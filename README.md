# kaiwu 开物 — AI Coding 增强引擎

> 本地知识引擎，给你的 AI 编程工具装上记忆。同一个错误不犯第二次。

<img width="1376" height="388" alt="image" src="https://github.com/user-attachments/assets/6a340d12-0b81-45c4-8a60-90166e5fa68c" />

<img width="1272" height="1396" alt="image" src="https://github.com/user-attachments/assets/85174b8a-9f17-47e8-8199-638e0d31ebd3" />

---

## 一句话说清楚

AI 编程工具没有记忆——同一个错误反复犯，同一个坑反复踩，token 烧完任务没完成。

kaiwu 是一个**本地知识引擎**，给你的 AI 工具挂上错误库 + 经验库 + 知识库 + 场景库。安装即用，不需要任何 API key。

---

## 开箱即用：本地知识引擎

以下能力全部在本地运行，**零 token、零网络、毫秒级响应**。

### 🔥 错误库 — 同一个错误不犯第二次

内置 **125 条预置错误方案**，每次解决新错误自动入库，越用越强。

```
错误发生 → 指纹精确匹配（0.49ms）→ 关键词模糊匹配 → 返回方案（0 token）
```

实测 10 种常见错误（GBK编码/模块缺失/连接拒绝/npm依赖/权限/类型/Key/导入循环/端口/JSON），第二次遇到时**全部本地命中，11-22ms 返回，0 token**。

> 日均按 30 次重复错误估算，**月省 ~528,000 tokens**。

### 🧠 经验库 — 越用越聪明

45 条预置经验 + 自动积累。每次任务完成经验自动入库，下次同类任务 TF-IDF 检索（47ms）直接注入。

> 实测 8 个真实任务，经验库注入率 **50%**。裸跑模型拿不到这些历史上下文。

### 📚 知识库 — 60,000+ 字符的编码智慧

| 知识库 | 内容 | 规模 |
|------|------|------|
| 中国开发者知识库 | 镜像源、GFW、支付接口、备案、编码陷阱 | 45,298 字 / 77 章节 |
| Python 兼容性指南 | 版本差异、编码问题、Windows 特有坑 | 6,058 字 / 8 章节 |
| 依赖陷阱集 | npm/pip/cargo 常见依赖冲突和解法 | 5,767 字 / 19 章节 |
| 工具使用指南 | MCP 工具最佳实践 | 3,022 字 / 8 章节 |

按任务关键词自动匹配注入，不相关的不注入，不浪费 token。

### 🎯 19 个场景规范

Web / React / Vue / 数据库 / 微信支付 / 部署 / 爬虫 / 数据分析 / Shell 脚本 / 游戏开发 / 代码审查...

> 实测 14 个任务，场景匹配率 **100%**。匹配到场景时自动注入最佳实践和常见陷阱。

### 🔄 循环检测

```
第 1 次 UnicodeDecodeError → 正常记录
第 2 次 UnicodeDecodeError → ⚠️ 循环检测触发！建议换方向
```

> 无 kaiwu：模型继续用同样的方法重试，浪费 token。有 kaiwu：第 2 次就拦住。

### 🤖 主模型自动识别

自动识别 30+ 主流模型（Claude / GPT / DeepSeek / Qwen / GLM / Gemini 等），按能力等级调整介入深度。强模型少干预，弱模型多辅助。

---

## 进阶：接入 LLM 解锁更多能力

以上本地功能不需要任何 API key。如果你配置了 LLM，还能解锁：

| 进阶能力 | 说明 | 消耗 |
|------|------|:---:|
| **新错误深度分析** | 本地未命中的错误，LLM 分析根因，方案自动回写本地库，下次秒解 | ~400 tok/次 |
| **任务规划 + 陷阱预警** | 复杂任务自动生成步骤规划、陷阱警告、边界情况 | ~600 tok/次 |
| **经验蒸馏** | 从执行轨迹中提炼方法论，存入经验库供后续复用 | ~400 tok/次 |
| **轨迹审计** | 分析执行过程中的转折点，提炼"在X情境下做Y比做Z好" | ~800 tok/次 |
| **上下文压缩** | 长对话自动压缩为结构化摘要，防止超窗口丢信息 | ~500 tok/次 |
| **跨会话记忆** | 自动提取持久记忆（技术偏好、项目约定），跨会话复用 | ~300 tok/次 |

支持 6 个提供商：**DeepSeek / OpenAI / Anthropic / Qwen / GLM / 自定义中转**，也可接本地模型（Ollama 等）。

> 推荐 DeepSeek，性价比最高，日均约 ¥0.1。新用户赠送 500 万 tokens：[platform.deepseek.com](https://platform.deepseek.com)

**方法论示例（LLM 轨迹审计自动提炼）：**
```
[方法论] 修改已有配置文件时 → 先读取现有内容再增量修改
   推荐: 先读取现有内容，理解结构，再做增量修改
   避免: 直接覆盖写入完整配置
   原因: 直接覆盖容易丢失已有配置项
```

---

## 实测数据

### 端到端对比：裸跑 vs kaiwu 增强

5 个真实编码场景，每个场景模拟 3 个典型错误：

| 场景 | 裸跑 token | kaiwu token | 节省 | 裸跑时间 | kaiwu 时间 |
|------|---:|---:|:---:|---:|---:|
| React 表单 + API 联调 | 2,758 | 1,626 | **41%** | 85.5s | 46.0s |
| 部署 + Nginx 反向代理 | 2,611 | 1,027 | **61%** | 84.4s | 25.5s |
| SQLite 迁移 PostgreSQL | 2,844 | 866 | **70%** | 85.8s | 25.6s |
| 微信小程序支付 | 2,749 | 1,674 | **39%** | 85.7s | 44.1s |
| **合计** | **10,962** | **5,193** | **53%** | **341s** | **141s** |

> 错误本地命中率 **87%**，命中时 0 token、<20ms。测试脚本：[tests/benchmark_e2e.py](tests/benchmark_e2e.py)

### 10 个高难度任务知识注入对比

微信支付、K8s部署、WebSocket协作、分库分表、OAuth2、分布式队列、异步爬虫、gRPC微服务、CI/CD、RAG系统：

|  | 裸跑 | kaiwu 增强 |
|------|:---:|:---:|
| 知识库注入 | 0 字符 | **135,894 字符** |
| 经验库命中 | 0/10 | **4/10** |
| 场景规范命中 | 0/10 | **9/10** |
| 错误本地命中 | 0/30 | **30/30** |
| 错误诊断 token | ~24,000 | **~0** |
| 循环检测 | 无 | 第 2 次即触发 |

> 测试脚本：[tests/benchmark_hard10.py](tests/benchmark_hard10.py)

### 本地功能性能

| 功能 | 速度 | 实测数据 |
|------|:---:|------|
| 错误库匹配 | **0.49ms** | 命中率 100%（已解决过的错误） |
| 经验库检索 | **47ms** | 注入率 50% |
| 任务分类器 | **0.09ms** | 零 token 决策 |
| 场景检测 | **0.36ms** | 匹配率 100%（14/14） |
| 循环检测 | **<1ms** | 第 2 次即触发 |
| 模型识别 | **<0.1ms** | 准确率 100%（14/14） |

> Windows 11 / Python 3.12 实测。全部毫秒级，零网络依赖。

---

## 安装（2 步）

### 1. 安装

```bash
pip install git+https://github.com/val1813/kaiwu.git
```

### 2. 接入你的 AI 编程工具

```bash
# Claude Code（推荐 Plugin 模式）
kaiwu install --plugin

# Cursor / Codex / 其他 MCP 兼容工具
kaiwu install --mcp

# 按平台选择
kaiwu install --mcp --claude-code --codex --cursor
```

验证：`kaiwu doctor`

**到这里就能用了。** 本地功能（错误库、经验库、知识库、场景规范、循环检测）全部就绪。

### 可选：配置 LLM 解锁进阶能力

```bash
kaiwu config
```

交互式向导引导配置。不配也完全不影响本地功能。

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

硬拼推理能力走不通，换思路——**给 AI 装上记忆**。把错误库、经验库、场景库挂在主模型旁边，该出手时出手，不该介入时保持安静。核心价值不依赖任何外部 API，可选接入 LLM 做深度增强。

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
