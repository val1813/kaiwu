"""任务记录器 — 记录任务结果到经验库和错误库

成功时：调用 DeepSeek 提炼经验摘要，存入 ExperienceStore
失败时：记录错误模式到 ErrorKB + 失败经验到 ExperienceStore

v0.2 新增：
- anchors 参数：记录决策锚点到 Session（高权重，永久保留）
- RecordLayer 分层：anchor / experience / log 三层不同权重
- distill_async()：后台异步蒸馏，不阻塞主流程

设计为 fire-and-forget 风格：所有操作都不会抛异常阻塞主流程。
"""

import json
import threading
from typing import Any, Optional

from loguru import logger

from kaiwu.config import (
    DEFAULT_TIMEOUT,
    MEMORY_LAYER_ANCHOR,
    MEMORY_LAYER_EXP,
    MEMORY_LAYER_LOG,
    MEMORY_LAYER_METHOD,
)
from kaiwu.llm_client import call_llm
from kaiwu.quota import check_quota, record_call
from kaiwu.storage import get_error_kb, get_experience_store


# ── 记忆分层 ──────────────────────────────────────────────────────

class RecordLayer:
    """记录分层：不同层级有不同的保留策略和注入权重

    - ANCHOR: 决策锚点，永久保留，注入时排在最前面
    - EXPERIENCE: 经验摘要，中权重，参与 few-shot
    - LOG: 操作日志，低权重，可定期清理，默认不参与注入
    """
    ANCHOR = MEMORY_LAYER_ANCHOR
    EXPERIENCE = MEMORY_LAYER_EXP
    LOG = MEMORY_LAYER_LOG

# ── DeepSeek 经验蒸馏提示词 ────────────────────────────────────────

_DISTILL_SYSTEM = """\
你是一位编程经验总结专家。
给你一个 AI 编程助手刚完成的任务信息，请提炼出可复用的经验摘要。

# 输出要求

严格以 JSON 格式返回：

```json
{
  "summary": "一句话总结做了什么、怎么做的",
  "key_steps": ["关键步骤1", "关键步骤2", "..."],
  "pitfalls": ["容易踩坑的地方"]
}
```

# 原则

1. summary 不超过 100 字，突出方法论而非具体代码
2. key_steps 最多 5 条，每条不超过 50 字
3. pitfalls 提炼出对后续类似任务有参考价值的注意事项
4. 只输出 JSON，不要有任何其他文字

# 严禁事项（防止干扰主 AI）

你的摘要会注入到另一个 AI 的上下文。为了避免你的知识与主 AI 冲突：

- 禁止写入具体数值（性能倍数、速度、大小、百分比等）
- 禁止写入年份断言（如"2024标准"、"最新的"）
- 禁止写入版本号断言（如"必须用 3.x"、"要求 v2 以上"）
- 禁止写入主观排名（如"最好的方案"、"标准组合"、"首选"）
- 禁止写入世界知识型事实（如公司信息、历史数据、科学常数）

只写：做了什么操作、用了什么方法、踩了什么坑、怎么绕过的。
用动词描述步骤（"配置…"、"安装…"、"检查…"），不要下结论性判断。
"""

# ── 轨迹审计提示词 ─────────────────────────────────────────────────

_AUDIT_SYSTEM = """\
你是编程方法论分析师。分析 AI 编程助手的执行轨迹，提炼可复用的方法论模式。

轨迹可能来自强模型（Opus/GPT-4o）或弱模型，你需要识别两类模式：
A. 最佳实践：强模型的高效路线，值得其他模型学习
B. 犯错教训：任何模型踩过的坑，后续应避免

# 输出格式
严格返回 JSON：
{
  "pivot_turn": 5,
  "pivot_description": "从直接修改配置改为先读取再增量修改",
  "pattern_type": "best_practice 或 pitfall",
  "pattern": {
    "situation": "需要修改已有配置文件时",
    "good_approach": "先读取现有内容，理解结构，再做增量修改",
    "bad_approach": "直接覆盖写入完整配置",
    "reason": "直接覆盖容易丢失已有配置项，导致其他功能异常"
  },
  "confidence": 0.8
}

# 规则
1. situation: 触发条件（什么时候适用），不超过30字
2. good_approach / bad_approach: 方法论（怎么做），不超过50字
3. reason: 为什么（一句话），不超过50字
4. 只提炼方法论，不写具体代码/路径/值/版本号
5. confidence: 0.5-1.0，越通用越高
6. pattern_type: best_practice（成功路线值得学习）或 pitfall（犯错模式需要避免）
7. 全部成功且无转折的短轨迹 → {"pivot_turn": null, "pattern": null, "confidence": 0}
8. 只输出 JSON，不要 markdown 代码块
"""


# ── 轨迹审计门控与引擎 ─────────────────────────────────────────────

def _should_audit(
    success: bool,
    turns: int,
    trace_steps: list,
    host_level: str,
) -> bool:
    """选择性审计 — 只审计有价值的轨迹

    设计原则：
    - strong 模型的轨迹更有价值（最佳实践 + 犯错模式都值得记录）
    - 所有模型的失败和转折都值得审计
    - 太短太简单的轨迹跳过，省 token
    """
    if not trace_steps:
        return False
    if len(trace_steps) < 3:
        return False

    failed_steps = sum(1 for s in trace_steps if not s.success)
    has_pivot = any(s.pivot for s in trace_steps)

    # ── strong 模型：积极学习（他的路线是最佳实践，他的错误是高价值教训）──
    if host_level == "strong":
        # 失败 → 必须记录（强模型的犯错模式极有价值，如 write 超长）
        if not success:
            return True
        # 有失败步骤 → 记录（强模型踩过的坑，弱模型更容易踩）
        if failed_steps >= 1:
            return True
        # 有 pivot → 记录（强模型主动换方向，说明原路线有问题）
        if has_pivot:
            return True
        # 长任务成功 → 记录（强模型的完整路线就是教科书）
        if success and turns >= 5:
            return True
        # 短任务全部成功 → 跳过（太简单，没什么可学的）
        return False

    # ── medium/weak 模型 ──
    # 失败 + 步骤多 → 分析哪里走错了
    if not success and turns >= 5:
        return True
    # 成功但经历过失败步骤 → 有转折点
    if success and failed_steps >= 2:
        return True
    # 主 AI 自标了 pivot → 一定审计
    if has_pivot:
        return True
    # 长任务成功 → 可能有值得提炼的经验
    if success and turns >= 6:
        return True
    return False


def _audit_trace(task, task_type, trace_steps, success, turns, host_level=""):
    """调用 DeepSeek 分析轨迹，提取方法论模式

    Returns:
        dict with pattern info, or None if no pattern found.
    """
    from kaiwu.quota import check_quota, record_call

    allowed, _ = check_quota()
    if not allowed:
        return None

    # 构建 user prompt
    level_hint = ""
    if host_level == "strong":
        level_hint = "（来自强模型 Opus/GPT-4o 级别，其成功路线是最佳实践，其犯错是高价值教训）"
    lines = [f"# 任务\n{task[:300]}"]
    lines.append(f"# 结果: {'成功' if success else '失败'}, {turns} 轮 {level_hint}")
    lines.append("# 执行轨迹")
    for s in trace_steps[:20]:
        marker = "OK" if s.success else "FAIL"
        pivot = " [PIVOT]" if s.pivot else ""
        lines.append(f"Turn {s.turn} [{marker}]{pivot}: {s.action} → {s.outcome}")

    try:
        raw = call_llm(
            messages=[
                {"role": "system", "content": _AUDIT_SYSTEM},
                {"role": "user", "content": "\n".join(lines)},
            ],
            max_tokens=300,
            temperature=0.3,
            timeout=DEFAULT_TIMEOUT,
            purpose="audit",
        )
        record_call()

        text = raw.strip()
        if text.startswith("```"):
            text_lines = text.split("\n")
            text_lines = [l for l in text_lines if not l.strip().startswith("```")]
            text = "\n".join(text_lines)

        data = json.loads(text)

        confidence = data.get("confidence", 0)
        pattern = data.get("pattern")
        if not pattern or confidence < 0.6:
            logger.debug(f"审计结果置信度不足: confidence={confidence}")
            return None

        # 验证 pattern 必要字段
        for key in ("situation", "good_approach", "bad_approach", "reason"):
            if not pattern.get(key):
                return None

        return {
            "pivot_turn": data.get("pivot_turn"),
            "pivot_description": data.get("pivot_description", ""),
            "pattern": pattern,
            "confidence": confidence,
        }
    except Exception as e:
        logger.debug(f"轨迹审计 LLM 调用失败: {e}")
        return None


def _is_universal_pattern(pattern_dict: dict, confidence: float) -> bool:
    """判断方法论是否为通用模式（不含项目特定词）

    高置信度 + 无项目特定词 → universal，存入时 project_name="" 使所有项目可见。
    """
    if confidence < 0.85:
        return False

    situation = pattern_dict.get("situation", "").lower()
    good = pattern_dict.get("good_approach", "").lower()
    bad = pattern_dict.get("bad_approach", "").lower()
    all_text = f"{situation} {good} {bad}"

    _project_specific = {
        # 具体文件名/格式
        ".vue", ".tsx", ".jsx", "package.json", "requirements.txt",
        "docker-compose", "nginx.conf", "webpack",
        # 具体框架
        "fastapi", "django", "flask", "express", "nextjs", "nuxt",
        # 具体数据库
        "mysql", "postgresql", "mongodb", "sqlite",
    }

    if any(kw in all_text for kw in _project_specific):
        return False

    return True


def _store_pattern(pattern_dict, task_type, turns, success, project_name, confidence: float = 0.7):
    """将方法论模式存入经验库"""
    from kaiwu.storage.experience import MEMORY_TAG_METHOD

    exp_store = get_experience_store()

    # 判断是否为通用方法论：universal 时清空 project_name，所有项目可见
    if _is_universal_pattern(pattern_dict, confidence):
        actual_project = ""
        logger.info(f"方法论标记为 universal (confidence={confidence}): {pattern_dict['situation'][:50]}")
    else:
        actual_project = project_name

    # situation 可能很短，拼接 good_approach 确保超过 15 字符的最低长度
    task_desc = f"[方法论] {pattern_dict['situation']}→{pattern_dict['good_approach']}"
    exp_store.record(
        task=task_desc,
        task_type=task_type,
        success=True,
        summary=f"{pattern_dict['situation']}→{pattern_dict['good_approach']}",
        key_steps=[
            f"推荐: {pattern_dict['good_approach']}",
            f"避免: {pattern_dict['bad_approach']}",
            f"原因: {pattern_dict['reason']}",
        ],
        turns=turns,
        memory_tag=MEMORY_TAG_METHOD,
        project_name=actual_project,
    )
    logger.info(f"方法论模式已存入: {pattern_dict['situation'][:50]}")


def audit_async(task, task_type, trace_steps, success, turns, project_name, host_level=""):
    """后台线程执行轨迹审计"""
    def worker():
        try:
            result = _audit_trace(task, task_type, trace_steps, success, turns, host_level)
            if result and result.get("pattern"):
                _store_pattern(result["pattern"], task_type, turns, success, project_name,
                               confidence=result.get("confidence", 0.7))
        except Exception as e:
            logger.debug(f"异步审计失败: {e}")

    t = threading.Thread(target=worker, name="audit-trace", daemon=True)
    t.start()


# ── plan vs trace 零 token 对比 ──────────────────────────────────

def _compare_plan_vs_trace(session_id: str, trace_steps: list) -> dict:
    """零 token 对比规划 vs 实际轨迹

    Returns:
        {"overlap": 0.0-1.0, "diverged": bool, "plan_steps": int, "trace_steps": int}
        空 dict 表示无法对比（无规划数据或无轨迹）
    """
    if not session_id or not trace_steps:
        return {}

    try:
        from kaiwu.session import SessionManager
        from kaiwu.storage.experience import _extract_keywords

        mgr = SessionManager()
        session_data = mgr.get(session_id)
        if not session_data:
            return {}

        plan_data = session_data.get("_plan_result", {})
        if not plan_data:
            return {}

        plan_steps = plan_data.get("steps", [])
        if not plan_steps:
            return {}

        # 提取 plan 关键词（steps 可能是 dict 列表或字符串列表）
        plan_texts = []
        for s in plan_steps:
            if isinstance(s, dict):
                plan_texts.append(s.get("action", "") or s.get("title", "") or str(s))
            else:
                plan_texts.append(str(s))
        plan_kw = set(_extract_keywords(" ".join(plan_texts)))

        # 提取 trace 关键词
        trace_kw = set(_extract_keywords(" ".join(s.action for s in trace_steps)))

        if not plan_kw or not trace_kw:
            return {}

        overlap = len(plan_kw & trace_kw) / max(len(plan_kw), len(trace_kw))

        return {
            "overlap": round(overlap, 2),
            "diverged": overlap < 0.3,
            "plan_steps": len(plan_steps),
            "trace_steps": len(trace_steps),
        }
    except Exception as e:
        logger.debug(f"plan vs trace 对比失败: {e}")
        return {}



def record_outcome(
    task: str,
    task_type: str,
    success: bool,
    tool_calls: Optional[list[dict]] = None,
    turns: int = 0,
    skip_distill: bool = False,
    error_summary: str = "",
    session_id: str = "",
    subtask_seq: int = 0,
    anchors: Optional[list[str]] = None,
    project_name: str = "",
    trace_steps: Optional[list] = None,
    host_level: str = "",
) -> dict[str, str]:
    """记录任务结果到经验库和错误库

    Args:
        task: 原始任务描述
        task_type: 任务分类（如 web, react, python_script 等）
        success: 任务是否成功
        tool_calls: 本次任务的工具调用序列（可选）
        turns: 完成任务花费的轮数
        error_summary: 失败时的错误摘要
        session_id: 会话 ID（传入则记录检查点）
        subtask_seq: 子任务序号（> 0 时记录检查点）
        anchors: 本轮产生的决策锚点（高权重，存入 Session ANCHOR 层）
        project_name: 所属项目名（空则全局共享，非空则经验归属该项目）
        trace_steps: 执行轨迹步骤列表（可选，list[TraceStep]）
        host_level: 主AI能力等级（传给审计门控）

    Returns:
        dict: {"message": str, "exp_id": str}
        message 是确认消息，exp_id 是经验ID（成功时非空，失败时为空）
    """
    try:
        exp_id = ""
        if success:
            result, exp_id = _record_success(task, task_type, tool_calls, turns,
                                     project_name, skip_distill)
        else:
            result = _record_failure(task, task_type, error_summary, turns, project_name)

        # 记录会话检查点
        if session_id and subtask_seq > 0:
            try:
                from kaiwu.session import SessionManager
                mgr = SessionManager()
                summary = task[:80] if success else f"[失败] {error_summary[:60]}"
                mgr.add_checkpoint(session_id, subtask_seq, summary)

                # 检测是否所有子任务完成
                session = mgr.resolve_session(session_id)
                if session and session.subtasks:
                    all_done = all(
                        st.status == "completed" for st in session.subtasks
                    )
                    if all_done:
                        mgr.complete_session(session_id, success=True)
                        result += "; 会话所有子任务已完成，自动标记结束"

                result += f"; 检查点已记录 (子任务 {subtask_seq})"
            except Exception as e:
                logger.debug(f"记录会话检查点失败: {e}")

        # 记录决策锚点到 Session（ANCHOR 层：永久保留，高权重）
        if session_id and anchors:
            try:
                from kaiwu.session import SessionManager
                mgr = SessionManager()
                mgr.update_anchors(session_id, anchors)
                result += f"; {len(anchors)} 条决策锚点已记录"
                logger.info(f"锚点记录到会话 {session_id}: {anchors}")
            except Exception as e:
                logger.debug(f"记录决策锚点失败: {e}")

        # 记录错误到 Session 的 error_history（用于循环检测）
        if session_id and not success and error_summary.strip():
            try:
                from kaiwu.session import SessionManager
                from kaiwu.storage.error_kb import _fingerprint, _extract_error_key
                mgr = SessionManager()
                fp = _fingerprint(error_summary)
                error_type = _extract_error_key(error_summary)
                mgr.record_error(session_id, error_type, fp)
                logger.debug(f"错误已记录到会话 error_history: {error_type[:50]}")
            except Exception as e:
                logger.debug(f"记录错误到会话失败: {e}")

        # plan vs trace 零 token 对比（路线偏离时提升审计优先级）
        already_auditing = trace_steps and _should_audit(success, turns, trace_steps, host_level)
        if trace_steps and session_id:
            comparison = _compare_plan_vs_trace(session_id, trace_steps)
            if comparison.get("diverged") and not already_auditing:
                audit_async(task, task_type, trace_steps, success, turns, project_name, host_level)
                result += "; 路线偏离审计已启动"
                already_auditing = True

        # 轨迹审计
        if trace_steps and not already_auditing and _should_audit(success, turns, trace_steps, host_level):
            audit_async(task, task_type, trace_steps, success, turns, project_name, host_level)
            result += "; 轨迹审计已启动"

        return {"message": result, "exp_id": exp_id}
    except Exception as e:
        # fire-and-forget: 永远不阻塞主流程
        logger.warning(f"记录任务结果失败（静默忽略）: {e}")
        return {"message": f"记录失败（不影响主流程）: {e}", "exp_id": ""}


def _record_success(
    task: str,
    task_type: str,
    tool_calls: Optional[list[dict]],
    turns: int,
    project_name: str = "",
    skip_distill: bool = False,
) -> tuple[str, str]:
    """记录成功任务

    Returns:
        (message, exp_id) 元组。exp_id 为空字符串表示未记录。
    """
    from kaiwu.storage import get_experience_store
    exp_store = get_experience_store()

    # 按需蒸馏：简单任务（<=3轮）跳过 DeepSeek 调用，直接本地存
    summary = ""
    key_steps: list[str] = []

    allowed, _ = check_quota()
    if allowed and task.strip() and turns > 3 and not skip_distill:
        summary, key_steps = _distill_experience(task, task_type, tool_calls, turns)

    # 未蒸馏时用 task 本身做 fallback summary（保证经验库不为空）
    if not summary and task.strip():
        summary = task[:200]

    # 存入经验库（自动推断 memory_tag，传入 project_name）
    exp = exp_store.record(
        task=task,
        task_type=task_type,
        success=True,
        summary=summary,
        key_steps=key_steps,
        turns=turns,
        project_name=project_name,
    )

    if exp:
        logger.info(f"成功经验已记录: {exp.exp_id}")

        # 静默上传到云端（已登录用户）
        _try_cloud_upload(task, task_type, summary, key_steps)

        return (
            f"成功经验已记录 (id={exp.exp_id}), 摘要: {summary[:80] or '(无DeepSeek蒸馏)'}",
            exp.exp_id,
        )
    return "任务描述过短，跳过经验记录", ""


def _record_failure(
    task: str,
    task_type: str,
    error_summary: str,
    turns: int,
    project_name: str = "",
) -> str:
    """记录失败任务"""
    messages: list[str] = []

    # 记录到错误库
    if error_summary.strip():
        kb = get_error_kb()
        fp = kb.record_error(error_summary, context=task[:200])
        messages.append(f"错误模式已记录到 ErrorKB (fp={fp})")

        # 静默上传错误到云端
        _try_cloud_upload_error(error_summary, task, task_type)

    # 记录失败经验（不调 DeepSeek，节省 token）
    exp_store = get_experience_store()
    exp = exp_store.record(
        task=task,
        task_type=task_type,
        success=False,
        turns=turns,
        error_summary=error_summary,
        project_name=project_name,
    )

    if exp:
        messages.append(f"失败经验已记录 (id={exp.exp_id})")

    return "; ".join(messages) if messages else "记录完成（无有效内容可存储）"


def _distill_experience(
    task: str,
    task_type: str,
    tool_calls: Optional[list[dict]],
    turns: int,
) -> tuple[str, list[str]]:
    """调用 DeepSeek 蒸馏经验摘要

    Returns:
        (summary, key_steps) 元组。调用失败返回 ("", [])。
    """
    try:
        # 组装任务信息
        user_parts = [
            f"# 任务\n\n{task[:500]}",
            f"\n# 任务类型: {task_type}",
            f"\n# 完成轮数: {turns}",
        ]

        if tool_calls:
            # 只取关键工具调用，避免 token 爆炸
            calls_summary = []
            for tc in tool_calls[:15]:
                name = tc.get("name", tc.get("tool", "unknown"))
                result = str(tc.get("result", ""))[:100]
                calls_summary.append(f"- {name}: {result}")
            user_parts.append(f"\n# 工具调用序列\n\n" + "\n".join(calls_summary))

        raw = call_llm(
            messages=[
                {"role": "system", "content": _DISTILL_SYSTEM},
                {"role": "user", "content": "\n".join(user_parts)},
            ],
            max_tokens=300,
            temperature=0.3,
            timeout=DEFAULT_TIMEOUT,
            purpose="distill",
        )
        record_call()

        # 解析 JSON
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        data = json.loads(text)
        summary = data.get("summary", "")[:200]
        key_steps = data.get("key_steps", [])[:5]

        return summary, key_steps

    except Exception as e:
        logger.debug(f"经验蒸馏失败（不影响记录）: {e}")
        return "", []


# ── 云端静默上传 ─────────────────────────────────────────────────

def _try_cloud_upload(
    task: str, task_type: str, summary: str, key_steps: list[str]
):
    """静默上传成功经验到云端（v1.0 预留，暂不启用）"""
    if not summary:
        return
    try:
        from kaiwu.storage.sync import CloudSync

        client = CloudSync()
        if not client.is_logged_in:
            return

        client.contribute({
            "task_type":    task_type,
            "summary":      summary,
            "key_steps":    key_steps,
            "success":      True,
        })
    except Exception as e:
        logger.debug(f"云端上传跳过: {e}")


def _try_cloud_upload_error(
    error_summary: str, task: str, task_type: str
):
    """静默上传错误模式到云端（v1.0 预留，暂不启用）"""
    if not error_summary.strip():
        return
    try:
        from kaiwu.storage.sync import CloudSync

        client = CloudSync()
        if not client.is_logged_in:
            return

        client.contribute({
            "task_type":  f"error:{task_type}",
            "error_type": error_summary,
            "success":    False,
        })
    except Exception as e:
        logger.debug(f"云端错误上传跳过: {e}")


# ── 异步蒸馏 ────────────────────────────────────────────────────

def distill_async(
    exp_id: str,
    task: str,
    task_type: str,
    turns: int,
    project_name: str = "",
) -> None:
    """后台线程异步蒸馏经验摘要，完成后回写经验库

    用于同系列模型场景：先秒返结果，后台慢慢蒸馏。
    """
    def _worker():
        try:
            summary, key_steps = _distill_experience(task, task_type, None, turns)
            if not summary:
                return

            # 回写到经验库
            exp_store = get_experience_store()
            exp_store.update_distill(exp_id, summary, key_steps)
            logger.info(f"异步蒸馏完成: {exp_id}, summary={summary[:60]}")
        except Exception as e:
            logger.debug(f"异步蒸馏失败（静默）: {e}")

    t = threading.Thread(target=_worker, daemon=True, name=f"distill-{exp_id[:8]}")
    t.start()
