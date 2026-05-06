package model

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/val1813/kaiwu/internal/config"
	"github.com/val1813/kaiwu/internal/hardware"
)

// DeployProfile is the result of matching a model to hardware
type DeployProfile struct {
	ModelID      string
	DisplayName  string
	Family       string
	Arch         string
	NativeMTP    bool
	Quant        string
	HFRepo       string
	HFFile       string
	Size_GB      float64
	Mode         string // "full_gpu", "moe_partial", or "moe_offload"
	NCpuMoe      int    // for moe_partial: number of expert layers on CPU (0 = auto-calculate)
	OTFlags      string
	StopTokens   []string
	Layers       int
	ExpertsTotal int  // total number of expert layers in the model
	KVHeads      int  // GQA kv_heads 数量，用于 KV cache 精确计算
	HeadDim      int  // attention head dimension（通常 128）
	EmbeddingDim int  // embedding dimension（hidden_size）
	NativeCtx    int  // 模型原生最大上下文（从 GGUF context_length 读取）
	CtxOverride    int  // 微调模式：用户手动指定的 ctx 大小，0 = 自动
	HasIsoQuant    bool // IsoQuant KV cache 压缩是否可用
	IsHybrid       bool // hybrid attention+recurrent architecture (DeltaNet/SSM/Mamba)
	MeasuredVRAM_MB int  // warmup 实测显存占用（MB），用于 MoE SelectKVCacheType 精确计算，0=未测
	LocalPath    string // 直接路径模式：绝对路径，跳过下载
}

// Match selects the best quantization for the given hardware
func Match(model *ModelDef, hw *hardware.HardwareProbe) (*DeployProfile, error) {
	vramGB := float64(hw.TotalVRAM_MB()) / 1024.0 // 多卡总VRAM
	ramGB := float64(hw.RAM.Total_MB) / 1024.0

	profile := &DeployProfile{
		ModelID:      model.ID,
		DisplayName:  model.DisplayName,
		Family:       model.Family,
		Arch:         model.Arch,
		NativeMTP:    model.NativeMTP,
		IsHybrid:     model.IsHybrid,
		StopTokens:   model.StopTokens,
		Layers:       model.Layers,
		ExpertsTotal: model.ExpertsTotal,
		KVHeads:      model.KVHeads,
		HeadDim:      model.HeadDim,
		HasIsoQuant:  !model.IsHybrid, // iso3 breaks on hybrid architectures (DeltaNet layers have no KV cache)
	}

	// Strategy 1: Full GPU — all layers in VRAM
	// For MoE models, full_gpu needs size_gb (entire model) to fit in VRAM
	// For dense models, min_vram_gb is the actual VRAM needed
	var fullGPU []Quantization
	for _, q := range model.Quantizations {
		needed := q.MinVRAM_GB
		if model.IsMoE() {
			needed = q.Size_GB
		}
		// 本地已有文件时放宽阈值（OOM preflight 会兜底）
		reserve := 1.0
		if isLocalAvailable(q.HFFile) {
			reserve = 0.0 // 本地有文件，让 preflight 决定能不能跑
		}
		if needed <= vramGB-reserve {
			fullGPU = append(fullGPU, q)
		}
	}

	// Strategy 2: MoE offload — shared layers in GPU, experts in CPU
	// For MoE models, prefer offload mode if it gives better quality
	var moeOffload []Quantization
	if model.IsMoE() {
		for _, q := range model.Quantizations {
			if q.MinVRAM_GB <= vramGB-1 && q.MinRAM_GB <= ramGB-3 {
				moeOffload = append(moeOffload, q)
			}
		}
	}

	// Choose best strategy: prefer MoE offload with higher quality over full GPU with lower quality
	if len(moeOffload) > 0 && len(fullGPU) > 0 {
		// Sort both by quality (size_gb as proxy)
		sort.Slice(fullGPU, func(i, j int) bool {
			return fullGPU[i].Size_GB > fullGPU[j].Size_GB
		})
		sort.Slice(moeOffload, func(i, j int) bool {
			return moeOffload[i].Size_GB > moeOffload[j].Size_GB
		})

		// If MoE offload best is significantly better quality, use it
		if moeOffload[0].Size_GB > fullGPU[0].Size_GB*1.2 {
			best := moeOffload[0]
			profile.Quant = best.ID
			profile.HFRepo = best.HFRepo
			profile.HFFile = best.HFFile
			profile.Size_GB = best.Size_GB
			profile.OTFlags = model.MoeOffloadTemplate
			// Calculate moe_partial vs moe_offload
			profile.Mode, profile.NCpuMoe = calcMoEMode(profile, hw)
			enrichFromGGUF(profile)
			return profile, nil
		}
	}

	// Use full GPU if available
	if len(fullGPU) > 0 {
		// 优先选本地已有的文件，避免不必要的下载
		sort.Slice(fullGPU, func(i, j int) bool {
			iLocal := isLocalAvailable(fullGPU[i].HFFile)
			jLocal := isLocalAvailable(fullGPU[j].HFFile)
			if iLocal != jLocal {
				return iLocal // 本地文件优先
			}
			return fullGPU[i].Size_GB > fullGPU[j].Size_GB // 质量降序
		})
		best := fullGPU[0]
		profile.Quant = best.ID
		profile.HFRepo = best.HFRepo
		profile.HFFile = best.HFFile
		profile.Size_GB = best.Size_GB
		profile.Mode = "full_gpu"
		enrichFromGGUF(profile)
		return profile, nil
	}

	// Fallback to MoE offload
	if len(moeOffload) > 0 {
		sort.Slice(moeOffload, func(i, j int) bool {
			return moeOffload[i].Size_GB > moeOffload[j].Size_GB
		})
		best := moeOffload[0]
		profile.Quant = best.ID
		profile.HFRepo = best.HFRepo
		profile.HFFile = best.HFFile
		profile.Size_GB = best.Size_GB
		profile.OTFlags = model.MoeOffloadTemplate
		// Calculate moe_partial vs moe_offload
		profile.Mode, profile.NCpuMoe = calcMoEMode(profile, hw)
		enrichFromGGUF(profile)
		return profile, nil
	}

	// Strategy 3: Dense model partial offload — try smallest quant
	if !model.IsMoE() {
		var partial []Quantization
		for _, q := range model.Quantizations {
			if q.MinRAM_GB <= ramGB-3 {
				partial = append(partial, q)
			}
		}
		if len(partial) > 0 {
			sort.Slice(partial, func(i, j int) bool {
				return partial[i].MinVRAM_GB < partial[j].MinVRAM_GB
			})
			best := partial[0]
			profile.Quant = best.ID
			profile.HFRepo = best.HFRepo
			profile.HFFile = best.HFFile
			profile.Size_GB = best.Size_GB
			profile.Mode = "full_gpu"
			enrichFromGGUF(profile)
			return profile, nil
		}
	}

	return nil, fmt.Errorf(
		"insufficient hardware for %s.\n"+
			"  VRAM: %.1f GB, RAM: %.1f GB\n"+
			"  Minimum required: %.1f GB VRAM or %.1f GB RAM\n"+
			"  Consider upgrading RAM or choosing a smaller model.",
		model.DisplayName, vramGB, ramGB,
		model.Quantizations[len(model.Quantizations)-1].MinVRAM_GB,
		model.Quantizations[len(model.Quantizations)-1].MinRAM_GB,
	)
}

// isLocalAvailable checks if a model file matching the pattern exists locally
func isLocalAvailable(hfFilePattern string) bool {
	// Extract search term from pattern like "*Q5_K_M*"
	searchTerm := strings.ReplaceAll(hfFilePattern, "*", "")
	searchTerm = strings.ToLower(searchTerm)

	// Check model directory
	modelDir := config.ModelDir()
	entries, err := os.ReadDir(modelDir)
	if err == nil {
		for _, entry := range entries {
			if entry.IsDir() {
				continue
			}
			name := strings.ToLower(entry.Name())
			if strings.Contains(name, searchTerm) && strings.HasSuffix(name, ".gguf") {
				// Verify file size > 100MB (not a partial download)
				fullPath := filepath.Join(modelDir, entry.Name())
				if info, err := os.Stat(fullPath); err == nil && info.Size() > 100*1024*1024 {
					return true
				}
			}
		}
	}

	// Check alternative paths
	altPaths := []string{
		filepath.Join("D:", "program", "ollama", "test"),
		filepath.Join("D:", "program", "ollama", "kaiwu-launcher", "models"),
	}
	for _, altDir := range altPaths {
		entries, err := os.ReadDir(altDir)
		if err != nil {
			continue
		}
		for _, entry := range entries {
			if entry.IsDir() {
				continue
			}
			name := strings.ToLower(entry.Name())
			if strings.Contains(name, searchTerm) && strings.HasSuffix(name, ".gguf") {
				fullPath := filepath.Join(altDir, entry.Name())
				if info, err := os.Stat(fullPath); err == nil && info.Size() > 100*1024*1024 {
					return true
				}
			}
		}
	}

	return false
}

// findLocalGGUF finds a local .gguf file matching the HFFile pattern.
// Returns the full path or "" if not found.
func findLocalGGUF(hfFilePattern string) string {
	searchTerm := strings.ReplaceAll(hfFilePattern, "*", "")
	searchTerm = strings.ToLower(searchTerm)

	dirs := []string{config.ModelDir()}
	dirs = append(dirs,
		filepath.Join("D:", "program", "ollama", "test"),
		filepath.Join("D:", "program", "ollama", "kaiwu-launcher", "models"),
	)

	for _, dir := range dirs {
		entries, err := os.ReadDir(dir)
		if err != nil {
			continue
		}
		for _, entry := range entries {
			if entry.IsDir() {
				continue
			}
			name := strings.ToLower(entry.Name())
			if strings.Contains(name, searchTerm) && strings.HasSuffix(name, ".gguf") {
				fullPath := filepath.Join(dir, entry.Name())
				if info, err := os.Stat(fullPath); err == nil && info.Size() > 100*1024*1024 {
					return fullPath
				}
			}
		}
	}
	return ""
}

// enrichFromGGUF reads GGUF metadata from the local model file and overwrites
// Layers, KVHeads, HeadDim, NativeCtx with the real values from the file header.
// yaml values are only used as fallback when the file isn't available yet.
func enrichFromGGUF(profile *DeployProfile) {
	path := findLocalGGUF(profile.HFFile)
	if path == "" {
		return
	}
	meta, err := ReadGGUFMeta(path)
	if err != nil {
		return
	}
	if meta.Layers > 0 {
		profile.Layers = meta.Layers
	}
	if meta.KVHeads > 0 {
		profile.KVHeads = meta.KVHeads
	}
	if meta.HeadDim > 0 {
		profile.HeadDim = meta.HeadDim
	}
	if meta.ContextLength > 0 {
		profile.NativeCtx = meta.ContextLength
	}
	if meta.EmbeddingDim > 0 {
		profile.EmbeddingDim = meta.EmbeddingDim
	}
	// Update hybrid detection from actual GGUF metadata (overrides yaml)
	if meta.IsHybrid {
		profile.IsHybrid = true
		profile.HasIsoQuant = false
	}
}

// calcMoEMode determines whether to use moe_partial or moe_offload based on VRAM.
// Returns (mode, nCpuMoe).
// moe_partial: some expert layers on GPU, rest on CPU (--n-cpu-moe N)
// moe_offload: all expert layers on CPU (--cpu-moe)
func calcMoEMode(profile *DeployProfile, hw *hardware.HardwareProbe) (string, int) {
	if profile.ExpertsTotal <= 0 || profile.Layers <= 0 {
		return "moe_offload", 0 // can't calculate, fall back to full offload
	}

	vramMB := hw.TotalVRAM_MB()

	// Guard: if model is significantly larger than total VRAM, don't attempt moe_partial.
	// moe_partial requires attention layers + overhead + some experts to fit in VRAM.
	// If model_size > 1.2x VRAM, the attention layers alone likely won't fit.
	modelMB := int(profile.Size_GB * 1024)
	if modelMB > vramMB*120/100 {
		return "moe_offload", 0
	}

	// Attention layers ≈ 25% of model size
	attentionMB := int(profile.Size_GB * 1024 * 0.25)
	// Reserve for KV cache (at least 8K ctx) + compute buffer + activations
	// KV cache at 8K ctx ≈ 500-1500MB depending on model, compute buffer ≈ 500-1000MB
	overheadMB := 2560 // 2.5GB: enough for 8K-32K ctx KV cache + compute buffer

	// Expert layers ≈ 75% of model size
	expertTotalMB := int(profile.Size_GB * 1024 * 0.75)
	perExpertLayerMB := expertTotalMB / profile.ExpertsTotal

	if perExpertLayerMB <= 0 {
		return "moe_offload", 0
	}

	// How many expert layers can fit in remaining VRAM after attention + overhead
	vramForExperts := vramMB - attentionMB - overheadMB
	if vramForExperts <= 0 {
		return "moe_offload", 0 // not even attention fits comfortably
	}

	gpuExpertLayers := vramForExperts / perExpertLayerMB
	if gpuExpertLayers >= profile.ExpertsTotal {
		// All experts fit → full_gpu (caller should have caught this, but safety check)
		return "full_gpu", 0
	}

	nCpuMoe := profile.ExpertsTotal - gpuExpertLayers
	if nCpuMoe >= profile.ExpertsTotal {
		return "moe_offload", 0 // all on CPU
	}

	return "moe_partial", nCpuMoe
}
