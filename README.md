# kaiwu 开物 — AI Coding 增强引擎

> 内嵌 DeepSeek，为 Claude Code / Cursor / Codex 等主流 AI 编程工具提供规划、诊断、经验学习能力。

<img width="1376" height="388" alt="image" src="https://github.com/user-attachments/assets/6a340d12-0b81-45c4-8a60-90166e5fa68c" />

<img width="1272" height="1396" alt="image" src="https://github.com/user-attachments/assets/85174b8a-9f17-47e8-8199-638e0d31ebd3" />

---

## 为什么需要 kaiwu？

Claude Code 的 Opus 成本较高，Sonnet/Haiku 便宜但在复杂任务中错误率偏高——同一个错误反复犯，重复错误消耗大量 token 却无法完成任务。

kaiwu 的解决思路：**给主模型配一个 DeepSeek 参谋**。

- DeepSeek 不做司令，只做顾问——主模型需要时才介入，不抢 token
- 本地错误库 + 经验库兜底，90% 的重复问题零 token 秒解
- 越用越聪明，每次解决的错误和完成的任务都自动入库

**结果：Sonnet 级模型 + kaiwu 在中等复杂度任务上的完成质量，接近甚至追平裸跑 Opus。**

---

## 系统架构

### 智能增强飞轮

kaiwu 的核心不是单次调用，而是一个**自增强的闭环飞轮**——每一次任务执行都在为下一次积累智慧：

```
                    ┌─────────────────────────────────────────┐
                    │           kaiwu 智能增强飞轮             │
                    └─────────────────────────────────────────┘

        ┌──────────┐     规划注入      ┌──────────────┐
        │          │ ◄──────────────── │              │
        │  主 AI   │     经验 + 方法论  │  知识引擎     │
        │  模型    │ ◄──────────────── │  (DeepSeek)  │
        │          │                   │              │
        └────┬─────┘                   └──────▲───────┘
             │                                │
             │ 执行任务                        │ 审计提炼
             ▼                                │
        ┌──────────┐                   ┌──────┴───────┐
        │          │    轨迹上报        │              │
        │  执行    │ ─────────────────► │  轨迹审计    │
        │  过程    │                   │  引擎        │
        │          │                   │              │
        └────┬─────┘                   └──────────────┘
             │                                ▲
             │ 结果 + 错误                     │ 方法论模式
             ▼                                │
        ┌──────────┐    四态去重写入     ┌──────┴───────┐
        │  经验库   │ ◄──────────────── │  经验蒸馏    │
        │  错误库   │                   │  (DeepSeek)  │
        │  方法论库 │ ──────────────────►│              │
        └──────────┘    下次任务注入     └──────────────┘
```

**飞轮转动逻辑：**

```
任务开始 ──► 注入历史经验 + 方法论 ──► 主 AI 执行 ──► 记录结果
                                                         │
    ┌────────────────────────────────────────────────────┘
    │
    ▼
 轨迹审计（有转折？有挣扎？）
    │
    ├─ 有故事 ──► DeepSeek 提炼方法论 ──► 存入方法论库
    │                                         │
    └─ 太简单 ──► 跳过（省 token）             │
                                              ▼
                                    下次同类任务自动注入
                                    "在X情境下，做Y比做Z好"
```

### 三层错误诊断 + 自愈闭环

```
错误发生
  │
  ├─ Layer 1: 指纹精确匹配 ─── 命中 ──► 秒级返回方案（0 token）
  │                              │
  │                              └── 未命中 ▼
  │
  ├─ Layer 2: 关键词模糊匹配 ── 命中 ──► 返回相似方案（0 token）
  │                              │
  │                              └── 未命中 ▼
  │
  └─ Layer 3: DeepSeek 深度分析 ────────► 返回方案（消耗 token）
                                              │
                                              ▼
                                    方案自动回写 Layer 1
                                    下次相同错误 → 0 token 秒解
```

### 经验库四态决策

每条新经验写入前，先与已有经验比对，避免膨胀：

```
新经验进入
    │
    ├─ 关键词重叠 > 80% ──► NONE（丢弃，已有足够相似的）
    │
    └─ 不确定 ──► DeepSeek 判断
                    │
                    ├─ ADD    ── 全新知识点，直接写入
                    ├─ UPDATE ── 同场景更详细，合并到已有条目
                    ├─ DELETE ── 与已有矛盾，废弃旧条目
                    └─ NONE   ── 高度相似，无增量价值
```

### 轨迹审计管线（v0.2.2 新增）

不是所有任务都值得审计——只审计**有故事的轨迹**：

```
任务完成，主 AI 上报执行轨迹
    │
    ▼
 审计门控 _should_audit()
    │
    ├─ trace < 3 步 ──────────────► 跳过（太短，没什么可学的）
    │
    │  ┌─ strong 模型（积极学习：最佳实践 + 犯错教训）─────────┐
    │  │                                                      │
    │  ├─ 任务失败 ───────────────► ✅ 审计（高价值犯错模式）   │
    │  ├─ 有失败步骤（≥1）────────► ✅ 审计（踩过的坑要记录）   │
    │  ├─ 标记了 pivot ──────────► ✅ 审计（换方向说明有问题）   │
    │  ├─ 成功 + 轮数 ≥ 5 ───────► ✅ 审计（完整路线是教科书）  │
    │  └─ 短任务全部成功 ─────────► 跳过                       │
    │                                                          │
    │  ┌─ medium / weak 模型 ─────────────────────────────────┐
    │  │                                                      │
    │  ├─ 失败 + 轮数 ≥ 5 ───────► ✅ 审计（分析哪里走错了）   │
    │  ├─ 成功但 ≥ 2 步失败 ─────► ✅ 审计（有转折点）          │
    │  ├─ 标记了 pivot ──────────► ✅ 审计（明确换了方向）       │
    │  ├─ 成功 + 轮数 ≥ 6 ───────► ✅ 审计（长任务可能有经验）  │
    │  └─ 其他 ──────────────────► 跳过                       │
    │
    ▼
 DeepSeek 分析轨迹，提取两类模式：
    │
    ├─ best_practice: 强模型的高效路线，值得学习
    └─ pitfall: 任何模型踩过的坑，后续应避免
                    │
                    ▼
              ┌─────────────────────┐
              │ situation: 触发条件   │
              │ good_approach: 推荐   │
              │ bad_approach: 避免    │
              │ reason: 原因          │
              └─────────────────────┘
                    │
                    ▼
              存入经验库 [方法论] 标签
              下次同类任务自动注入
```

**审计产出示例：**

```
[方法论] 需要修改已有配置文件时→先读取现有内容再增量修改
   推荐: 先读取现有内容，理解结构，再做增量修改
   避免: 直接覆盖写入完整配置
   原因: 直接覆盖容易丢失已有配置项
```

### 主模型能力自适应

kaiwu 根据主模型能力等级自动调整介入深度：

```
                strong (Opus/GPT-4o)     medium (Sonnet/Qwen)     weak (Haiku/Mini)
                ─────────────────────    ─────────────────────    ─────────────────
规划             知识库 + 经验注入        DeepSeek 规划             DeepSeek 全力规划
诊断             本地匹配（0 token）      本地 → DeepSeek 三层      本地 → DeepSeek 三层
蒸馏             跳过                    异步蒸馏                  同步蒸馏
轨迹审计         积极学习（最佳实践+坑）  正常门控                  正常门控
方法论注入       注入                    注入                      注入
```

---

## 核心能力

| 能力 | 说明 | 消耗 token |
|------|------|:---:|
| **智能规划** | DeepSeek 为任务生成步骤规划 + 陷阱警告 | 少量 |
| **三层错误诊断** | 本地精确匹配 → 本地模糊匹配 → DeepSeek 分析 | 前两层 0 |
| **经验学习** | 每次任务自动提炼经验，下次同类任务直接注入 | 少量 |
| **轨迹审计** | 分析执行过程中的转折点，提炼可复用方法论 | ~800/次 |
| **上下文压缩** | 长对话自动压缩，防止超窗口丢信息 | 少量 |
| **场景规范** | 19 个编码场景（Web/React/数据库/微信支付等）的最佳实践 | 0 |
| **用户画像** | 学习你的编码习惯，预判下一步 | 0 |
| **能力自适应** | 根据主模型等级（strong/medium/weak）自动调整介入深度 | 0 |

---

## 安装（3 步搞定）

### 1. 安装 kaiwu

```bash
pip install git+https://github.com/val1813/kaiwu.git
```

或克隆安装：

```bash
git clone https://github.com/val1813/kaiwu.git
cd kaiwu
pip install .
```

### 2. 配置 DeepSeek API Key

```bash
kaiwu config
```

交互式向导会引导你完成配置。支持 5 个预设提供商（OpenAI / Anthropic / DeepSeek / Qwen / GLM），选择后只需输入 API Key，URL 和模型名回车使用默认值。

DeepSeek API Key 免费注册：[platform.deepseek.com](https://platform.deepseek.com)（新用户赠送 500 万 tokens，日常使用约 ¥0.1/天）。

### 3. 接入编程工具

**Claude Code 用户（推荐 Plugin 模式）：**

```bash
kaiwu install --plugin
```

安装后重启 Claude Code，获得 6 个斜杠命令 + 3 个自动触发技能 + MCP 工具，完整体验。

**Cursor / Codex / 其他 MCP 兼容工具：**

```bash
# 全平台注册（Claude Code + Cursor + Codex）
kaiwu install --mcp

# 只注册单个平台
kaiwu install --mcp --claude-code
kaiwu install --mcp --codex
kaiwu install --mcp --cursor

# 组合注册
kaiwu install --mcp --claude-code --codex
```

自动注册 MCP Server 到指定平台的配置文件，重启工具后生效。

**卸载：**

```bash
# 全部卸载
kaiwu uninstall

# 按平台卸载
kaiwu uninstall --claude-code
kaiwu uninstall --codex
kaiwu uninstall --cursor
```

---

## 安装后你会得到什么

### 6 个斜杠命令

| 命令 | 作用 |
|------|------|
| `/kaiwu-plan` | 获取 DeepSeek 任务规划 |
| `/kaiwu-lessons` | 诊断错误，获取解决方案 |
| `/kaiwu-record` | 记录任务经验到知识库 |
| `/kaiwu-scene` | 获取场景编码规范 |
| `/kaiwu-doctor` | 诊断插件连接状态 |
| `/kaiwu-stats` | 查看经验库/错误库统计 |

### 3 个自动触发技能

- **kaiwu-workflow** — 新任务时自动引导调用规划
- **kaiwu-diagnosis** — 检测到错误时自动提示诊断
- **kaiwu-experience** — 任务完成时自动提示记录经验

### 2 个事件钩子

- **PostToolUse** — Bash 执行出错时，自动提示调用 kaiwu_lessons
- **Stop** — 会话结束前，自动提示记录经验

### 7 个 MCP 工具

插件内嵌 MCP Server，自动注册，无需手动配置：

| 工具 | 作用 |
|------|------|
| `kaiwu_context` | 初始化项目上下文，创建 Session |
| `kaiwu_plan` | 生成结构化任务规划 |
| `kaiwu_lessons` | 三层错误诊断 |
| `kaiwu_record` | 记录成功/失败经验 + 轨迹审计 |
| `kaiwu_condense` | 上下文压缩 |
| `kaiwu_scene` | 场景规范检测 |
| `kaiwu_profile` | 用户习惯画像 |

---

## 验证安装

```bash
# 检查插件和 MCP 连接是否正常
kaiwu doctor

# 有问题自动修复
kaiwu doctor --fix
```

或在 Claude Code 中直接输入 `/kaiwu-doctor`。

---

## 使用演示

### 接到新任务

Claude Code 自动调用 `kaiwu_plan`，DeepSeek 返回规划：

```json
{
  "steps": [
    {"seq": 1, "action": "读取现有路由文件", "reason": "了解现有 API 结构"},
    {"seq": 2, "action": "定义 Pydantic 请求模型", "reason": "类型安全"}
  ],
  "trap_warnings": [
    "CORS 配置放在 app 级中间件，不要在单个路由里硬编码",
    "中文 Windows 注意 encoding='utf-8'"
  ],
  "confidence": 0.85
}
```

### 遇到报错

自动检测错误，调用 `kaiwu_lessons` 秒级诊断：

```json
{
  "root_cause": "UnicodeEncodeError: 中文 Windows 默认 GBK 编码",
  "fix_suggestion": "添加 sys.stdout.reconfigure(encoding='utf-8', errors='replace')",
  "confidence": 0.95,
  "source": "local_exact"
}
```

### 任务完成

自动提示记录经验。如果执行过程有转折（方案A失败→切换方案B成功），轨迹审计自动提炼方法论：

```
[方法论] 需要修改已有配置文件时→先读取现有内容再增量修改
   推荐: 先读取现有内容，理解结构，再做增量修改
   避免: 直接覆盖写入完整配置
   原因: 直接覆盖容易丢失已有配置项
```

下次遇到类似任务，这条方法论会自动注入到规划中。

---

## 配置

配置文件位于 `~/.kaiwu/config.toml`：

```toml
[providers.deepseek]
api_key = "sk-your-api-key"
base_url = "https://api.deepseek.com/v1"  # 可改为中转地址
model = "deepseek-chat"
```

### 环境变量

```bash
DEEPSEEK_API_KEY=sk-xxx        # 优先于 config.toml
DEEPSEEK_BASE_URL=https://...  # 优先于 config.toml
KAIWU_HOME=~/.kaiwu            # 数据目录（默认）
```

### CLI 命令一览

```bash
kaiwu install --plugin       # Claude Code Plugin 安装（推荐）
kaiwu install --mcp          # MCP Server 注册（全平台）
kaiwu install --mcp --claude-code  # 只注册 Claude Code
kaiwu install --mcp --codex  # 只注册 Codex
kaiwu install --mcp --cursor # 只注册 Cursor
kaiwu uninstall              # 全部卸载
kaiwu uninstall --claude-code  # 按平台卸载
kaiwu config                 # 交互式配置向导
kaiwu doctor                 # 诊断连接状态
kaiwu doctor --fix           # 诊断并自动修复
kaiwu launch                 # 验证 + 启动 Claude Code
kaiwu stats                  # 查看经验库/错误库统计
kaiwu toggle                 # 一键开关（对比开/关效果）
```

---

## 数据存储

所有数据本地存储在 `~/.kaiwu/`：

```
~/.kaiwu/
├── config.toml           # 配置
├── error_kb.json         # 错误知识库
├── experiences.json      # 经验库（含方法论模式）
├── profile.json          # 用户画像
├── sessions/             # 会话记录
└── kaiwu.log             # 日志
```

> 当前版本所有数据均存储在本地，不上传任何数据到云端。云端同步功能正在开发中，上线后将提供明确的数据使用说明和用户授权流程。

---

## 开发初衷

Opus 成本高，Sonnet 在复杂任务中稳定性不足。同一个错误反复出现，token 消耗殆尽任务仍未完成。

硬拼推理能力走不通，换思路——**DeepSeek 做顾问，不做司令**。把错误库、经验库、场景库挂在主模型旁边，DeepSeek 负责调度这些知识，该出手时出手，不该介入时保持安静。

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
