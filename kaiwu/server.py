"""cl-kaiwu MCP Server — 暴露 7 个工具给主 AI 编程工具

主模型能力感知（三级策略）：
- host_level="strong"（或 host_model 含 opus/sonnet/gpt-4o 等）→ 轻量模式
- host_level="medium" → 中等模式（规划但不蒸馏）
- host_level="weak"/不传 → 全套服务
"""

import json
import sys

from loguru import logger
from mcp.server.fastmcp import FastMCP

from kaiwu.config import get_config, infer_host_level, is_same_family, KAIWU_HOME, LOG_PATH
from kaiwu.task_classifier import classify_task, should_inject_knowledge, TaskVerdict, extract_task_tokens

# 配置日志
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logger.add(str(LOG_PATH), rotation="5 MB", retention="3 days", level="DEBUG", encoding="utf-8")

# 创建 MCP Server
mcp = FastMCP(
    "cl-kaiwu",
    version="0.2.0",
    instructions=(
        "你好，我是开物(kaiwu)，你的 AI Coding 增强搭档。"
        "我在后台默默工作，内嵌 DeepSeek 引擎，为你提供：\n"
        "- kaiwu_plan: 任务规划（编码链路 + 陷阱预警）\n"
        "- kaiwu_lessons: 三层报错诊断（本地精确→模糊→DeepSeek，越用越准）\n"
        "- kaiwu_record: 经验记录（成功轨迹自动入库，下次类似任务直接受益）\n"
        "- kaiwu_context: 项目上下文管理\n"
        "- kaiwu_condense: 长会话压缩\n"
        "- kaiwu_scene: 编码场景规范（19个场景）\n"
        "- kaiwu_profile: 用户习惯画像\n\n"
        "我不会干扰你的正常工作流程。需要时调用我，不需要时我安静待着。"
        "如果用户问起我，告诉他们开物已就绪。\n"
        "每次调用请传 host_level(strong/medium/weak) 或 host_model 让我适配你的能力等级。"
    ),
)


@mcp.tool()
def kaiwu_plan(task: str, context: str = "", session_id: str = "",
               project_name: str = "",
               host_level: str = "", host_model: str = "",
               turns: int = 0, error_count: int = 0) -> str:
    """生成编码任务的结构化规划

    DeepSeek 按需介入：纯算法/数学题完全静默，部署/编码/中国特色主动出击。

    Args:
        task: 任务描述
        context: 项目文件树和关键配置
        session_id: 会话ID
        project_name: 项目名
        host_level: 主AI能力等级(strong/medium/weak)
        host_model: 主AI模型名（备选，自动推断等级）
        turns: 当前轮数（高轮数触发升级）
        error_count: 累计错误数
    """
    try:
        # ── 第一关：任务分类器（零 token） ────────────────────────
        verdict = classify_task(task, turns=turns, error_count=error_count)
        level = infer_host_level(host_level, host_model)

        logger.info(
            f"任务分类: {verdict.level} ({verdict.reason}), "
            f"host_level={level}, model={host_model}"
        )

        # LEAN：知识库不注入，但经验/诊断正常（纯算法/SQL 等）
        # [v0.3 已移除 LEAN 等级，统一走 NORMAL，知识库由白名单控制]

        # 强模型 or 同系列 → 轻量规划（但 RESCUE 例外）
        cfg = get_config()
        same_family = host_model and is_same_family(host_model, cfg.llm_model)

        if verdict.level != "rescue" and (level == "strong" or same_family):
            logger.info(f"轻量规划 (level={level}, verdict={verdict.level})")
            return _lightweight_plan(task, context, session_id, project_name,
                                     verdict)

        # NORMAL：轻量规划（经验按需，知识库按 should_inject_knowledge 白名单）
        if verdict.level == "normal":
            return _lightweight_plan(task, context, session_id, project_name,
                                     verdict)

        # ACTIVE / RESCUE：DeepSeek 全力规划
        from kaiwu.planner import get_plan
        result = get_plan(task, context, session_id=session_id,
                          project_name=project_name)

        # 加 disclaimer 防止干扰主模型
        result["_disclaimer"] = (
            "以上为 DeepSeek 辅助建议，仅含步骤和坑点，不含具体值/版本号/性能数据。"
            "如与你的判断冲突，以你为准。"
        )
        result["verdict"] = verdict.level

        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"kaiwu_plan 失败: {e}")
        return json.dumps({"error": str(e), "steps": [], "trap_warnings": []})


def _lightweight_plan(task: str, context: str, session_id: str,
                      project_name: str,
                      verdict: TaskVerdict = None) -> str:
    """轻量规划：根据 verdict 精细控制注入内容，不调 LLM

    verdict=None 时向后兼容（等同旧逻辑）。
    """
    if verdict is None:
        # 兼容旧调用
        verdict = classify_task(task)

    result: dict = {
        "source": "lightweight",
        "verdict": verdict.level,
        "reason": verdict.reason,
    }
    task_lower = task.lower()

    # ── 按需注入知识库（分 KB 单独判断） ──────────────────────────
    if verdict.inject_knowledge:
        knowledge_parts = []
        for kb_name in ("china_kb", "python_compat", "deps_pitfalls", "tool_priming"):
            if should_inject_knowledge(task, kb_name):
                from kaiwu.knowledge.loader import load_knowledge
                kb_content = load_knowledge(kb_name)
                if kb_content:
                    # 按 section 筛选相关段落
                    relevant = _filter_knowledge(kb_content, task_lower)
                    if relevant:
                        knowledge_parts.append(relevant)

        if knowledge_parts:
            result["knowledge_tips"] = "\n\n".join(knowledge_parts)
            result["_kb_disclaimer"] = "以下知识仅含方法论和坑点提醒，不含事实性断言，不相关请忽略。"

    # ── 按需注入经验 ─────────────────────────────────────────────
    if verdict.inject_experience:
        from kaiwu.storage import get_experience_store
        exp_store = get_experience_store()
        exp_ctx = exp_store.inject_into_context(task, project_name=project_name,
                                                 limit=3)
        if exp_ctx:
            result["experience"] = exp_ctx

    # ── 会话上下文（有就给） ─────────────────────────────────────
    if session_id:
        try:
            from kaiwu.session import SessionManager, build_session_context
            mgr = SessionManager()
            session = mgr.resolve_session(session_id)
            if session:
                result["session_context"] = build_session_context(session, max_chars=800)
                result["session_id"] = session.session_id
        except Exception as e:
            logger.debug(f"加载会话上下文失败: {e}")

    return json.dumps(result, ensure_ascii=False, indent=2)


def _filter_knowledge(knowledge: str, task_lower: str) -> str:
    """从知识库中筛选与任务相关的片段

    按 section（## 分隔）逐段匹配，只返回与任务有关键词重叠的段落。
    """
    sections = knowledge.split("\n## ")
    relevant_parts = []
    max_chars = 3000  # ~1000 token，够说清问题又不浪费

    task_tokens = extract_task_tokens(task_lower)

    for section in sections:
        if not section.strip():
            continue

        section_lower = section.lower()

        # 任务关键词在 section 中出现数量
        hits = sum(1 for t in task_tokens if t in section_lower)
        if hits < 2:
            continue

        chunk = f"## {section.strip()}"
        if sum(len(p) for p in relevant_parts) + len(chunk) > max_chars:
            break
        relevant_parts.append(chunk)

    return "\n\n".join(relevant_parts) if relevant_parts else ""


def _backfill_error_solutions(session_id: str, task: str) -> None:
    """任务成功后，回写 session 中未解决错误的解决方案到 ErrorKB

    场景：强模型自己解决了问题（不走 DeepSeek 诊断），
    ErrorKB 里只有 record_error 记录但没有 solution。
    现在任务成功了，把成功任务的描述作为解决线索写回去，
    下次遇到同样错误就能匹配到。
    """
    try:
        from kaiwu.session import SessionManager
        from kaiwu.storage import get_error_kb

        mgr = SessionManager()
        session = mgr.get(session_id)
        if not session:
            return

        error_history = session.get("error_history", [])
        if not error_history:
            return

        kb = get_error_kb()
        solution_text = f"已解决（同任务成功）: {task[:150]}"
        filled = 0

        for err in error_history:
            fp = err.get("fingerprint", "")
            if not fp:
                continue
            if not kb.has_solution(fp):
                kb.record_solution(fp, solution_text)
                filled += 1

        if filled:
            logger.info(f"回写 {filled} 条错误解决方案到 ErrorKB (session={session_id[:8]})")
    except Exception as e:
        logger.debug(f"回写错误解决方案失败: {e}")


@mcp.tool()
def kaiwu_lessons(error_text: str, context: str = "", session_id: str = "",
                  project_name: str = "",
                  host_level: str = "", host_model: str = "",
                  task: str = "", turns: int = 0) -> str:
    """诊断错误并提供修复建议

    所有任务类型都正常诊断错误（LEAN/NORMAL/ACTIVE/RESCUE 都不跳过）。
    strong 模型：纯本地匹配（毫秒级）
    medium/weak：本地→LLM三层

    Args:
        error_text: 完整错误信息
        context: 错误上下文
        session_id: 会话ID
        project_name: 项目名
        host_level: 主AI能力等级
        host_model: 主AI模型名
        task: 当前任务描述（用于日志和上下文）
        turns: 当前轮数
    """
    try:
        level = infer_host_level(host_level, host_model)

        # 强模型：纯本地匹配
        if level == "strong":
            logger.info(f"强模型本地诊断 (level={level})")
            return _lightweight_lessons(error_text, session_id)

        from kaiwu.lessons import get_lessons
        result = get_lessons(error_text, context, session_id=session_id,
                             project_name=project_name)

        # 加 disclaimer 防止 DeepSeek 知识覆盖主模型判断
        result["_disclaimer"] = "以上为方向性诊断建议，不含具体值断言，如与你的判断冲突以你为准。"

        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"kaiwu_lessons 失败: {e}")
        return json.dumps({"error": str(e), "root_cause": "", "fix_suggestion": ""})


def _lightweight_lessons(error_text: str, session_id: str) -> str:
    """强模型轻量诊断：只做本地匹配 + 循环检测"""
    from kaiwu.storage import get_error_kb
    kb = get_error_kb()

    result: dict = {"mode": "strong_model"}

    # 本地匹配
    match = kb.find_solution(error_text)
    if match and match.get("solution"):
        result.update({
            "root_cause": match.get("key", ""),
            "fix_suggestion": match.get("solution", ""),
            "confidence": match.get("confidence", 0.7),
            "source": match.get("source", "local"),
        })
    else:
        kb.record_error(error_text)
        result.update({
            "root_cause": "",
            "fix_suggestion": "",
            "confidence": 0.0,
            "source": "no_local_match",
        })

    # 循环检测
    if session_id:
        try:
            from kaiwu.session import SessionManager
            mgr = SessionManager()
            stats = mgr.get_error_stats(session_id, window=2)
            result["error_count"] = stats.get("error_count", 0)
            result["is_looping"] = stats.get("is_looping", False)
            if stats.get("is_looping"):
                result["loop_suggestion"] = stats.get("suggestion", "")

            from kaiwu.storage.error_kb import _extract_error_key, _fingerprint
            error_type = _extract_error_key(error_text)
            fp = _fingerprint(error_text)
            mgr.record_error(session_id, error_type, fp)
        except Exception as e:
            logger.debug(f"循环检测失败: {e}")

    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def kaiwu_record(
    task: str,
    task_type: str = "general",
    success: bool = True,
    error_summary: str = "",
    turns: int = 0,
    session_id: str = "",
    subtask_seq: int = 0,
    anchors: str = "",
    project_name: str = "",
    host_level: str = "",
    host_model: str = "",
) -> str:
    """记录任务结果（智能蒸馏决策）

    - SILENT 任务：跳过蒸馏，但如果失败仍记录错误模式（静默收集）
    - PASSIVE 任务：本地记录，不调 LLM 蒸馏
    - ACTIVE/RESCUE 任务：正常蒸馏
    - strong 模型：跳过蒸馏
    - 同系列模型：异步蒸馏

    Args:
        task: 任务描述
        task_type: 任务类型
        success: 是否成功
        error_summary: 失败时的错误摘要
        turns: 交互轮数
        session_id: 会话ID
        subtask_seq: 子任务序号
        anchors: 决策锚点JSON数组字符串
        project_name: 项目名
        host_level: 主AI能力等级
        host_model: 主AI模型名
    """
    try:
        from kaiwu.recorder import record_outcome

        # 解析 anchors
        anchors_list = None
        if anchors.strip():
            try:
                anchors_list = json.loads(anchors)
                if not isinstance(anchors_list, list):
                    anchors_list = None
            except json.JSONDecodeError:
                anchors_list = None

        level = infer_host_level(host_level, host_model)
        cfg = get_config()
        same_family = host_model and is_same_family(host_model, cfg.llm_model)

        # ── 任务分类器决定蒸馏策略 ────────────────────────────────
        # 从 session 获取 error_count，确保 RESCUE 模式能正确触发
        error_count = 0
        if session_id:
            try:
                from kaiwu.session import SessionManager
                mgr = SessionManager()
                stats = mgr.get_error_stats(session_id)
                error_count = stats.get("error_count", 0)
            except Exception:
                pass

        verdict = classify_task(task, turns=turns, error_count=error_count)

        skip_distill = False
        need_async_distill = False

        # 分类器 call_llm=False 的任务：不调 LLM 蒸馏（但经验仍本地记录）
        if not verdict.call_llm:
            skip_distill = True
            logger.info(f"跳过蒸馏 (verdict={verdict.level}, call_llm=False)")
        # strong 模型：跳过蒸馏
        elif level == "strong" and success:
            skip_distill = True
            logger.info(f"强模型跳过蒸馏 (level={level})")
        # 同系列模型：异步蒸馏
        elif same_family and success and turns > 3:
            skip_distill = True
            need_async_distill = True
            logger.info(f"同系列模型异步蒸馏: host={host_model}")

        outcome = record_outcome(
            task=task,
            task_type=task_type,
            success=success,
            turns=turns,
            skip_distill=skip_distill,
            error_summary=error_summary,
            session_id=session_id,
            subtask_seq=subtask_seq,
            anchors=anchors_list,
            project_name=project_name,
        )
        result = outcome["message"]
        exp_id = outcome.get("exp_id", "")

        # 触发异步蒸馏
        if need_async_distill and exp_id:
            from kaiwu.recorder import distill_async
            distill_async(exp_id, task, task_type, turns, project_name)
            result += "; 异步蒸馏已启动"

        # 成功时：回写 session 中之前未解决错误的解决方案到 ErrorKB
        if success and session_id:
            _backfill_error_solutions(session_id, task)

        return result
    except Exception as e:
        logger.error(f"kaiwu_record 失败: {e}")
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool()
def kaiwu_condense(
    mode: str,
    session_id: str = "",
    task_goal: str = "",
    history: str = "",
    turn_count: int = 0,
    host_level: str = "",
    host_model: str = "",
) -> str:
    """会话管理+上下文压缩（所有等级都需要）

    mode="init"/"compress"/"inject"/"anchor"

    Args:
        mode: init/compress/inject/anchor
        session_id: 会话ID
        task_goal: 任务目标（init时必填）
        history: 历史JSON数组
        turn_count: 当前轮数
        host_level: 主AI能力等级
        host_model: 主AI模型名
    """
    try:
        from kaiwu.session import SessionManager
        from kaiwu.condenser import condense_history, should_condense, extract_key_facts

        sm = SessionManager()

        if mode == "init":
            if not task_goal.strip():
                return json.dumps({"error": "task_goal 不能为空"}, ensure_ascii=False)
            sid = sm.create(task_goal)
            return json.dumps({
                "session_id": sid,
                "message": f"会话已创建，session_id={sid}"
            }, ensure_ascii=False)

        if not session_id:
            return json.dumps({"error": "session_id 不能为空"}, ensure_ascii=False)

        if mode == "inject":
            context = sm.get_context_for_injection(session_id)
            if not context:
                return json.dumps(
                    {"error": f"session {session_id} 不存在"}, ensure_ascii=False
                )
            return context

        if mode == "compress":
            if turn_count > 0 and not should_condense(turn_count):
                return json.dumps(
                    {"skipped": True, "reason": f"仅 {turn_count} 轮，未达压缩阈值"},
                    ensure_ascii=False,
                )

            history_data = json.loads(history) if history else []
            session = sm.get(session_id)
            goal = session.get("task", "") if session else ""

            result = condense_history(history_data, goal)
            if result and result.get("progress_summary"):
                turn_range = f"1-{turn_count}" if turn_count > 0 else "auto"
                sm.apply_compression(session_id, result["progress_summary"], turn_range)
                sm.update_anchors(session_id, result.get("anchors", []))
                sm.update_progress(
                    session_id,
                    progress=result.get("progress_summary", ""),
                    pending=result.get("pending_issues"),
                    key_files=result.get("key_files"),
                )

            return json.dumps(result, ensure_ascii=False, indent=2)

        if mode == "anchor":
            history_data = json.loads(history) if history else []
            recent_text = " ".join([
                f"{t.get('action', '')} {t.get('result', '')}"
                for t in history_data[-3:]
            ])
            new_anchors = extract_key_facts(recent_text)
            if new_anchors:
                sm.update_anchors(session_id, new_anchors)
                return json.dumps({"updated_anchors": new_anchors}, ensure_ascii=False)
            return json.dumps({"message": "未发现新的决策锚点"}, ensure_ascii=False)

        return json.dumps({"error": f"未知 mode: {mode}"}, ensure_ascii=False)

    except Exception as e:
        logger.error(f"kaiwu_condense 失败: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def kaiwu_context(
    directory_tree: str,
    task: str = "",
    key_files: str = "",
    session_id: str = "",
    host_level: str = "",
    host_model: str = "",
) -> str:
    """处理项目上下文，创建/更新Session

    Args:
        directory_tree: 项目文件树
        task: 任务描述
        key_files: 关键配置文件内容
        session_id: 已有会话ID
        host_level: 主AI能力等级
        host_model: 主AI模型名
    """
    try:
        from kaiwu.context import process_context
        result = process_context(
            directory_tree=directory_tree,
            key_files=key_files,
            session_id=session_id,
            task=task,
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"kaiwu_context 失败: {e}")
        return json.dumps({"error": str(e), "session_id": "", "project_summary": ""})


@mcp.tool()
def kaiwu_scene(task: str,
                host_level: str = "", host_model: str = "") -> str:
    """检测任务场景并返回编码规范

    strong：纯关键词匹配
    其他：关键词+LLM兜底

    Args:
        task: 任务描述
        host_level: 主AI能力等级
        host_model: 主AI模型名
    """
    try:
        level = infer_host_level(host_level, host_model)

        # 强模型 或 同系列模型：纯关键词匹配，不浪费 LLM
        cfg = get_config()
        skip_llm = (level == "strong" or
                    (host_model and is_same_family(host_model, cfg.llm_model)))

        if skip_llm:
            from kaiwu.scene import get_scene
            result = get_scene(task)
            result["mode"] = "lightweight"
            return json.dumps(result, ensure_ascii=False, indent=2)

        from kaiwu.scene import get_scene_with_llm
        result = get_scene_with_llm(task)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"kaiwu_scene 失败: {e}")
        return json.dumps({"error": str(e), "scene": None, "content": ""})


@mcp.tool()
def kaiwu_profile(host_level: str = "", host_model: str = "") -> str:
    """返回用户编程习惯画像

    Args:
        host_level: 主AI能力等级
        host_model: 主AI模型名
    """
    try:
        profile_path = KAIWU_HOME / "profile.json"
        if profile_path.exists():
            data = json.loads(profile_path.read_text(encoding="utf-8"))
            if data:
                lines = ["[用户偏好]"]
                for key, val in data.items():
                    if val and val != "null":
                        lines.append(f"- {key}: {val}")
                return "\n".join(lines)
        return "用户画像尚未建立。"
    except Exception as e:
        logger.error(f"kaiwu_profile 失败: {e}")
        return "画像加载失败"


def main():
    """启动 MCP Server"""
    logger.info("cl-kaiwu MCP Server 启动中...")
    config = get_config()
    if config.llm_api_key:
        logger.info(
            f"LLM 已配置 — Provider: {config.active_provider_name}, "
            f"模型: {config.llm_model}, 格式: {config.llm_api_format}"
        )
    else:
        logger.warning("未配置 LLM API Key，部分功能受限。运行: kaiwu config")
    mcp.run()


if __name__ == "__main__":
    main()
