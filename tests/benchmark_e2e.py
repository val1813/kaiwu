"""kaiwu 端到端对比 — DeepSeek 裸跑 vs DeepSeek + kaiwu

模拟真实编码场景：给 DeepSeek 一个任务，让它生成代码方案，
然后模拟遇到错误，看它如何诊断和修复。

对比维度：总 token、轮数、诊断速度、是否走弯路
"""
import os, sys, json, time
os.environ['LOGURU_LEVEL'] = 'ERROR'
from loguru import logger
logger.disable('kaiwu')

from kaiwu.llm_client import call_llm
from kaiwu.config import get_config

cfg = get_config()
if not cfg.llm_api_key:
    print("ERROR: No LLM API key configured")
    sys.exit(1)

print("=" * 75)
print("DeepSeek 裸跑 vs DeepSeek + kaiwu — 端到端对比")
print("=" * 75)

# ================================================================
# 测试任务定义
# ================================================================

SCENARIOS = [
    {
        "name": "FastAPI JWT 登录接口",
        "task": "用 FastAPI 实现用户注册和登录接口，密码用 bcrypt 加密，返回 JWT token",
        "simulated_errors": [
            "ModuleNotFoundError: No module named 'passlib'",
            "ValueError: Invalid salt",
            "jwt.exceptions.DecodeError: Not enough segments",
        ],
    },
    {
        "name": "React 表单 + API 联调",
        "task": "用 React + TypeScript 实现用户注册表单，前端校验 + 调用后端 API，处理 CORS 和错误提示",
        "simulated_errors": [
            "Access to XMLHttpRequest has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header",
            "TypeError: Cannot read properties of undefined (reading 'map')",
            "Unhandled Runtime Error: Objects are not valid as a React child",
        ],
    },
    {
        "name": "部署 + Nginx 反向代理",
        "task": "将 FastAPI 应用部署到 Linux 服务器，配置 Nginx 反向代理和 HTTPS，用 systemd 管理进程",
        "simulated_errors": [
            "nginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)",
            "502 Bad Gateway - upstream prematurely closed connection",
            "certbot: Error: Could not bind TCP port 80 because it is already in use",
        ],
    },
    {
        "name": "SQLite 迁移 PostgreSQL",
        "task": "将 Django 项目从 SQLite 迁移到 PostgreSQL，处理数据迁移、连接池配置和编码问题",
        "simulated_errors": [
            "django.db.utils.OperationalError: could not connect to server: Connection refused",
            "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0",
            "psycopg2.errors.UndefinedTable: relation 'auth_user' does not exist",
        ],
    },
    {
        "name": "微信小程序支付",
        "task": "实现微信小程序支付功能，包括统一下单、支付回调验签、订单状态查询",
        "simulated_errors": [
            "requests.exceptions.SSLError: HTTPSConnectionPool: Max retries exceeded (Caused by SSLError)",
            "xml.etree.ElementTree.ParseError: not well-formed (invalid token)",
            "WechatPayError: SIGNERROR - 签名错误，请检查后再试",
        ],
    },
]


def run_bare(task, errors):
    """裸跑：DeepSeek 只有自己的知识"""
    total_tokens = {"prompt": 0, "completion": 0}
    turns = 0
    results = []

    # Turn 1: 任务规划
    turns += 1
    start = time.perf_counter()
    try:
        resp = call_llm(
            messages=[
                {"role": "system", "content": "你是一个编程助手，帮用户完成编码任务。给出具体的实现步骤和关键代码。"},
                {"role": "user", "content": f"任务：{task}\n\n请给出实现步骤和关键代码。"},
            ],
            max_tokens=800,
            temperature=0.3,
            purpose="benchmark_bare_plan",
        )
        plan_time = time.perf_counter() - start
        # 估算 token（实际 token 在 record_usage 里记录了，这里用字符估算）
        prompt_tok = len(task) // 3 + 50
        completion_tok = len(resp) // 3
        total_tokens["prompt"] += prompt_tok
        total_tokens["completion"] += completion_tok
        results.append({"turn": turns, "type": "plan", "time": plan_time, "tokens": prompt_tok + completion_tok})
    except Exception as e:
        results.append({"turn": turns, "type": "plan", "error": str(e)})
        return {"turns": turns, "tokens": total_tokens, "results": results, "success": False}

    # Turn 2-N: 遇到错误，裸跑诊断
    for err in errors:
        turns += 1
        start = time.perf_counter()
        try:
            resp = call_llm(
                messages=[
                    {"role": "system", "content": "你是一个编程助手。用户遇到了错误，请诊断原因并给出修复方案。"},
                    {"role": "user", "content": f"执行时遇到错误：\n```\n{err}\n```\n请诊断原因并给出修复代码。"},
                ],
                max_tokens=600,
                temperature=0.3,
                purpose="benchmark_bare_fix",
            )
            fix_time = time.perf_counter() - start
            prompt_tok = len(err) // 3 + 50
            completion_tok = len(resp) // 3
            total_tokens["prompt"] += prompt_tok
            total_tokens["completion"] += completion_tok
            results.append({"turn": turns, "type": "fix", "time": fix_time, "tokens": prompt_tok + completion_tok})
        except Exception as e:
            results.append({"turn": turns, "type": "fix", "error": str(e)})

    return {"turns": turns, "tokens": total_tokens, "results": results, "success": True}


def run_with_kaiwu(task, errors):
    """kaiwu 增强：注入知识库 + 经验 + 场景 + 本地错误匹配"""
    from kaiwu.task_classifier import classify_task, should_inject_knowledge
    from kaiwu.scene import detect_scenes_multi
    from kaiwu.storage import get_experience_store, get_error_kb
    from kaiwu.storage.error_kb import _fingerprint
    from kaiwu.knowledge.loader import load_knowledge

    total_tokens = {"prompt": 0, "completion": 0}
    turns = 0
    results = []
    local_hits = 0

    exp_store = get_experience_store()
    error_kb = get_error_kb()
    kb_names = ['china_kb', 'python_compat', 'deps_pitfalls', 'tool_priming']

    # ── kaiwu 预处理：收集注入内容 ──
    verdict = classify_task(task)
    injected_kbs = [kb for kb in kb_names if should_inject_knowledge(task, kb)]
    scenes = detect_scenes_multi(task)
    exp_ctx = exp_store.inject_into_context(task, limit=3)

    extra_context = ""
    if injected_kbs:
        for kb_name in injected_kbs:
            content = load_knowledge(kb_name)
            if content:
                # 只取相关段落，不全量注入
                extra_context += f"\n[知识库-{kb_name}] (已筛选相关段落)\n"
    if scenes:
        extra_context += f"\n[场景规范] 匹配场景: {', '.join(s[0] for s in scenes)}\n"
    if exp_ctx:
        extra_context += f"\n[历史经验]\n{exp_ctx[:500]}\n"

    # Turn 1: 任务规划（带 kaiwu 注入）
    turns += 1
    start = time.perf_counter()
    try:
        user_msg = f"任务：{task}\n\n请给出实现步骤和关键代码。"
        if extra_context:
            user_msg += f"\n\n--- 以下为辅助参考信息 ---\n{extra_context}"

        resp = call_llm(
            messages=[
                {"role": "system", "content": "你是一个编程助手，帮用户完成编码任务。给出具体的实现步骤和关键代码。"},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=800,
            temperature=0.3,
            purpose="benchmark_kaiwu_plan",
        )
        plan_time = time.perf_counter() - start
        prompt_tok = len(user_msg) // 3 + 50
        completion_tok = len(resp) // 3
        total_tokens["prompt"] += prompt_tok
        total_tokens["completion"] += completion_tok
        results.append({
            "turn": turns, "type": "plan", "time": plan_time,
            "tokens": prompt_tok + completion_tok,
            "kaiwu_inject": bool(extra_context),
        })
    except Exception as e:
        results.append({"turn": turns, "type": "plan", "error": str(e)})
        return {"turns": turns, "tokens": total_tokens, "results": results, "success": False, "local_hits": 0}

    # Turn 2-N: 遇到错误，先走 kaiwu 本地匹配
    for err in errors:
        turns += 1

        # kaiwu 本地匹配
        start = time.perf_counter()
        local_result = error_kb.find_solution(err)
        local_time = (time.perf_counter() - start) * 1000

        if local_result and local_result.get("solution"):
            # 本地命中，0 token
            local_hits += 1
            results.append({
                "turn": turns, "type": "fix_local", "time": local_time / 1000,
                "tokens": 0, "source": "kaiwu_local",
            })
        else:
            # 本地未命中，调 LLM（但带 kaiwu 上下文）
            start = time.perf_counter()
            try:
                resp = call_llm(
                    messages=[
                        {"role": "system", "content": "你是一个编程助手。用户遇到了错误，请诊断原因并给出修复方案。"},
                        {"role": "user", "content": f"执行时遇到错误：\n```\n{err}\n```\n请诊断原因并给出修复代码。"},
                    ],
                    max_tokens=600,
                    temperature=0.3,
                    purpose="benchmark_kaiwu_fix",
                )
                fix_time = time.perf_counter() - start
                prompt_tok = len(err) // 3 + 50
                completion_tok = len(resp) // 3
                total_tokens["prompt"] += prompt_tok
                total_tokens["completion"] += completion_tok
                results.append({"turn": turns, "type": "fix_llm", "time": fix_time, "tokens": prompt_tok + completion_tok})

                # 解决后回写到本地库
                fp = _fingerprint(err)
                error_kb.record_error(err)
                error_kb.record_solution(fp, resp[:200])
            except Exception as e:
                results.append({"turn": turns, "type": "fix_llm", "error": str(e)})

    return {
        "turns": turns, "tokens": total_tokens, "results": results,
        "success": True, "local_hits": local_hits,
    }


# ================================================================
# 先预热错误库（模拟已经用了一段时间的 kaiwu）
# ================================================================

print("\n[预热] 模拟已使用 kaiwu 一段时间，预注册常见错误解决方案...")
from kaiwu.storage import get_error_kb
from kaiwu.storage.error_kb import _fingerprint
error_kb = get_error_kb()

preheat_errors = {
    "ModuleNotFoundError: No module named 'passlib'": "pip install passlib[bcrypt]",
    "ValueError: Invalid salt": "确保 bcrypt.gensalt() 生成的 salt 传入 hashpw，不要手动构造",
    "jwt.exceptions.DecodeError: Not enough segments": "检查 token 格式，确保是完整的 header.payload.signature",
    "Access to XMLHttpRequest has been blocked by CORS policy": "FastAPI 添加 CORSMiddleware，配置 allow_origins",
    "TypeError: Cannot read properties of undefined (reading 'map')": "检查 API 返回数据是否为 undefined，添加可选链 ?. 或默认值",
    "nginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)": "sudo lsof -i :80 找到占用进程，kill 或改端口",
    "502 Bad Gateway - upstream prematurely closed connection": "检查 upstream 服务是否启动，proxy_pass 地址和端口是否正确",
    "django.db.utils.OperationalError: could not connect to server: Connection refused": "检查 PostgreSQL 服务是否启动，pg_hba.conf 是否允许连接",
    "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff": "数据可能是 Latin-1 或 GBK 编码，用 chardet 检测后指定正确编码",
    "requests.exceptions.SSLError: HTTPSConnectionPool: Max retries exceeded": "微信支付需要加载商户证书，requests.post(url, cert=(cert_path, key_path))",
    "xml.etree.ElementTree.ParseError: not well-formed": "微信回调可能返回非 XML 内容，先检查 Content-Type 和响应体",
    "WechatPayError: SIGNERROR": "检查签名顺序和 API 密钥，确保参与签名的字段按字典序排列",
}

for err_text, solution in preheat_errors.items():
    fp = _fingerprint(err_text)
    error_kb.record_error(err_text)
    error_kb.record_solution(fp, solution)

print(f"  已预注册 {len(preheat_errors)} 条错误解决方案\n")

# ================================================================
# 运行对比
# ================================================================

all_bare = []
all_kaiwu = []

for i, scenario in enumerate(SCENARIOS):
    name = scenario["name"]
    task = scenario["task"]
    errors = scenario["simulated_errors"]

    print(f"{'='*75}")
    print(f"场景 {i+1}: {name}")
    print(f"  任务: {task[:70]}...")
    print(f"  模拟错误: {len(errors)} 个")
    print(f"{'='*75}")

    # ── 裸跑 ──
    print(f"\n  [裸跑 DeepSeek]")
    bare = run_bare(task, errors)
    bare_total_tok = bare["tokens"]["prompt"] + bare["tokens"]["completion"]
    bare_time = sum(r.get("time", 0) for r in bare["results"])
    print(f"    轮数: {bare['turns']}")
    print(f"    总 token: ~{bare_total_tok}")
    print(f"    总耗时: {bare_time:.1f}s")
    for r in bare["results"]:
        t = r.get("type", "?")
        tok = r.get("tokens", 0)
        tm = r.get("time", 0)
        err = r.get("error", "")
        if err:
            print(f"    Turn {r['turn']}: {t} ERROR {err[:50]}")
        else:
            print(f"    Turn {r['turn']}: {t} {tok} tok {tm:.1f}s")
    all_bare.append({"name": name, "turns": bare["turns"], "tokens": bare_total_tok, "time": bare_time})

    # ── kaiwu 增强 ──
    print(f"\n  [DeepSeek + kaiwu]")
    kaiwu = run_with_kaiwu(task, errors)
    kaiwu_total_tok = kaiwu["tokens"]["prompt"] + kaiwu["tokens"]["completion"]
    kaiwu_time = sum(r.get("time", 0) for r in kaiwu["results"])
    kaiwu_local = kaiwu.get("local_hits", 0)
    print(f"    轮数: {kaiwu['turns']} (其中 {kaiwu_local} 轮本地命中)")
    print(f"    总 token: ~{kaiwu_total_tok}")
    print(f"    总耗时: {kaiwu_time:.1f}s")
    for r in kaiwu["results"]:
        t = r.get("type", "?")
        tok = r.get("tokens", 0)
        tm = r.get("time", 0)
        src = r.get("source", "")
        err = r.get("error", "")
        if err:
            print(f"    Turn {r['turn']}: {t} ERROR {err[:50]}")
        elif src:
            print(f"    Turn {r['turn']}: {t} {tok} tok {tm*1000:.0f}ms [{src}]")
        else:
            print(f"    Turn {r['turn']}: {t} {tok} tok {tm:.1f}s")

    saved_tok = bare_total_tok - kaiwu_total_tok
    saved_time = bare_time - kaiwu_time
    print(f"\n  [对比] token 节省: {saved_tok} ({saved_tok/max(bare_total_tok,1)*100:.0f}%), 时间节省: {saved_time:.1f}s")
    all_kaiwu.append({"name": name, "turns": kaiwu["turns"], "tokens": kaiwu_total_tok, "time": kaiwu_time, "local_hits": kaiwu_local})
    print()

# ================================================================
# 汇总
# ================================================================

print("=" * 75)
print("5 个场景端到端汇总")
print("=" * 75)

total_bare_tok = sum(b["tokens"] for b in all_bare)
total_bare_time = sum(b["time"] for b in all_bare)
total_bare_turns = sum(b["turns"] for b in all_bare)

total_kaiwu_tok = sum(k["tokens"] for k in all_kaiwu)
total_kaiwu_time = sum(k["time"] for k in all_kaiwu)
total_kaiwu_turns = sum(k["turns"] for k in all_kaiwu)
total_local_hits = sum(k["local_hits"] for k in all_kaiwu)

print(f"""
  {'场景':25s} | {'裸跑 token':>10s} | {'kaiwu token':>11s} | {'节省':>6s} | {'裸跑时间':>8s} | {'kaiwu时间':>9s}
  {'-'*25}-+-{'-'*10}-+-{'-'*11}-+-{'-'*6}-+-{'-'*8}-+-{'-'*9}""")

for b, k in zip(all_bare, all_kaiwu):
    saved = b["tokens"] - k["tokens"]
    pct = saved / max(b["tokens"], 1) * 100
    print(f"  {b['name']:25s} | {b['tokens']:>10} | {k['tokens']:>11} | {pct:>5.0f}% | {b['time']:>7.1f}s | {k['time']:>8.1f}s")

saved_total = total_bare_tok - total_kaiwu_tok
saved_pct = saved_total / max(total_bare_tok, 1) * 100

print(f"  {'-'*25}-+-{'-'*10}-+-{'-'*11}-+-{'-'*6}-+-{'-'*8}-+-{'-'*9}")
print(f"  {'合计':25s} | {total_bare_tok:>10} | {total_kaiwu_tok:>11} | {saved_pct:>5.0f}% | {total_bare_time:>7.1f}s | {total_kaiwu_time:>8.1f}s")

print(f"""
  裸跑 DeepSeek:
    总轮数: {total_bare_turns}, 总 token: ~{total_bare_tok}, 总耗时: {total_bare_time:.1f}s
    每个错误都要调 LLM 分析

  DeepSeek + kaiwu:
    总轮数: {total_kaiwu_turns} (其中 {total_local_hits} 轮本地命中, 0 token)
    总 token: ~{total_kaiwu_tok}, 总耗时: {total_kaiwu_time:.1f}s
    本地命中的错误: {total_local_hits}/{total_kaiwu_turns - len(SCENARIOS)} ({total_local_hits/max(total_kaiwu_turns - len(SCENARIOS), 1)*100:.0f}%)

  节省:
    Token: ~{saved_total} ({saved_pct:.0f}%)
    时间: {total_bare_time - total_kaiwu_time:.1f}s
""")
