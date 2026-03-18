# cl-kaiwu 开物 v0.2

**开发初衷，一个viber的碎碎念：**
claude code 的opus太贵
只能用普通模型，模型老报错，同一个错误老犯，改来改去。

于是我脑洞大开
我要为国请命，打造一个中国人能用的deepseek能跑的底座
于是花费巨资后失败。cl打造各种牛B功能，但一跑成功率不足70%。

---------------------------------------------------------------
我对不起国家和九年义务教育里各位语文老师
------------------------------------------------------------------

这时候我脑洞打开，cl搞不出来，我搞外挂，现有coding软件上挂个数据库，把错误和经验还有想要的挂上去，我不就是“模型同权”
注意，“模型同权”竟然被我一个viber提出来了！！！！！
于是我就试呀，试试发现全是坑，他们不听我调度。我让读错误，让读经验，主AI把我所有包都读了，然后说跟任务无关。
token没了 任务没解决。

这时候偷懒，怎么走捷径~~~~当然用AI呀。

**用AI来调度这些库，我发现我是天才，我又对得起我语文老师了。**
然后我就AI来调度，我研究各种学说，都告诉我一个道理：
想要模型同权，除非你能有无敌推理能力。
靠北~~我一deepseek跟你们比什么推理。
换思路。

deepseek做顾问，不做司令。

我聪明呀。
装了以后，我问过我的主ai，你觉得你在现在这个环境和在claude code什么感觉
他说：我总感觉身边有个声音 ，在指引我，告诉我，电脑前这个人是个老登。。。。。。。

成了！！！！
最后优化下，怎么让deepseek不跟主模型打架。怎么不在不该出现时候出现。
完美~~~

大家尝试

**双引擎的无敌设计！！！！！！请大家看这里**

安装了本MCP 服务后
deepseek统领经验库、错误库还有个自作聪明的中国经验库。给主ai提供参谋。

-----------------------------------------------------------------------------------
这个coding软件外挂个插件，内嵌deepseek 你们想过没
-----------------------------------------------------------------------------------

只有主AI需要的时候，他才会建议，所以不会耗费您的token。
而且也不会让您的贵模型降费。
而且内嵌的deepseek还在总结您的经验和错误，对了还在学习你的行为习惯，预测你下一步命令。

本次发布本地版，不用担心数据会被偷。
后面会发布云端版，收集大家错误，然后共享
（等我的网站ICP和我个体工商户弄出来，到时候收费！！！）
我测过几次数据 大概水平：
  ┌─────────────────┬──────┬────────┬─────────┬───────────┬─────────┬─────────┐
  │    Condition    │ Done │ Pass@1 │ AvgQual │ AvgTokens │ AvgTime │ AvgCost │
  ├─────────────────┼──────┼────────┼─────────┼───────────┼─────────┼─────────┤
  │ A (Haiku)       │ 9    │ 8/9    │ 9.8     │ 120,004   │ 150.3s  │ $0.2027 │
  ├─────────────────┼──────┼────────┼─────────┼───────────┼─────────┼─────────┤
  │ B (Haiku+kaiwu) │ 9    │ 8/9    │ 9.8     │ 43,677    │ 203.8s  │ $0.0665 │
  ├─────────────────┼──────┼────────┼─────────┼───────────┼─────────┼─────────┤
  │ C (Opus)        │ 9    │ 8/9    │ 9.9     │ 60,988    │ 119.3s  │ $0.4724 │
  └─────────────────┴──────┴────────┴─────────┴───────────┴─────────┴─────────┘

 后面会上云端，希望到时大家多共享，到时根据共享给大家算积分，共享成果，数据库拿出来贡献给国家
 迟早有一天 咱们能做到
 
 -----------------------------------------------------------------------------
 模型同权！！！！！！！！！国际共产主义一定会实现!!!!!!!!!!!!!!!!!!!!!!!
 ----------------------------------------------------------------------------


**AI Coding 增强引擎** — 为 Claude Code / Cursor / VS Code Copilot / Codex 等主流 AI 编程工具提供：

- DeepSeek 辅助规划（精准安排编码链路）
- 经验库（成功轨迹积累，越用越智能）
- 报错库（错误模式 + 解决方案，秒级诊断）
- 中国场景库（19 个编码场景规范 + 中国开发者知识库）

> 名字取自明代科技巨著《天工开物》—— 开万物之巧，记工匠之智。

---

## 核心特性

### 7 个 MCP 工具

| 工具 | 作用 | DeepSeek 调用 |
|------|------|:---:|
| `kaiwu_context` | 处理项目上下文，创建/更新 Session | ✗ |
| `kaiwu_plan` | 为编码任务生成结构化规划（步骤 + 陷阱警告） | ✓ |
| `kaiwu_lessons` | 三层错误诊断（本地精确 → 本地模糊 → DeepSeek） | 仅第三层 |
| `kaiwu_record` | 记录成功经验/失败教训，自动提炼 | ✓ |
| `kaiwu_condense` | 会话管理 + 上下文压缩（init/compress/inject/anchor） | ✓ 压缩时 |
| `kaiwu_scene` | 检测任务场景，返回编码规范 | 仅 LLM 兜底 |
| `kaiwu_profile` | 返回用户编程习惯画像 | ✗ |

### 三层错误诊断

```
错误输入
  ├─ Layer 1: ErrorKB 精确匹配（指纹，毫秒级，0 token）
  ├─ Layer 2: ErrorKB 模糊匹配（关键词，毫秒级，0 token）
  └─ Layer 3: DeepSeek 分析（消耗 token，解决方案自动回写）
       → 下次相同错误直接命中 Layer 1，不再调 API
```

### 19 个编码场景

web · react · dataviz · python_script · backend_api · data_analysis · web_scraping · shell_script · copywriting · game_dev · test_case · database · code_review · docx · pdf · pptx · xlsx · china_deploy · wechat_pay

### 越用越智能

- 每次成功任务，DeepSeek 自动提炼经验入库
- 每次遇到新错误，解决方案自动存入报错库
- 相似任务命中历史经验，注入 few-shot 提高成功率

---

## 安装

### 1. 安装包

```bash
pip install git+https://github.com/v289986095-sketch/kaiwu.git
```

或者克隆到本地安装：

```bash
git clone https://github.com/v289986095-sketch/kaiwu.git
cd kaiwu
pip install .
```

### 2. 配置 DeepSeek API Key

```bash
# 交互式配置（推荐，自动探测 API 格式）
kaiwu config

# 或命令行直接设置
kaiwu config set providers.deepseek.api_key sk-your-api-key
```

免费注册：[platform.deepseek.com](https://platform.deepseek.com)（新用户赠送 500 万 tokens）

### 3. 安装到编程工具

```bash
# 安装到所有已检测到的平台
kaiwu install

# 或指定平台
kaiwu install --platform claude-code
kaiwu install --platform cursor
kaiwu install --platform vscode
kaiwu install --platform codex
```

这一步会：
- 生成平台对应的配置文件（CLAUDE.md / .cursor/rules/ / copilot-instructions.md / AGENTS.md）
- 注册 MCP Server 到平台配置

### 4. 启动 MCP Server

```bash
kaiwu serve
# 或
python -m kaiwu
```

---

## 平台支持

| 平台 | 配置文件兜底 | MCP Server 增强 |
|------|:-----------:|:--------------:|
| **Claude Code** | CLAUDE.md | ✓ 原生支持 |
| **Cursor** | .cursor/rules/ | ✓ 支持 MCP |
| **VS Code Copilot** | copilot-instructions.md | ✓ 通过扩展 |
| **OpenAI Codex** | AGENTS.md | 计划中 |

**两层架构：**
1. **配置文件兜底**（零门槛）— 即使不启动 MCP Server，规则也会注入到 AI 上下文
2. **MCP Server 增强**（完整能力）— DeepSeek 实时规划、经验检索、错误诊断

---

## 使用方式

安装后，AI 编程工具会自动发现并使用 kaiwu 的 7 个工具：

### 场景1：接到新任务

AI 工具自动调用 `kaiwu_plan` 获取规划建议：
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

### 场景2：遇到报错

AI 工具调用 `kaiwu_lessons` 获取诊断：
```json
{
  "root_cause": "UnicodeEncodeError: 中文 Windows 默认 GBK 编码",
  "fix_suggestion": "添加 sys.stdout.reconfigure(encoding='utf-8', errors='replace')",
  "confidence": 0.95,
  "source": "local_exact"
}
```

### 场景3：任务完成

AI 工具调用 `kaiwu_record` 记录经验，下次类似任务直接受益。

---

## 配置

配置文件位于 `~/.kaiwu/config.toml`：

```toml
[providers.deepseek]
api_key = "sk-your-api-key"
base_url = "https://api.deepseek.com/v1"  # 可改为中转地址
model = "deepseek-chat"
api_format = "openai"
```

### 环境变量

```bash
DEEPSEEK_API_KEY=sk-xxx     # 优先于 config.toml
DEEPSEEK_BASE_URL=https://... # 优先于 config.toml
KAIWU_HOME=~/.kaiwu          # 数据目录
```

### CLI 命令

```bash
kaiwu serve                  # 启动 MCP Server
kaiwu config                 # 交互式配置向导
kaiwu install                # 安装到编程工具
kaiwu toggle                 # 一键开关（对比开/关效果）
kaiwu stats                  # 查看经验库/错误库统计

kaiwu data show              # 查看本地数据概览
kaiwu data delete            # 删除所有本地数据
kaiwu data export            # 导出数据为 JSON
```

---

## 数据存储

所有数据存储在 `~/.kaiwu/` 目录：

```
~/.kaiwu/
├── config.toml           # 配置文件
├── error_kb.json         # 错误知识库
├── experiences.json      # 经验库
├── scene_enrichments.json # 场景增强内容
├── profile.json          # 用户画像
├── usage.json            # 用量统计
├── sessions/             # 会话记录
└── kaiwu.log             # 运行日志
```

---

## DeepSeek API Key

AI 增强功能（智能规划、错误分析、经验提炼）需要 DeepSeek API Key：

1. 访问 [platform.deepseek.com](https://platform.deepseek.com) 注册账号
2. 进入「API Keys」页面，点击「创建 API Key」
3. 新用户赠送 500 万 tokens 免费额度
4. 用完后充值 ¥2 起步，日常使用约 ¥0.1/天

---

## 项目结构

```
cl-kaiwu/
├── pyproject.toml          # 项目配置
├── README.md
├── kaiwu/                  # 核心包
│   ├── __init__.py
│   ├── __main__.py         # python -m kaiwu 入口
│   ├── cli.py              # 命令行工具
│   ├── server.py           # MCP Server（7 个工具）
│   ├── config.py           # 配置管理
│   ├── planner.py          # kaiwu_plan 实现
│   ├── lessons.py          # kaiwu_lessons 实现
│   ├── recorder.py         # kaiwu_record 实现
│   ├── condenser.py        # kaiwu_condense 实现
│   ├── context.py          # kaiwu_context 实现
│   ├── scene.py            # 场景检测
│   ├── profile.py          # 用户画像
│   ├── session.py          # 会话管理
│   ├── task_classifier.py  # 任务分类器
│   ├── llm_client.py       # LLM 调用客户端
│   ├── privacy.py          # 隐私脱敏
│   ├── hooks.py            # 规则引擎
│   ├── quota.py            # 用量统计
│   ├── wizard.py           # 配置向导
│   ├── storage/
│   │   ├── error_kb.py     # 错误知识库
│   │   └── experience.py   # 经验库
│   ├── knowledge/
│   │   ├── loader.py       # 知识库加载器
│   │   ├── china_kb.md     # 中国开发者知识库
│   │   ├── python_compat.md # Python 版本兼容
│   │   ├── deps_pitfalls.md # 依赖陷阱
│   │   └── tool_priming.md # MCP 工具调用引导词
│   └── scenes/             # 19 个场景规范
│       ├── web.md
│       ├── react.md
│       ├── ...
│       └── wechat_pay.md
├── data/
│   ├── rules.json          # 规则引擎配置（16 条）
│   ├── error_kb.json       # 预置报错库（125 条）
│   └── experience.json     # 预置经验库（43 条）
```

---

## 技术栈

- **MCP 框架**: mcp[cli] (FastMCP)
- **DeepSeek 调用**: openai SDK（兼容接口）
- **存储**: JSON 文件（~/.kaiwu/）
- **CLI**: click + rich
- **日志**: loguru
- **Python**: >=3.10

依赖极简（无 litellm），安装 <30 秒。

---

## 致谢

本项目在设计上借鉴了以下开源项目和学术成果（仅借鉴架构理念，未复制代码）：

- **SWE-Exp 三层经验库** — 设计理念：精确匹配 → 模糊匹配 → LLM 分析，经验自动回写
- **[mem0](https://github.com/mem0ai/mem0)** (Apache 2.0) — 经验库四态决策（ADD/UPDATE/DELETE/NONE），写入前先比对去重
- **[MCP 协议](https://modelcontextprotocol.io/)** (MIT) — Model Context Protocol，工具注册与调用框架

### AI 生成内容声明

以下内容由 Claude (Anthropic) 协助生成，经人工审校后纳入项目：

- `kaiwu/scenes/*.md` — 19 个编码场景规范
- `kaiwu/knowledge/*.md` — 中国开发者知识库、Python 兼容性指南、依赖陷阱集、工具引导词
- `data/error_kb.json` — 预置错误知识库（125 条常见报错 + 解决方案）
- `data/experience.json` — 预置经验库（43 条种子经验）

这些内容基于 AI 的通用知识生成，不包含任何第三方版权材料的直接复制。

---

## 许可证

**Apache License 2.0** — 详见 [LICENSE](LICENSE)

你可以自由使用、修改、分发本项目的全部代码和数据。

### 贡献者协议（CLA）

向本项目提交代码或数据（Pull Request）时，需签署 [贡献者许可协议（CLA）](CLA.md)。

CLA 的核心条款：
- 你保留对贡献内容的全部权利
- 你授予项目维护者在云端服务中使用社区贡献的经验库、错误库和知识库数据的权利
- 这使我们能在未来推出云端同步和社区共享功能时，整合社区贡献的数据

> 个人使用、修改、分发不受 CLA 影响，CLA 仅适用于向本仓库提交贡献的场景。
