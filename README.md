# kaiwu 开物 — AI Coding 增强引擎

> 本地知识引擎，给你的 AI 编程工具装上记忆。同一个错误不犯第二次。

<img width="1376" height="388" alt="image" src="https://github.com/user-attachments/assets/6a340d12-0b81-45c4-8a60-90166e5fa68c" />

<img width="1272" height="1396" alt="image" src="https://github.com/user-attachments/assets/85174b8a-9f17-47e8-8199-638e0d31ebd3" />

---

## 一句话说清楚

AI 编程工具没有记忆——同一个错误反复犯，同一个坑反复踩，token 烧完任务没完成。

kaiwu 是一个**本地知识引擎**，给你的 AI 工具挂上错误库 + 经验库 + 知识库。87% 的重复错误零 token 毫秒级解决，剩下的可选接入 LLM（DeepSeek / GPT / Claude / Qwen / 本地模型）深度分析。

**不依赖任何 LLM 也能工作。** 不配 API key，本地功能 100% 可用。

---

## 三个核心卖点

### 🔥 错误诊断：0.49ms，零 token

同一个错误只需要被解决一次。kaiwu 内置 **125 条预置错误方案** + 自动积累的错误库，三层匹配：

```
错误发生 → 指纹精确匹配（0.49ms）→ 关键词模糊匹配 → LLM 深度分析（可选）
                ↓                        ↓                    ↓
           秒级返回（0 token）      秒级返回（0 token）    方案自动回写本地
                                                        下次同样错误 → 0 token
```

**实测数据（10 种常见错误，模拟第二次遇到）：**

| 错误类型 | 有 kaiwu | 无 kaiwu | 节省 |
|---------|:---:|:---:|:---:|
| GBK 编码 | 0 tok / 22ms | ~800 tok | -800 |
| 模块缺失 | 0 tok / 15ms | ~800 tok | -800 |
| 连接拒绝 | 0 tok / 18ms | ~800 tok | -800 |
| npm 依赖冲突 | 0 tok / 18ms | ~800 tok | -800 |
| 权限拒绝 | 0 tok / 11ms | ~800 tok | -800 |
| 类型错误 | 0 tok / 14ms | ~800 tok | -800 |
| Key 不存在 | 0 tok / 22ms | ~800 tok | -800 |
| 导入循环 | 0 tok / 17ms | ~800 tok | -800 |
| 端口占用 | 0 tok / 13ms | ~800 tok | -800 |
| JSON 解析 | 0 tok / 16ms | ~800 tok | -800 |
| **合计** | **0 tok** | **~8,000 tok** | **-8,000** |

> 本地命中率：**100%**（已解决过的错误）。日均按 30 次重复错误估算，**月省 ~528,000 tokens**。

### 🧠 越用越聪明：自增强飞轮

每次任务完成，kaiwu 自动提炼经验入库。下次遇到同类任务，历史经验直接注入规划：

```
任务执行 → 轨迹审计（有转折？踩过坑？）→ LLM 提炼方法论 → 存入经验库
                                                                    ↓
下次同类任务 ← 自动注入 ← 经验库 TF-IDF 检索（47ms）← 45+ 条预置经验
```

**实测数据（8 个真实编码任务的知识注入情况）：**

| 任务 | 知识库注入 | 经验注入 | LLM |
|------|:---:|:---:|:---:|
| 部署 FastAPI + nginx + HTTPS | — | ✅ | ✅ |
| 修复 Python 3.12 asyncio 兼容 | python_compat | ✅ | — |
| 解决 npm ERESOLVE 依赖冲突 | deps_pitfalls | — | ✅ |
| 微信支付 JSAPI 签名验证 | china_kb | ✅ | ✅ |
| 用 FastMCP 开发 MCP 工具 | tool_priming | — | — |
| MySQL 主从复制 | — | — | — |
| Django SQLite 迁移 PostgreSQL | — | — | — |
| FastAPI JWT refresh token | — | ✅ | — |

> 知识库注入率：**50%**，经验库注入率：**50%**。裸跑模型拿不到这些上下文，只能靠自己的训练知识猜。

**方法论示例（轨迹审计自动提炼）：**
```
[方法论] 修改已有配置文件时 → 先读取现有内容再增量修改
   推荐: 先读取现有内容，理解结构，再做增量修改
   避免: 直接覆盖写入完整配置
   原因: 直接覆盖容易丢失已有配置项
```

### ⚡ 零侵入，不抢 token

kaiwu 不是另一个 AI，是你现有 AI 工具的**外挂知识库**：

- 不替代主模型推理，只在需要时提供知识
- 强模型（Opus/GPT-4o）自动切换轻量模式，只给知识库不调 LLM
- 弱模型（Haiku/Mini）才启用 LLM 全力辅助
- 连续 2 次同类错误自动检测循环，建议换方向，**避免 token 黑洞**
- 配了 LLM key 时日均消耗约 **¥0.1**（DeepSeek 新用户赠送 500 万 tokens）

**循环检测实测：**
```
第 1 次 UnicodeDecodeError → 正常记录
第 2 次 UnicodeDecodeError → ⚠️ 循环检测触发！
  建议: 统一用 encoding='utf-8'，加 errors='replace'，检查 sys.stdout 编码
  → 无 kaiwu: 模型继续用同样的方法重试，浪费 token
  → 有 kaiwu: 立即建议换方向
```

---

## 实测：端到端对比 — 裸跑 vs kaiwu 增强

5 个真实编码场景，每个场景模拟 3 个典型错误，实际调用 LLM API 完成任务规划 + 错误诊断：

| 场景 | 裸跑 token | kaiwu token | 节省 | 裸跑时间 | kaiwu 时间 |
|------|---:|---:|:---:|---:|---:|
| React 表单 + API 联调 | 2,758 | 1,626 | **41%** | 85.5s | 46.0s |
| 部署 + Nginx 反向代理 | 2,611 | 1,027 | **61%** | 84.4s | 25.5s |
| SQLite 迁移 PostgreSQL | 2,844 | 866 | **70%** | 85.8s | 25.6s |
| 微信小程序支付 | 2,749 | 1,674 | **39%** | 85.7s | 44.1s |
| **合计** | **10,962** | **5,193** | **53%** | **341s** | **141s** |

> - 错误本地命中率：**13/15 (87%)**，命中时 0 token、<20ms 返回
> - 裸跑每个错误都要调 LLM（~20s/次），kaiwu 本地命中的错误毫秒级返回
> - 测试脚本：[tests/benchmark_e2e.py](tests/benchmark_e2e.py)，可自行复现

---

## 10 个高难度任务知识注入对比

我们用 10 个真实高难度编码任务（微信支付、K8s部署、WebSocket协作、分库分表、OAuth2、分布式队列、异步爬虫、gRPC微服务、CI/CD、RAG系统）做了完整对比：

|  | 裸跑 | kaiwu 增强 |
|------|:---:|:---:|
| 知识库注入 | 0 字符 | **135,894 字符** |
| 经验库命中 | 0/10 | **4/10** |
| 场景规范命中 | 0/10 | **9/10** |
| 错误本地命中 | 0/30 | **30/30** |
| 错误诊断 token | ~24,000 | **~0** |
| 循环检测 | 无 | 第 2 次即触发 |
| 陷阱预警 | 无 | LLM 规划注入 |

> 错误本地命中 30/30 的前提：这些错误之前被解决过一次。kaiwu 的核心价值是**同一个错误不犯第二次** — 第一次遇到走 LLM 分析（或手动解决），方案自动回写本地，之后再遇到同类错误 0 token 毫秒级返回。
>
> 测试脚本：[tests/benchmark_hard10.py](tests/benchmark_hard10.py)，可自行复现。

---

## 实测性能

| 功能 | 速度 | Token 消耗 | 实测数据 |
|------|:---:|:---:|------|
| 错误库本地匹配 | **0.49ms** | 0 | 命中率 100%（已解决过的错误） |
| 经验库 TF-IDF 检索 | **47ms** | 0 | 注入率 50%（8 个真实任务） |
| 任务分类器 | **0.09ms** | 0 | 自动判断是否需要 LLM 介入 |
| 场景规范检测 | **0.36ms** | 0 | 匹配率 100%（14/14 场景） |
| 知识库按需注入 | **<1ms** | 0 | 注入率 50%（8 个真实任务） |
| 循环检测 | **<1ms** | 0 | 第 2 次同类错误即触发 |
| 主模型识别 | **<0.1ms** | 0 | 准确率 100%（14/14 模型） |
| 知识库总量 | — | 0 | 60,000+ 字符，112 章节 |
| LLM 规划 | ~2-5s | ~600 | 仅中低端模型触发，可选 |
| LLM 诊断 | ~2-5s | ~400 | 仅本地未命中时触发，可选 |

> 以上数据在 Windows 11 / Python 3.12 环境实测。本地功能全部毫秒级响应，零网络依赖。
>
> **月均节省估算：~528,000 tokens**（按日均 30 次重复错误计算）。

---

## 主模型能力自适应

kaiwu 自动识别你的 AI 工具用的什么模型，调整介入深度：

```
              strong (Opus/GPT-4o)     medium (Sonnet/Qwen)     weak (Haiku/Mini)
              ─────────────────────    ─────────────────────    ─────────────────
规划           知识库 + 经验注入        LLM 规划                  LLM 全力规划
诊断           本地匹配（0 token）      本地 → LLM 三层           本地 → LLM 三层
蒸馏           跳过                    异步蒸馏                  同步蒸馏
轨迹审计       积极学习                正常门控                  正常门控
```

已支持自动识别：Claude Opus/Sonnet/Haiku、GPT-4o/4-turbo/o1/o3/o4-mini、DeepSeek、Qwen、GLM、Gemini、Yi、文心、星火、混元等 30+ 模型。

---

## 安装（3 步，2 分钟）

### 1. 安装

```bash
pip install git+https://github.com/val1813/kaiwu.git
```

### 2. 配置 LLM（可选，不配也能用）

```bash
kaiwu config
```

交互式向导，支持 6 个提供商（OpenAI / Anthropic / DeepSeek / Qwen / GLM / 自定义中转）。

> 不配 LLM key 时，kaiwu 的本地功能（错误库、经验库、知识库、场景规范、循环检测）100% 可用。配了 LLM 后额外获得任务规划和新错误深度分析能力。
>
> 推荐 DeepSeek，性价比最高：[platform.deepseek.com](https://platform.deepseek.com)（新用户赠送 500 万 tokens，日均约 ¥0.1）

### 3. 接入你的 AI 编程工具

```bash
# Claude Code（推荐 Plugin 模式，一键获得斜杠命令 + 自动触发 + MCP 工具）
kaiwu install --plugin

# Cursor / Codex / 其他 MCP 兼容工具
kaiwu install --mcp

# 按平台选择
kaiwu install --mcp --claude-code --codex --cursor
```

验证安装：
```bash
kaiwu doctor
```

---

## 安装后你会得到什么

kaiwu 在后台自动工作，你不需要手动调用任何工具：

- **接到新任务** → 自动注入知识库 + 历史经验 + 场景规范
- **遇到报错** → 自动本地匹配诊断，未命中才调 LLM（如已配置）
- **任务完成** → 自动提炼经验入库，下次同类任务直接受益
- **长对话** → 自动压缩上下文，防止超窗口丢信息
- **连续犯同一个错** → 自动检测循环，建议换方向

**Plugin 模式额外获得：**
- 6 个斜杠命令：`/kaiwu-plan`、`/kaiwu-lessons`、`/kaiwu-record`、`/kaiwu-scene`、`/kaiwu-doctor`、`/kaiwu-stats`
- 3 个自动触发技能：新任务自动规划、报错自动诊断、完成自动记录
- 2 个事件钩子：Bash 出错自动提示、会话结束自动提醒

---

## 预置知识库

开箱即用，不需要任何配置：

| 知识库 | 内容 | 规模 |
|------|------|------|
| 中国开发者知识库 | 镜像源、GFW、支付接口、备案、编码陷阱 | 45,298 字 / 77 章节 |
| Python 兼容性指南 | 版本差异、编码问题、Windows 特有坑 | 6,058 字 / 8 章节 |
| 依赖陷阱集 | npm/pip/cargo 常见依赖冲突和解法 | 5,767 字 / 19 章节 |
| 工具使用指南 | MCP 工具最佳实践 | 3,022 字 / 8 章节 |
| 错误知识库 | 125 条预置错误方案 | 持续自动积累 |
| 经验库 | 45 条预置经验 + 方法论 | 持续自动积累 |
| 编码场景规范 | Web/React/数据库/微信支付等 | 19 个场景 |

---

## 工作流演示

### 1. 接到新任务 → 自动规划

```json
{
  "steps": [
    {"seq": 1, "action": "读取现有路由文件", "reason": "了解现有 API 结构"},
    {"seq": 2, "action": "定义 Pydantic 请求模型", "reason": "类型安全"}
  ],
  "trap_warnings": [
    "CORS 配置放在 app 级中间件，不要在单个路由里硬编码",
    "中文 Windows 注意 encoding='utf-8'"
  ]
}
```

### 2. 遇到报错 → 秒级诊断

```json
{
  "root_cause": "UnicodeEncodeError: 中文 Windows 默认 GBK 编码",
  "fix_suggestion": "添加 sys.stdout.reconfigure(encoding='utf-8', errors='replace')",
  "confidence": 0.95,
  "source": "local_exact"    ← 本地命中，0 token
}
```

### 3. 任务完成 → 自动积累

经验自动入库，轨迹审计提炼方法论，下次同类任务直接受益。

---

## 配置

配置文件：`~/.kaiwu/config.toml`

```toml
[providers.deepseek]
api_key = "sk-your-api-key"
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
```

环境变量（优先于配置文件）：
```bash
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://...
KAIWU_HOME=~/.kaiwu
```

CLI 命令：
```bash
kaiwu install --plugin       # Claude Code Plugin 安装（推荐）
kaiwu install --mcp          # MCP Server 注册（全平台）
kaiwu uninstall              # 卸载
kaiwu config                 # 交互式配置向导
kaiwu doctor [--fix]         # 诊断 [+ 自动修复]
kaiwu stats                  # 查看统计
kaiwu toggle                 # 一键开关
```

---

## 数据存储

所有数据本地存储在 `~/.kaiwu/`：

```
~/.kaiwu/
├── config.toml           # 配置
├── error_kb.json         # 错误知识库（自动积累）
├── experiences.json      # 经验库（自动积累）
├── profile.json          # 用户画像
├── sessions/             # 会话记录
└── kaiwu.log             # 日志
```

> 当前版本所有数据均存储在本地，不上传任何数据到云端。云端同步功能正在开发中，上线后将提供明确的数据使用说明和用户授权流程。

---

## 开发初衷

Opus 成本高，Sonnet 在复杂任务中稳定性不足。同一个错误反复出现，token 消耗殆尽任务仍未完成。

硬拼推理能力走不通，换思路——**给 AI 装上记忆**。把错误库、经验库、场景库挂在主模型旁边，该出手时出手，不该介入时保持安静。可选接入 LLM 做深度分析，但核心价值不依赖任何外部 API。

不抢占 token，不干扰推理，持续积累经验。同一个错误只犯一次。

> 名字取自明代科技巨著《天工开物》—— 开万物之巧，记工匠之智。

---

## 联系方式

- GitHub Issues: https://github.com/val1813/kaiwu/issues
- 邮箱: valhuang@kaiwucl.com

---

## 致谢

本项目在设计上借鉴了以下开源项目和学术成果（仅借鉴架构理念，未复制代码）：

- **SWE-Exp 三层经验库** — 精确匹配 → 模糊匹配 → LLM 分析，经验自动回写
- **[mem0](https://github.com/mem0ai/mem0)** (Apache 2.0) — 经验库四态决策，写入前比对去重
- **[MCP 协议](https://modelcontextprotocol.io/)** (MIT) — Model Context Protocol，工具注册与调用框架

### AI 生成内容声明

以下内容由 Claude (Anthropic) 协助生成，经人工审校后纳入项目：

- `kaiwu/scenes/*.md` — 19 个编码场景规范
- `kaiwu/knowledge/*.md` — 中国开发者知识库、Python 兼容性指南、依赖陷阱集
- `data/error_kb.json` — 预置错误知识库（125 条）
- `data/experience.json` — 预置经验库（43 条）

---

## 许可证

**Apache License 2.0** — 详见 [LICENSE](LICENSE)

### 贡献者协议（CLA）

向本项目提交 Pull Request 时，需签署 [贡献者许可协议（CLA）](CLA.md)。

CLA 核心条款：
- 你保留对贡献内容的全部权利
- 你授予项目维护者在云端服务中使用社区贡献数据的权利

> 个人使用、修改、分发不受 CLA 影响，CLA 仅适用于向本仓库提交贡献的场景。
