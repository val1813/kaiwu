"""规划器 — 调用 DeepSeek 生成结构化任务规划

接收用户任务描述，加载知识库和历史经验，
让 DeepSeek 以"资深架构师"身份生成包含步骤、陷阱警告、
技术栈、影响文件、置信度的结构化规划建议。

v0.2.1 新增字段（基于 Self-Planning + Agentless 研究）：
- edge_cases: 显式列出边界情况，防止小模型遗漏
- verify: 可执行的验证步骤，支持 lint-fix-retry 循环
- reuse: 可复用的已有代码/库，避免重复实现（Agentless 精准定位思路）
- difficulty_map: 步骤难度标注，帮助主 AI 判断是否需要补充上下文

规划结果是建议性质（不是命令），最终决策由主 AI 工具做。
"""

import json
from typing import Any

from loguru import logger

from kaiwu.config import DEFAULT_TIMEOUT, DEFAULT_MAX_TOKENS
from kaiwu.llm_client import call_llm
from kaiwu.quota import check_quota, record_call
from kaiwu.knowledge.loader import load_all_knowledge
from kaiwu.storage import get_experience_store
from kaiwu.task_classifier import extract_task_tokens

# ── 系统提示词 ──────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
你是一位结构化规划助手，帮 AI 编程助手拆分步骤和识别风险。

# 你的职责边界（严格遵守）

你只负责：
1. 拆分任务步骤（做什么，顺序是什么）
2. 警告容易踩的坑（trap_warnings）
3. 标注哪些步骤是难点
4. 列出需要关注的边界情况

你绝对不能做：
- 给出具体的代码实现、具体的配置值、具体的数字常量
- 猜测 API 返回值、函数参数值、阈值等具体数值
- 推荐主 AI 不熟悉的库/框架（除非用户明确要求）
- 对主 AI 已经做出的判断给出不同答案
- 写入年份断言（如"2024标准"、"最新版本"）
- 写入性能断言（如"快10倍"、"提升50%"）
- 写入主观排名（如"最好的方案"、"首选"、"唯一正确"）
- 写入世界知识型事实（如公司信息、科学常数、历史数据）

你的输出会作为参考注入主 AI 的上下文。如果你给了错误的具体值，
主 AI 可能会盲从，导致错误。所以：步骤用动词描述（"查找..."、"修改..."），
不要写死具体值。

# 输出格式

严格返回 JSON：
```json
{
  "steps": [{"seq": 1, "action": "动作描述", "reason": "原因"}],
  "trap_warnings": ["踩坑点及规避方法（每条<50字）"],
  "tech_stack": ["涉及的技术/框架/库"],
  "affected_files": ["可能修改的文件路径"],
  "confidence": 0.85,
  "anchors": ["类别: 内容（原因）"],
  "subtasks": [{"seq": 1, "title": "子任务", "depends_on": [], "checkpoint": "验证标志"}],
  "edge_cases": ["边界情况 + 具体处理方式"],
  "verify": "可执行的验证命令",
  "reuse": ["可复用的已有代码/库"],
  "difficulty_map": [{"step": 1, "level": "easy|medium|hard", "reason": "原因"}]
}
```

# 规则

1. 有文件树时基于实际路径规划，识别已有模块避免重复
2. 有依赖配置时据此判断技术栈
3. 步骤 3-7 步，不过度细化
4. trap_warnings 最重要，列出容易踩的坑
5. edge_cases 每条必须含具体处理方式
6. verify 给可直接执行的命令，不要模糊指令
7. subtasks 仅步骤>=5时拆分
8. anchors 只记约束性决策，每条<50字，无决策则空数组
9. difficulty_map: easy=单文件操作, medium=单模块功能, hard=跨文件/架构/并发
10. 注意中国环境：镜像源、UTF-8/GBK、Windows路径
11. 只输出 JSON

# 会话上下文规则

有会话上下文时：遵循已有锚点，不重复已完成步骤，从当前进度继续。
"""

# ── 空规划（兜底） ──────────────────────────────────────────────────

_EMPTY_PLAN: dict[str, Any] = {
    "steps": [],
    "trap_warnings": [],
    "tech_stack": [],
    "affected_files": [],
    "confidence": 0.0,
    "source": "empty",
}


def get_plan(task: str, context: str = "", session_id: str = "",
             project_name: str = "") -> dict[str, Any]:
    """调用 DeepSeek 为任务生成结构化规划

    Args:
        task: 用户的原始任务描述
        context: 可选的额外上下文（如当前目录结构、已有代码片段）
        session_id: 会话 ID（传入则注入历史上下文）
        project_name: 项目名（传入则经验检索优先同项目）

    Returns:
        包含 steps, trap_warnings, tech_stack, affected_files, confidence, session_id 的字典。
        出错时返回空规划（confidence=0）。
    """
    if not task.strip():
        return {**_EMPTY_PLAN, "source": "empty"}

    # ── 检查额度 ───────────────────────────────────────────────
    allowed, msg = check_quota()
    if not allowed:
        logger.info(f"规划被限流: {msg}")
        return {**_EMPTY_PLAN, "source": "quota_exceeded", "message": msg}

    # ── 按需加载知识库（仅高风险任务才注入，省 token）─────────
    _risk_keywords = {"部署", "deploy", "编码", "encoding", "路径", "path",
                      "gbk", "utf", "npm", "pip", "镜像", "proxy", "nginx",
                      "windows", "权限", "permission", "cors", "ssl"}
    task_lower = task.lower()
    need_knowledge = not context or any(kw in task_lower for kw in _risk_keywords)
    knowledge = ""
    if need_knowledge:
        knowledge = _filter_knowledge_for_task(task_lower)

    # ── 加载相关经验 ───────────────────────────────────────────
    exp_store = get_experience_store()
    experience_context = exp_store.inject_into_context(task, project_name=project_name)

    # ── 加载会话上下文 ─────────────────────────────────────────
    session_ctx = ""
    resolved_session_id = ""
    if session_id:
        try:
            from kaiwu.session import SessionManager, build_session_context
            mgr = SessionManager()
            session = mgr.resolve_session(session_id)
            if session:
                session_ctx = build_session_context(session)
                resolved_session_id = session.session_id
        except Exception as e:
            logger.debug(f"加载会话上下文失败: {e}")

    # ── 组装用户消息 ───────────────────────────────────────────
    user_parts = [f"# 任务\n\n{task}"]

    if session_ctx:
        user_parts.append(f"\n{session_ctx}")

    if context:
        user_parts.append(f"\n# 补充上下文\n\n{context}")

    if knowledge:
        user_parts.append(f"\n# 知识库\n\n{knowledge}")

    if experience_context:
        user_parts.append(f"\n# 历史经验\n\n{experience_context}")

    # ── 加载用户记忆 ───────────────────────────────────────────
    try:
        from kaiwu.memory import inject_memory_context
        memory_ctx = inject_memory_context(task, project_name=project_name)
        if memory_ctx:
            user_parts.append(f"\n# 用户记忆\n\n{memory_ctx}")
    except Exception as e:
        logger.debug(f"加载用户记忆失败: {e}")

    user_message = "\n".join(user_parts)

    # ── 调用 LLM ──────────────────────────────────────────────
    try:
        raw = call_llm(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=DEFAULT_MAX_TOKENS,
            temperature=0.3,
            timeout=DEFAULT_TIMEOUT,
            purpose="plan",
        )
        record_call()

        # 解析 JSON —— 容忍 markdown 代码块包裹
        text = raw.strip()
        if text.startswith("```"):
            # 去掉 ```json ... ``` 包裹
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        plan = json.loads(text)

        # 校验必要字段，补齐缺失
        plan.setdefault("steps", [])
        plan.setdefault("trap_warnings", [])
        plan.setdefault("tech_stack", [])
        plan.setdefault("affected_files", [])
        plan.setdefault("confidence", 0.5)
        plan.setdefault("edge_cases", [])
        plan.setdefault("verify", "")
        plan.setdefault("reuse", [])
        plan.setdefault("difficulty_map", [])
        plan["source"] = "llm"

        # ── 提取 anchors/subtasks 存回会话 ─────────────────
        if resolved_session_id:
            try:
                from kaiwu.session import SessionManager, Subtask
                mgr = SessionManager()

                # 存储锚点
                for anchor in plan.get("anchors", []):
                    if isinstance(anchor, str) and anchor.strip():
                        mgr.add_anchor(resolved_session_id, anchor.strip())

                # 存储子任务（首次规划时）
                raw_subtasks = plan.get("subtasks", [])
                if raw_subtasks:
                    subtasks = []
                    for st in raw_subtasks:
                        if isinstance(st, dict) and "seq" in st and "title" in st:
                            subtasks.append(Subtask(
                                seq=st["seq"],
                                title=st["title"],
                                depends_on=st.get("depends_on", []),
                            ))
                    if subtasks:
                        mgr.set_subtasks(resolved_session_id, subtasks)
            except Exception as e:
                logger.debug(f"回写会话数据失败: {e}")

        plan["session_id"] = resolved_session_id

        logger.info(
            f"规划完成: {len(plan['steps'])} 步, "
            f"{len(plan['trap_warnings'])} 条警告, "
            f"置信度 {plan['confidence']}"
        )
        return plan

    except json.JSONDecodeError as e:
        logger.warning(f"DeepSeek 返回的 JSON 解析失败: {e}")
        return {**_EMPTY_PLAN, "source": "parse_error"}
    except Exception as e:
        logger.warning(f"规划调用失败: {e}")
        return {**_EMPTY_PLAN, "source": "error"}


def _filter_knowledge_for_task(task_lower: str) -> str:
    """按任务关键词筛选知识库相关段落，避免全量注入

    比 server.py 的 _filter_knowledge 稍宽松（hits>=1），
    因为这里塞给 DeepSeek，它会自行筛选。
    """
    import re

    full = load_all_knowledge()
    if not full:
        return ""

    sections = full.split("\n## ")
    relevant = []
    max_chars = 3000  # DeepSeek 端可以多给点

    task_tokens = extract_task_tokens(task_lower)

    for section in sections:
        if not section.strip():
            continue
        section_lower = section.lower()
        hits = sum(1 for t in task_tokens if t in section_lower)
        if hits >= 1:  # DeepSeek 端门槛低一些
            chunk = f"## {section.strip()}"
            if sum(len(p) for p in relevant) + len(chunk) > max_chars:
                break
            relevant.append(chunk)

    return "\n\n".join(relevant) if relevant else ""
