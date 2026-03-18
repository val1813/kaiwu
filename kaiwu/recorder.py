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
