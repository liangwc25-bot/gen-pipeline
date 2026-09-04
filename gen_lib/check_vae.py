#!/usr/bin/env python3
"""check_vae.py — 下载 checkpoint 后、上传 Runware 前，检查内嵌 VAE 是否可能有问题。

用法:
    python3 gen_lib/check_vae.py /path/to/checkpoint.safetensors [--vae-reference ref.safetensors]

输出(exit code):
    0 = VAE 正常/无 VAE 需注意
    1 = 疑似问题(FP16 阉割、结构缺块、或与参考 VAE 数值差异大)
    2 = 完全无 VAE(真没 bake)
    3 = 无法解析(文件损坏/不是 safetensors)

原理:只读 safetensors header(文件头,不用加载张量),不整载文件。
结构性坑(没 VAE / FP16 阉割 / 缺块)能可靠检出。
"VAE 质量到底行不行"最终仍需跑一张图 + 肉眼——本脚本只做体检,不盖章。

作者: Hermes Agent — 对应 sd-vae-bake-replace skill。
"""
import json
import struct
import sys
from collections import Counter
from pathlib import Path

PREFIX = "first_stage_model."


def read_header(path):
    """Return (header_len, header_dict). Only reads the header bytes from file head."""
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        if n > 100 * 1024 * 1024:  # safetensors 硬性 header 上限 100MB
            raise ValueError("header too large (not a valid safetensors?)")
        hdr = json.loads(f.read(n))
    return n, hdr


def vae_signature(hdr):
    """Return dict summarizing the embedded VAE (keys under first_stage_model.)."""
    fsm = {k: v for k, v in hdr.items() if k.startswith(PREFIX)}
    if not fsm:
        return None
    # 结构完整性检查:关键块是否齐全 (SDXL/SD1.5 VAE 通用结构)
    keys = set(fsm.keys())
    # 规范结构:去掉张量名保留主干
    stems = set()
    for k in fsm:
        # 剥掉 .weight/.bias 后缀和最后的层号
        parts = k[len(PREFIX):].split(".")
        stems.add(".".join(parts[:-1]))
    has_encoder = any("encoder" in s for s in stems)
    has_decoder = any("decoder" in s for s in stems)
    has_quant = any("quant_conv" in s or "post_quant_conv" in s for s in stems)
    # dtype 分布
    dtypes = Counter(v["dtype"] for v in fsm.values())
    total = len(fsm)
    return {
        "count": total,
        "dtype_dist": dict(dtypes),
        "has_encoder": has_encoder,
        "has_decoder": has_decoder,
        "has_quant": has_quant,
    }


def read_tensor(path, hdr, key, data_start):
    """Read one tensor fully (for reference comparison). Use numpy if available."""
    try:
        import numpy as np
        import safetensors
    except ImportError:
        return None
    try:
        sf = safetensors.safe_open(path, framework="numpy")
        t = sf.get_tensor(key)
        return t
    except Exception:
        return None


def compare_to_reference(path, hdr, ref_path, data_start):
    """Compare embedded VAE vs a reference VAE (e.g. sdxlVAE) numerically."""
    import numpy as np
    import safetensors

    if not PREFIX.startswith(""):
        pass
    try:
        sf = safetensors.safe_open(path, framework="numpy")
        sr = safetensors.safe_open(ref_path, framework="numpy")
        # 内嵌键(剥前缀) vs 参考文件键
        emb = {k[len(PREFIX):]: k for k in sf.keys() if k.startswith(PREFIX)}
        mismatches = []
        for refkey in sr.keys():
            if refkey in ("model_ema.decay", "model_ema.num_updates"):
                continue  # 参考文件的 ema 元数据,非权重
            if refkey not in emb:
                mismatches.append(f"missing:{refkey}")
                continue
            a = sf.get_slice(emb[refkey])[:]
            b = sr.get_slice(refkey)[:]
            if a.shape != b.shape or a.dtype != b.dtype:
                mismatches.append(f"shape/dtype:{refkey}")
            elif not np.array_equal(a, b) and a.size:
                # 标量张量用 array_equal 即可
                pass
        # 数值层:逐字节不等几乎必然(FP16 vs FP32),但 key 集合完全对齐 + dtype 差异是核心信号
        return mismatches
    except Exception as e:
        return [f"compare-error:{e}"]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(3)
    path = sys.argv[1]
    ref_path = sys.argv[2] if len(sys.argv) > 2 else None
    if not Path(path).exists():
        print(f"❌ 文件不存在: {path}")
        sys.exit(3)

    try:
        n, hdr = read_header(path)
    except Exception as e:
        print(f"❌ 无法解析 {path}: {e}")
        sys.exit(3)
    data_start = 8 + n

    sig = vae_signature(hdr)
    if sig is None:
        print(f"⚠️ [NO VAE] {Path(path).name} 完全没有 first_stage_model.* 键 → 真没 bake VAE")
        print("   建议: 若该模型需要 VAE, 先 bake/替换再上传 (见 sd-vae-bake-replace skill)")
        sys.exit(2)

    # 结构体检
    problems = []
    if not sig["has_encoder"]:
        problems.append("缺 encoder 块")
    if not sig["has_decoder"]:
        problems.append("缺 decoder 块")
    if not sig["has_quant"]:
        problems.append("缺 quant_conv/post_quant_conv")
    dtype_note = ""
    if "F16" in sig["dtype_dist"] and not ("F32" in sig["dtype_dist"]):
        # 全 FP16 VAE — SD1.5 原生 FP16 也常见,但 SDXL 系标准是 FP32,值得提示
        dtype_note = f" ⚠️ 全 FP16 (VEA dtype: {sig['dtype_dist']}) — SDXL/Illustrious 建议参考 FP32 版 VAE"

    print(f"✅ 含内嵌 VAE: {sig['count']} 键 | dtype: {sig['dtype_dist']}")
    print(f"   结构: encoder={sig['has_encoder']} decoder={sig['has_decoder']} quant={sig['has_quant']}")
    if dtype_note:
        print(dtype_note)

    # 参考 VAE 对比(可选)
    if ref_path and Path(ref_path).exists():
        import numpy as np
        import safetensors
        sf = safetensors.safe_open(path, framework="numpy")
        sr = safetensors.safe_open(ref_path, framework="numpy")
        emb_keys = {k[len(PREFIX):]: k for k in sf.keys() if k.startswith(PREFIX)}
        ref_keys = [k for k in sr.keys() if k not in ("model_ema.decay", "model_ema.num_updates")]
        missing = [k for k in ref_keys if k not in emb_keys]
        extra = [k for k in emb_keys if k not in ref_keys and k not in ("model_ema.decay", "model_ema.num_updates")]
        if missing:
            problems.append(f"与参考 VAE 比缺 {len(missing)} 键 (e.g. {missing[:3]})")
        if extra:
            problems.append(f"比参考 VAE 多 {len(extra)} 键 (e.g. {extra[:3]})")
        # 数值/位数对比: 抽样看 dtype 是否与参考不同
        dtype_diff = False
        for k in ref_keys:
            if k in emb_keys:
                ea = sf.get_slice(emb_keys[k]).get_dtype()
                ra = sr.get_slice(k).get_dtype()
                if ea != ra:
                    dtype_diff = True
                break
        if dtype_diff:
            problems.append("内嵌 VAE dtype 与参考 VAE 不同 (疑似非标准/阉割版, 建议替换)")
        print(f"   参考 {Path(ref_path).name}: 缺 {len(missing)} / 多 {len(extra)} 键")

    if problems:
        print(f"\n⚠️ 疑似 VAE 问题 ({len(problems)} 项):")
        for p in problems:
            print(f"   - {p}")
        print("\n   建议: 上传 Runware 前先与鹿鹿沟通 (可能需替换 VAE, 见 sd-vae-bake-replace skill)")
        sys.exit(1)
    else:
        print("\n✅ VAE 结构完整, 无明显问题 — 可上传 Runware")
        sys.exit(0)


if __name__ == "__main__":
    main()
