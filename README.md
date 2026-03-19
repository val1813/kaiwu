# kaiwu 开物 — Claude Code 增强插件

> 内嵌 DeepSeek，让低价模型在部分任务追平最强模型。

<img width="1376" height="388" alt="image" src="https://github.com/user-attachments/assets/6a340d12-0b81-45c4-8a60-90166e5fa68c" />

<img width="1272" height="1396" alt="image" src="https://github.com/user-attachments/assets/85174b8a-9f17-47e8-8199-638e0d31ebd3" />

---

## 为什么需要 kaiwu？

Claude Code 的 Opus 太贵，Sonnet/Haiku 便宜但容易翻车——同一个错误反复犯，改来改去 token 烧完任务还没解决。

kaiwu 的解决思路：**给主模型配一个 DeepSeek 参谋**。

- DeepSeek 不做司令，只做顾问——主模型需要时才介入，不抢 token
- 本地错误库 + 经验库兜底，90% 的重复问题零 token 秒解
- 越用越聪明，每次解决的错误和完成的任务都自动入库

**结果：Sonnet 级模型 + kaiwu 在中等复杂度任务上的完成质量，接近甚至追平裸跑 Opus。**

---

## 核心能力

| 能力 | 说明 | 消耗 token |
|------|------|:---:|
| **智能规划** | DeepSeek 为任务生成步骤规划 + 陷阱警告 | 少量 |
| **三层错误诊断** | 本地精确匹配 → 本地模糊匹配 → DeepSeek 分析 | 前两层 0 |
| **经验学习** | 每次任务自动提炼经验，下次同类任务直接注入 | 少量 |
| **上下文压缩** | 长对话自动压缩，防止超窗口丢信息 | 少量 |
| **场景规范** | 19 个编码场景（Web/React/数据库/微信支付等）的最佳实践 | 0 |
| **用户画像** | 学习你的编码习惯，预判下一步 | 0 |

### 三层错误诊断

```
错误发生
  ├─ Layer 1: 指纹精确匹配（毫秒级，0 token）
  ├─ Layer 2: 关键词模糊匹配（毫秒级，0 token）
  └─ Layer 3: DeepSeek 深度分析（消耗 token，方案自动回写）
       → 下次相同错误直接命中 Layer 1
```

### 越用越智能

- 每次成功任务 → DeepSeek 提炼经验入库
- 每次新错误被解决 → 解决方案自动存入报错库
- 相似任务 → 命中历史经验，注入 few-shot 提高成功率
- 同一个坑只踩一次

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

交互式向导会引导你完成配置。DeepSeek API Key 免费注册：[platform.deepseek.com](https://platform.deepseek.com)（新用户赠送 500 万 tokens，日常使用约 ¥0.1/天）。

### 3. 接入编程工具

**Claude Code 用户（推荐 Plugin 模式）：**

```bash
kaiwu install --plugin
```

安装后重启 Claude Code，获得 6 个斜杠命令 + 3 个自动触发技能 + MCP 工具，完整体验。

**Cursor / Codex / 其他 MCP 兼容工具：**

```bash
kaiwu install --mcp
```

自动注册 MCP Server 到 Claude Code、Cursor 等平台的配置文件，重启工具后生效。

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
| `kaiwu_record` | 记录成功/失败经验 |
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

自动提示记录经验，下次类似任务直接受益。

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
kaiwu install --mcp          # MCP Server 注册（通用，兼容多平台）
kaiwu config                 # 交互式配置向导
kaiwu doctor                 # 诊断连接状态
kaiwu doctor --fix           # 诊断并自动修复
kaiwu launch                 # 验证 + 启动 Claude Code
kaiwu stats                  # 查看经验库/错误库统计
kaiwu toggle                 # 一键开关（对比开/关效果）
```

---

## 数据存储

所有数据本地存储在 `~/.kaiwu/`，不上传任何数据到云端：

```
~/.kaiwu/
├── config.toml           # 配置
├── error_kb.json         # 错误知识库
├── experiences.json      # 经验库
├── profile.json          # 用户画像
├── sessions/             # 会话记录
└── kaiwu.log             # 日志
```

---

## 开发初衷

Opus 太贵，Sonnet 老翻车。同一个错误改五遍，token 烧完任务还是半成品。

硬拼推理能力走不通，换思路——**DeepSeek 做顾问，不做司令**。把错误库、经验库、场景库挂在主模型旁边，DeepSeek 负责调度这些知识，该出手时出手，不该出现时闭嘴。

不抢 token，不降智，越用越聪明。同一个坑只踩一次。

> 名字取自明代科技巨著《天工开物》—— 开万物之巧，记工匠之智。

---

## 联系方式

- QQ: 154882199
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
