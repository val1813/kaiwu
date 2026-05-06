<div align="center">

# Kaiwu · 开物

**Auto-tuned local LLM serving: Kaiwu probes your hardware, model, KV cache, and context window so you get the fastest OpenAI-compatible endpoint your machine can actually sustain.**

**自动调优本地大模型：Kaiwu 探测你的硬件、模型、KV cache 和上下文窗口，给你一个机器能稳定跑出的最快 OpenAI 兼容端点。**

[English](#english) · [中文](#中文)

</div>

---

<a name="english"></a>
# Kaiwu

LM Studio and Ollama make models run. Kaiwu makes them run *well* — by measuring, not guessing.

It probes your GPU, reads the model architecture, benchmarks KV cache options, and walks the context window down from the model's native maximum until it finds the largest window your hardware can sustain at a useful speed. That config is cached. Second launch takes 2 seconds.

## Proof

### 30B MoE on 8GB GPU — the hard case

Model: Qwen3-30B-A3B Q3_K_XL · RTX 5060 Laptop 8GB · Windows 11

| | LM Studio | Kaiwu |
|---|---|---|
| Speed | 3 tok/s | **8.7 tok/s** |
| Context window | 4K (default) | **32K (auto)** |
| VRAM used | 7,549 MB (93%) | 4,800 MB (59%) |
| Config required | Manual | **None** |

LM Studio fills VRAM trying to load the full model. Kaiwu detects the MoE architecture, keeps attention layers on GPU, routes 128 expert layers through CPU — usable speed at 32K context on hardware that can't fit the model at all.

### 8B dense — everyday use

Model: Llama 3.1 8B Q5_K_M · RTX 5060 8GB

| | LM Studio | Kaiwu |
|---|---|---|
| Speed (8K ctx) | 46.5 tok/s | **51.7 tok/s** |
| Context window | 4–8K (default) | **64K (auto)** |

Same speed, 8× more context. Kaiwu calculates whether f16 KV cache fits in VRAM and uses it when it does — matching LM Studio's speed while running a much larger context window.

### Dual 4090 — high-end

Model: Qwen3.6-35B-A3B · 2× RTX 4090 24GB

- **115 tok/s** · **256K context** · fully automatic tensor split

## How It Works

```
kaiwu run Qwen3-30B-A3B
```

That's it. Kaiwu:

1. **Probes your hardware** — GPU model, VRAM, memory bandwidth, SM version, CPU cores, RAM
2. **Reads the model** — architecture, layer count, KV heads, native context limit, MoE structure
3. **Selects KV cache** — calculates f16 footprint; uses f16 if it fits, q8_0+q4_0 if not, iso3 for tight VRAM
4. **Runs warmup benchmark** — walks ctx from native max downward, stops where speed ≥ 20 tok/s
5. **Tunes parameters** — ubatch size, thread count, mlock — all measured, not guessed
6. **Caches the result** — next launch skips warmup entirely (2s startup)

On subsequent runs:

```
✓ Using last config  (64K ctx · 26.2 tok/s · 3 days ago)
```

## Installation

**Windows** (PowerShell):
```powershell
irm https://raw.githubusercontent.com/val1813/kaiwu/main/install.ps1 | iex
```

**Linux / macOS**:
```bash
curl -fsSL https://raw.githubusercontent.com/val1813/kaiwu/main/install.sh | sh
```

Or download manually from [Releases](https://github.com/val1813/kaiwu/releases).

## Quick Start

```bash
# Run a model (auto-downloads if needed)
kaiwu run Qwen3-30B-A3B

# Run a local GGUF file
kaiwu run /path/to/model.gguf

# Connect your IDE (Continue, Cursor, Claude Code)
# Point it to: http://localhost:11435/v1

# Check what's running
kaiwu status

# Stop
kaiwu stop
```

The API is OpenAI-compatible. Any tool that works with the OpenAI API works with Kaiwu.

## Advanced Usage

```bash
# Override context size
kaiwu run Qwen3-8B --ctx-size 12000

# Force re-tune (after hardware change)
kaiwu run Qwen3-8B --reset

# Fast start — skip warmup, use cached config only
kaiwu run Qwen3-8B --fast

# List available models
kaiwu list

# Inject IDE config automatically
kaiwu inject
```

## What Gets Auto-Tuned

| Parameter | How Kaiwu decides |
|---|---|
| Context length | Walks from model's native max down; stops where speed ≥ 20 tok/s |
| KV cache type | Calculates f16 footprint; uses f16 → q8_0+q4_0 → iso3 by VRAM fit |
| MoE expert placement | Detects `.ffn_.*_exps.` tensors; routes to CPU automatically |
| ubatch size | Benchmarks 128 vs 512; picks the faster one |
| Thread count | 2 for full-GPU, physical_cores/2 for MoE offload |
| mlock | Enabled when RAM headroom > 30% |
| GPU tensor split | Weighted by VRAM × bandwidth when multiple GPUs detected |

## Requirements

- **GPU**: NVIDIA (CUDA) — 4GB+ VRAM recommended
- **Driver**: ≥ 550.54 (Windows) / ≥ 550.54 (Linux) — required for CUDA 12.4 runtime bundled with Kaiwu
  - Check: `nvidia-smi` → look for "Driver Version"
  - Update at: [nvidia.com/drivers](https://www.nvidia.com/drivers)
- **OS**: Windows 10/11, Linux (Ubuntu 20.04+)
- **RAM**: 8GB+ (16GB+ for 30B MoE models)
- **Model format**: GGUF

CPU-only inference is supported but not the focus.

## Commands

| Command | What it does |
|---|---|
| `run <model>` | Start a model. Downloads if needed. |
| `stop` | Stop the running model. |
| `status` | Show running model, speed, VRAM usage. |
| `list` | List available and downloaded models. |
| `probe` | Show detected hardware. |
| `inject` | Configure Continue/Cursor to use Kaiwu. |
| `version` | Show version. |

## Changelog

### v0.3.2 — VRAM detection fix + MoE partial guard + RTX PRO support
- Fixed VRAM over-reporting on Windows: Resizable BAR / shared GPU memory caused nvidia-smi to report inflated VRAM (e.g. 4070 showing 31GB instead of 12GB). Now cross-checks XML vs CSV values and caps to known GPU VRAM limits
- Fixed MoE partial mode OOM on small-VRAM cards: when model size > 1.2× total VRAM, forces `moe_offload` (all experts on CPU) instead of attempting `moe_partial` which would OOM
- Added RTX PRO series (Blackwell professional) to bandwidth fallback table: PRO 6000/5000/4500/4000/2000 — fixes bandwidth=0 causing suboptimal tuning
- Added `knownMaxVRAM()` lookup table covering all consumer/professional/datacenter NVIDIA GPUs

### v0.3.1 — MoE OOM root cause fix (--fit conflicts with --cpu-moe)
- `--fit on` cannot be combined with `--cpu-moe`/`--n-cpu-moe`（ik_llama.cpp docs）. Previous versions passed both, causing --fit to override MoE layer placement → OOM. Now only `full_gpu` uses `--fit on`; MoE modes use `-ngl 999` + explicit offload flags
- `calcMoEMode` overhead: 1GB → 2.5GB (reserves KV cache + compute buffer space)
- MoE + multi-GPU: skip `-sm graph`, use layer split + `GGML_CUDA_DISABLE_GRAPHS=1`
- `isLikelyOOM` excludes missing .so errors

### v0.2.9 — moe_partial + -sm graph detection + LD_LIBRARY_PATH
- New `moe_partial` mode: calculates `--n-cpu-moe N` based on VRAM, keeping as many expert layers on GPU as possible. Enables running 120B MoE models on 8GB VRAM
- `-sm graph` now runtime-detected: falls back to `--tensor-split` if binary doesn't support it. Prevents process exit from being misidentified as OOM
- `isLikelyOOM` excludes parameter errors and timeouts from OOM detection
- Linux: sets `LD_LIBRARY_PATH` to binary directory, fixing `libmtmd.so.0 not found`
- `buildArgs`/`BuildArgs` signature includes `binaryPath` for correct graph split detection

### v0.2.8 — Three-mode selection + relative threshold (no more hardcoded 20 tok/s)
- Warmup no longer filters by a fixed 18 tok/s threshold. Instead, collects all successful probe data points and derives three modes:
  - Speed: fastest ctx (smallest ctx, highest tok/s)
  - Balanced: largest ctx where TPS >= peak × 0.7
  - Context: largest ctx where TPS >= 15 tok/s
- Interactive selection after first warmup (10s timeout defaults to balanced), saved to config
- Subsequent launches use cache; `--mode speed/balanced/context` switches without re-warmup
- MoE mode or identical ctx across modes skips selection menu

### v0.2.7 — Blackwell JIT warmup (permanent fix for startup timeout)
- RTX 50-series first run now executes `llama-server --version` to trigger PTX JIT compilation and populate CUDA cache. All subsequent launches (warmup probes + final start) read from cache and start in ~2s
- No longer relies on extending timeouts to "hope" JIT finishes in time — JIT warmup runs once, result persists on disk across reboots
- Multi-GPU `--kv-unified` skip also included (v0.2.6 fix)

### v0.2.6 — Fix multi-GPU OOM (--kv-unified lands on GPU 0 only)
- `--kv-unified` allocates entire KV cache on a single device (GPU 0). On dual 3090, model splits across both cards but KV cache all goes to GPU 0 → OOM. Now skipped when GPUCount > 1

### v0.2.5 — (same as v0.2.6, tag issue)

### v0.2.4 — Fix panic on older GPUs (P6000, Tesla, etc.)
- `Fingerprint()` used hardcoded slice indices to remove dot from `ComputeCap` — panics on empty string. Replaced with `strings.ReplaceAll`

### v0.2.3 — Fix Blackwell startup timeout misidentified as OOM
- RTX 50-series startup timeout (90s) was too short for PTX JIT compilation (~60s) — timeout error was caught by `isLikelyOOM()` → false ctx-halving loop → 3 failures. Now 180s for Blackwell with distinct error message

### v0.2.2 — Blackwell OOM fix + MoE VRAM optimization + --host flag
- Fixed RTX 50-series (SM120) OOM on all context sizes: `--kv-unified` causes massive VRAM over-allocation with CUDA 12.4 binary on CUDA 13.x driver. Now skipped on Blackwell — llama.cpp uses paged KV allocation instead (grows on demand)
- Fixed RTX 50-series startup timeout being misidentified as OOM: CUDA 12.4 binary on SM120 needs PTX JIT compilation (~60s), old 90s timeout caused false OOM → ctx halving loop. Now 180s for Blackwell, with distinct error message so `isLikelyOOM` won't trigger ctx retry
- Warmup start point on Blackwell changed from `ideal×2` to `ideal` — the aggressive headroom caused all 8 probes to OOM before finding a working config
- MoE VRAM reserve changed from hardcoded 1536MB to dynamic calculation (`model_size × 0.30`). After warmup, measured VRAM is written back for even more accurate KV cache type selection. Fixes users seeing 4GB+ unused VRAM while stuck on small ctx
- iso3 detection no longer depends on `.kaiwu` marker file — `EnsureBinary` returns `isTurboQuant` directly (bundled = turboquant, downloaded = not)
- New `--host` flag: `kaiwu run model --host 0.0.0.0` to listen on all interfaces (LAN access). Default remains `127.0.0.1`

### v0.2.0 — iso3 detection rewrite (static, no more timeouts)
- Replaced runtime iso3 detection (`--help` + timeout) with static check: marker file + SM >= 80. Eliminates all JIT timeout failures on RTX 50-series (SM120) and CUDA 13.x
- CI now ships a `.kaiwu` marker file alongside the turboquant binary
- Removed `DetectIso3Support`, `DetectIso3SupportForSM`, and all iso3 cache logic
- New `ClusterCapabilities` architecture: multi-GPU capability decisions now take the intersection (min SM, all-support-iso3, all-support-FA) instead of relying on a single "primary" GPU. Resources (VRAM, bandwidth) are summed. Fixes heterogeneous multi-GPU misdetection (e.g. 4070+3060 where both have 12GB VRAM)
- `PrimaryGPU()` now selects by bandwidth (not VRAM), used only for display — all capability checks go through `ClusterCaps()`
- VRAM detection: added CSV fallback when XML `fb_memory_usage` returns 0 (newer driver schema changes). `parseMemValue` now handles "MiB", "MB", and comma-separated numbers
- Warns when GPU VRAM=0 detected, with link to report the issue

### v0.1.9 — Multi-GPU tensor split optimization
- Multi-GPU tensor split now weighted by VRAM × bandwidth instead of VRAM alone. Heterogeneous setups (e.g. 3090+4090+5060) get smarter layer distribution — weak cards receive fewer layers so they don't bottleneck the system
- Multi-GPU display now shows each card individually with VRAM, bandwidth, and computed split ratio
- `--fit on` now applied unconditionally for both full_gpu and moe_offload modes (was missing for moe_offload in fallback path)
- Accel display shows tensor split ratio for multi-GPU without NVLink

### v0.1.8 — MoE warmup no speed threshold
- MoE offload warmup no longer uses a speed threshold. Speed is PCIe-bandwidth-limited, not context-limited — dropping ctx from 128K to 4K only improves speed ~20-30%, never enough to cross any threshold. Warmup now finds the largest ctx that fits in VRAM and reports whatever speed the hardware delivers
- Warmup output now shows: `ℹ MoE offload · speed limited by PCIe bandwidth, not context size`

### v0.1.7 — MoE warmup threshold + /responses endpoint
- MoE offload warmup threshold lowered 18 → 8 tok/s: laptop MoE is PCIe-limited to 13-15 tok/s max; the old threshold caused warmup to always fall back to the smallest ctx even when the model runs fine
- Proxy now handles `/responses` (without `/v1/` prefix) in addition to `/v1/responses` — fixes 404 errors from newer Cursor and Claude Code clients

### v0.1.6 — MoE offload fix + direct path fix
- Fixed MoE models (Qwen3-30B, DeepSeek, etc.) always failing warmup with OOM: the previous `-ot` regex for routing expert layers to CPU wasn't working; replaced with `--cpu-moe` which is natively supported
- KV cache selection for MoE now trusts llama.cpp's `--fit` to handle layer placement, instead of guessing the GPU footprint with a hardcoded ratio
- Warmup timeout extended 60s → 180s to handle large MoE models loading ~13GB from RAM
- Fixed `kaiwu run /path/to/model.gguf` silently downloading the model instead of using the local file (regression from v0.1.3)

### v0.1.5 — iso3 cache + bandwidth-aware tuning
- iso3 detection result cached to disk — same binary only detects once
- SM-aware timeout: SM<75 skipped, SM75-119 uses 15s, SM120+ uses 60s
- OOM suggestion copy is now dynamic — small models no longer wrongly told to switch to MoE
- Small models (<2GB) ubatch reduced 512→128, fixing `--kv-unified` pre-allocation OOM
- Memory bandwidth calculated from nvidia-smi XML (`bus_width × max_mem_clock × 2`)
- Low-bandwidth GPUs (<200 GB/s) only benchmark ubatch=128, saving 1-2 min warmup
- Full GPU bandwidth table (GTX 10/16/20/30/40/50 + datacenter V100/P100/H200)

### v0.1.4 — Blackwell architecture support
- Fixed iso3 detection timeout on RTX 50-series (SM120): 10s → 60s
- Root cause: CUDA 12.4 has no SM120 precompiled kernels; PTX JIT takes ~30s on first run
- Prints warning when SM120 detected: `⚠ RTX 50-series first launch requires JIT compilation (~30s)`

### v0.1.3 — hybrid architecture + APEX quantization
- APEX quantization presets: Quality (q8_0) / Balanced (q5_k_m) / Compact (q4_k_m)
- Hybrid architecture detection: auto-disables iso3 + enables `--swa-full` for DeltaNet/SSM models
- Direct GGUF path support introduced (fixed properly in v0.1.6)
- Flash Attention auto-enabled on SM75+
- NVLink auto-detection
- nvidia-smi XML parsing (replaces fragile CSV)
- Fixed multi-GPU VRAM calculation

### v0.1.2 — iso3 detection timing fix
- Moved iso3 detection to Preflight (before warmup)
- Root cause: warmup launched llama-server with iso3 flags before confirming support → all ctx probes failed, false OOM

### v0.1.1 — initial release
- Hardware probe: GPU (nvidia-smi), CPU, RAM
- Model matcher: VRAM-based quantization selection, full_gpu / moe_offload modes
- Warmup benchmark: binary search for max ctx at ≥20 tok/s, ubatch measurement
- Config cache: results saved to `~/.kaiwu/profiles/`, 2s second launch
- Bundled turboquant iso3 llama-server binary
- OpenAI-compatible API at `http://localhost:11435/v1`

---

<a name="中文"></a>
# 开物 (Kaiwu)

> *"开物成务，利用厚生"* — 明·宋应星《天工开物》

LM Studio 和 Ollama 让模型能跑。Kaiwu 让模型跑好——靠实测，不靠猜。

它探测你的 GPU、读取模型架构、测试 KV cache 选项，然后从模型的原生最大上下文往下走，找到你的硬件能以实用速度稳定跑出的最大窗口。结果缓存起来，第二次启动只需 2 秒。

## 数据说话

### 8GB 显卡跑 30B 模型——最难的场景

模型：Qwen3-30B-A3B Q3_K_XL · RTX 5060 笔记本 8GB · Windows 11

| | LM Studio | Kaiwu |
|---|---|---|
| 速度 | 3 tok/s | **8.7 tok/s** |
| 上下文窗口 | 4K（默认） | **32K（自动）** |
| 显存占用 | 7,549 MB（93%） | 4,800 MB（59%） |
| 需要手动配置 | 是 | **不需要** |

LM Studio 试图把整个模型塞进显存，直接 OOM。Kaiwu 识别出 MoE 架构，只把 attention 层放 GPU，128 个 expert 层走 CPU——在装不下整个模型的硬件上，跑出 32K 上下文的可用速度。

### 8B 模型——日常使用

模型：Llama 3.1 8B Q5_K_M · RTX 5060 8GB

| | LM Studio | Kaiwu |
|---|---|---|
| 速度（8K 上下文） | 46.5 tok/s | **51.7 tok/s** |
| 上下文窗口 | 4–8K（默认） | **64K（自动）** |

速度持平甚至更快，上下文多 8 倍。Kaiwu 计算 f16 KV cache 能不能装进显存，能装就用——速度匹配 LM Studio，同时跑更大的上下文。

### 双 4090——高端配置

模型：Qwen3.6-35B-A3B · 2× RTX 4090 24GB

- **115 tok/s** · **256K 上下文** · 自动多卡分配

## 工作原理

```
kaiwu run Qwen3-30B-A3B
```

就这一句。Kaiwu 会：

1. **探测硬件** — GPU 型号、显存、内存带宽、SM 版本、CPU 核数、内存
2. **读模型信息** — 架构、层数、KV heads、原生上下文限制、MoE 结构
3. **选 KV cache** — 计算 f16 占用；能装用 f16，不够降 q8_0+q4_0，显存极紧用 iso3
4. **跑 warmup 基准测试** — 从最大上下文往下探，找速度 ≥ 20 tok/s 的最大值
5. **调整参数** — ubatch 大小、线程数、mlock——全部实测，不靠猜
6. **缓存结果** — 下次启动跳过 warmup，2 秒就绪

第二次启动你会看到：

```
✓ 使用上次配置  (64K ctx · 26.2 tok/s · 3 天前)
```

## 安装

**Windows** (PowerShell):
```powershell
irm https://raw.githubusercontent.com/val1813/kaiwu/main/install.ps1 | iex
```

**Linux / macOS**:
```bash
curl -fsSL https://raw.githubusercontent.com/val1813/kaiwu/main/install.sh | sh
```

也可以从 [Releases](https://github.com/val1813/kaiwu/releases) 手动下载。

## 快速开始

```bash
# 运行模型（没有会自动下载）
kaiwu run Qwen3-30B-A3B

# 运行本地 GGUF 文件
kaiwu run /path/to/model.gguf

# 接入 IDE（Continue、Cursor、Claude Code）
# API 地址：http://localhost:11435/v1

# 查看运行状态
kaiwu status

# 停止
kaiwu stop
```

API 兼容 OpenAI 格式，任何支持 OpenAI API 的工具都可以直接用。

## 进阶用法

```bash
# 指定上下文大小
kaiwu run Qwen3-8B --ctx-size 12000

# 强制重新调参（换了硬件后）
kaiwu run Qwen3-8B --reset

# 快速启动——跳过 warmup，直接用缓存
kaiwu run Qwen3-8B --fast

# 列出可用模型
kaiwu list

# 自动配置 IDE
kaiwu inject
```

## 自动调整的参数

| 参数 | Kaiwu 怎么决定 |
|---|---|
| 上下文长度 | 从模型最大值往下探，找速度 ≥ 20 tok/s 的最大值 |
| KV cache 类型 | 计算 f16 占用；按显存依次选 f16 → q8_0+q4_0 → iso3 |
| MoE expert 位置 | 自动识别 `.ffn_.*_exps.` 张量，路由到 CPU |
| ubatch 大小 | 实测 128 vs 512，取快的 |
| 线程数 | 全 GPU 用 2，MoE offload 用物理核 /2 |
| mlock | 内存余量 > 30% 时自动开，防止模型被换出到磁盘 |
| 多卡分配 | 按显存×带宽加权自动切分，弱卡少分活 |

## 硬件要求

- **显卡**：NVIDIA（CUDA）——建议 4GB+ 显存
- **驱动**：≥ 550.54——Kaiwu 内置 CUDA 12.4 runtime，需要此版本驱动支持
  - 查看：`nvidia-smi` → 看 "Driver Version"
  - 更新：[nvidia.com/drivers](https://www.nvidia.com/drivers)
- **系统**：Windows 10/11，Linux（Ubuntu 20.04+）
- **内存**：8GB+（30B MoE 模型建议 16GB+）
- **模型格式**：GGUF

支持纯 CPU 推理，但不是主要使用场景。

## 命令列表

| 命令 | 说明 |
|---|---|
| `run <模型>` | 启动模型，没有会自动下载 |
| `stop` | 停止运行中的模型 |
| `status` | 显示当前模型、速度、显存占用 |
| `list` | 列出可用和已下载的模型 |
| `probe` | 显示检测到的硬件信息 |
| `inject` | 自动配置 Continue/Cursor 接入 Kaiwu |
| `version` | 显示版本号 |

## 版本历史

### v0.2.3 — 修复 Blackwell 启动超时被误判为 OOM
- RTX 50 系启动超时（90s）不够 PTX JIT 编译（~60s），超时错误被 `isLikelyOOM()` 捕获 → ctx 减半重试循环 → 三次全失败。Blackwell 现在 180s 超时，错误信息与 OOM 区分开

### v0.3.2 — VRAM 检测修复 + MoE partial 保护 + RTX PRO 支持
- 修复 Windows 下 VRAM 虚高：Resizable BAR / 共享 GPU 内存导致 nvidia-smi 报告虚假 VRAM（如 4070 显示 31GB 而非 12GB）。现在 XML 与 CSV 交叉校验，并用已知 GPU VRAM 上限表兜底
- 修复小显存卡 MoE partial 模式 OOM：当模型大小 > 1.2× 总 VRAM 时，强制走 `moe_offload`（全部 expert 放 CPU），不再尝试 `moe_partial`
- 新增 RTX PRO 系列（Blackwell 专业卡）带宽枚举：PRO 6000/5000/4500/4000/2000——修复带宽=0 导致调参不准
- 新增 `knownMaxVRAM()` 查找表，覆盖所有消费级/专业/数据中心 NVIDIA GPU

### v0.3.1 — MoE OOM 根因修复（--fit 与 --cpu-moe 冲突）
- `--fit on` 不能和 `--cpu-moe`/`--n-cpu-moe` 同时使用（ik_llama.cpp 文档明确说明）。之前所有版本都同时传了两个，`--fit` 覆盖了 MoE 层分配 → OOM。现在只有 `full_gpu` 用 `--fit on`，MoE 模式用 `-ngl 999` + 显式 offload 参数
- `calcMoEMode` overhead 从 1GB 增加到 2.5GB（预留 KV cache + compute buffer 空间）
- MoE + 多卡：跳过 `-sm graph`，用 layer split + `GGML_CUDA_DISABLE_GRAPHS=1`
- `isLikelyOOM` 排除 .so 缺失错误

### v0.2.9 — moe_partial + -sm graph 检测 + LD_LIBRARY_PATH
- 新增 `moe_partial` 模式：根据 VRAM 计算 `--n-cpu-moe N`，只把超出显存的 expert 层放 CPU，其余留 GPU。8GB 卡可跑 120B MoE 模型
- `-sm graph` 改为运行时检测：binary 不支持时自动降级到 `--tensor-split`，不再因参数错误导致进程退出被误判 OOM
- `isLikelyOOM` 排除参数错误和超时，不再触发错误的 ctx 减半重试
- Linux 启动时设 `LD_LIBRARY_PATH` 到 binary 目录，修复 `libmtmd.so.0 not found`
- `buildArgs`/`BuildArgs` 签名加 `binaryPath` 参数，graph split 检测用正确的 binary

### v0.2.8 — 三档模式选择 + 相对阈值（不再写死 20 tok/s）
- Warmup 不再用固定 18 tok/s 阈值过滤。改为收集所有成功的 probe 数据点，探测结束后推导三档：
  - 速度优先：最快的 ctx（最小 ctx，最高 tok/s）
  - 均衡：峰值速度 × 0.7 阈值下的最大 ctx
  - 上下文优先：速度 ≥ 15 tok/s 的最大 ctx
- 首次 warmup 后交互选择（10s 超时默认均衡），选择结果保存到 config
- 下次启动直接用缓存，`--mode speed/balanced/context` 切换不需要重新 warmup
- MoE 模式或三档 ctx 相同时跳过选择菜单

### v0.2.7 — Blackwell JIT 预热（彻底解决启动超时）
- RTX 50 系首次运行时，先执行 `llama-server --version` 触发 PTX JIT 编译并写入 CUDA 缓存。后续所有启动秒开
- 不再依赖延长超时——JIT 预热只需一次，结果持久化到磁盘，重启也不丢
- 多卡场景跳过 `--kv-unified`（v0.2.6 修复也包含在内）

### v0.2.2 — Blackwell OOM 修复 + --host 参数
- 修复 RTX 50 系（SM120）所有上下文大小都 OOM 的问题：`--kv-unified` 在 CUDA 12.4 binary + CUDA 13.x 驱动下会过度分配显存。Blackwell 现在跳过此参数，llama.cpp 改用分页式 KV 分配（按需增长）
- Blackwell warmup 起点从 `ideal×2` 改为 `ideal`——激进的探顶策略导致 8 次探测全部 OOM
- iso3 检测不再依赖 `.kaiwu` 标记文件——`EnsureBinary` 直接返回 `isTurboQuant`（bundled = turboquant，下载的 = 不是）
- 新增 `--host` 参数：`kaiwu run model --host 0.0.0.0` 监听所有网卡（局域网访问）。默认仍为 `127.0.0.1`

### v0.2.0 — iso3 检测重写（静态判断，不再超时）
- iso3 检测从运行时（`--help` + 超时）改为静态判断：标记文件 + SM >= 80。彻底消除 RTX 50 系（SM120）和 CUDA 13.x 下的 JIT 超时误判
- CI 打包时在 turboquant binary 旁放 `.kaiwu` 标记文件
- 删除 `DetectIso3Support`、`DetectIso3SupportForSM` 及所有 iso3 缓存逻辑
- 新增 `ClusterCapabilities` 架构：多卡能力判断改为取交集（最低 SM、全部支持 iso3、全部支持 FA），资源取总和。修复异构多卡误识别（如 4070+3060 同为 12GB 时主卡选错）
- `PrimaryGPU()` 改为按带宽选主卡（不再按 VRAM），仅用于显示——所有能力判断走 `ClusterCaps()`
- VRAM 检测：XML `fb_memory_usage` 返回 0 时自动用 CSV fallback（兼容新版驱动 schema 变化）。`parseMemValue` 支持 "MiB"/"MB"/逗号分隔数字
- GPU VRAM=0 时打印警告和 issue 链接，方便用户反馈

### v0.1.9 — 多卡 tensor split 优化
- 多卡 tensor split 从纯按显存比例改为按 显存×带宽 加权。异构多卡（如 3090+4090+5060）分配更合理——弱卡少分层，不拖慢整体
- 多卡显示改为逐卡列出（型号、显存、带宽、分配比例）
- `--fit on` 现在对 full_gpu 和 moe_offload 两种模式都无条件启用（之前 fallback 路径的 moe_offload 漏了）
- 加速特性显示新增 tensor split 比例（多卡无 NVLink 时）

### v0.1.8 — MoE warmup 不再限速
- MoE offload warmup 不再使用速度阈值。MoE 的速度瓶颈是 PCIe 带宽，不是 ctx 大小——ctx 从 128K 降到 4K 速度只提升 20-30%，永远到不了任何阈值。现在直接找显存能装下的最大 ctx，速度是多少就是多少
- warmup 结束后新增提示：`ℹ MoE offload · speed limited by PCIe bandwidth, not context size`

### v0.1.7 — MoE warmup 阈值 + /responses 端点
- MoE offload warmup 阈值从 18 降到 8 tok/s：笔记本 MoE 受 PCIe 带宽限制，上限约 13-15 tok/s，旧阈值导致 warmup 总是 fallback 到最小 ctx，即使模型跑得好好的
- proxy 新增 `/responses` 路由（不带 `/v1/` 前缀），修复新版 Cursor 和 Claude Code 调用时的 404

### v0.1.6 — MoE offload 修复 + 直接路径修复
- 修复 MoE 模型（Qwen3-30B、DeepSeek 等）warmup 全 OOM 的问题：之前用 `-ot` 正则把 expert 层路由到 CPU 实际没生效，改用 llama.cpp 原生支持的 `--cpu-moe`
- MoE 模式的 KV cache 选择不再用硬编码比例猜 GPU 占用，改为信任 llama.cpp 的 `--fit` 自动处理层分配
- warmup 超时从 60s 延长到 180s，适配大 MoE 模型从内存加载 ~13GB 的时间
- 修复 `kaiwu run /path/to/model.gguf` 实际走下载而非使用本地文件的 bug（v0.1.3 引入的回归）

### v0.1.5 — iso3 缓存 + 带宽感知调参
- iso3 检测结果缓存到磁盘，同一 binary 只检测一次
- SM 版本感知超时：SM<75 直接跳过，SM75-119 用 15s，SM120+ 用 60s
- OOM 建议文案动态化：小模型 OOM 不再错误建议换 MoE
- 小模型（<2GB）ubatch 从 512 降到 128，修复 `--kv-unified` 预分配 OOM
- 带宽从 nvidia-smi XML 精确计算（`bus_width × max_mem_clock × 2`）
- 低带宽卡（<200 GB/s）warmup 只测 ubatch=128，减少 1-2 分钟等待
- 完整 GPU 带宽枚举表（GTX 10/16/20/30/40/50 + 数据中心）

### v0.1.4 — Blackwell 架构支持
- 修复 RTX 50 系（SM120）iso3 检测超时：10s → 60s
- 根因：CUDA 12.4 无 SM120 预编译 kernel，PTX JIT 编译需 ~30s
- 检测到 SM120 时打印提示：`⚠ RTX 50 系首次启动需要 JIT 编译 (~30s)`

### v0.1.3 — 混合架构支持 + APEX 量化
- APEX 量化三档预设：Quality (q8_0) / Balanced (q5_k_m) / Compact (q4_k_m)
- 混合架构动态检测：iso3 自动禁用 + `--swa-full` 补偿（DeltaNet/SSM 架构）
- 直接 GGUF 路径支持（v0.1.6 修复了实际生效的 bug）
- Flash Attention 自动启用（SM75+）
- NVLink 自动检测
- nvidia-smi XML 解析（替代脆弱的 CSV 解析）
- 修复多卡 VRAM 计算错误

### v0.1.2 — iso3 检测时机修复
- iso3 检测移到 warmup 之前（Preflight 阶段）
- 根因：warmup 用 iso3 参数启动 llama-server，但 binary 不支持 → 所有 ctx 探测失败，误报 OOM

### v0.1.1 — 初始版本
- 硬件探测：GPU（nvidia-smi）、CPU、内存
- 模型匹配：基于 VRAM 选量化，full_gpu / moe_offload 两种模式
- Warmup 基准测试：二分探测最大 ctx，ubatch 实测
- 配置缓存：结果保存到 `~/.kaiwu/profiles/`，第二次启动 2 秒
- 内置 turboquant iso3 llama-server binary
- OpenAI 兼容 API：`http://localhost:11435/v1`

---

## For Developers / 贡献者

Build from source (requires Go 1.22+):

```bash
git clone https://github.com/val1813/kaiwu.git
cd kaiwu
make build-windows   # or build-linux
```

---

<div align="center">

Built on [llama.cpp](https://github.com/ggerganov/llama.cpp) · by [llmbbs.ai](https://llmbbs.ai)

</div>
