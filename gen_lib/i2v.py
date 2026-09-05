"""
gen_lib/i2v.py — Image-to-Video pipeline dispatcher.

Multi-provider I2V pipeline following the same pattern as gen_lib/runware.py.
Each provider module handles its own API, pricing, and parameter space.
"""
from pathlib import Path
from gen_lib.common import load_env

load_env()

I2V_PROVIDERS = {
    "replicate-wan": {
        "name": "Replicate Wan 2.2 I2V Fast",
        "price": "$0.11/run (81-121帧 flat)",
        "supports_lora": True,
        "params": {
            "num_frames": 121,
            "fps": 24,
            "resolution": "480p",
            "disable_safety_checker": True,
            "go_fast": True,
        },
    },
    "runpod-wan": {
        "name": "RunPod Wan 2.2 I2V",
        "price": "~$0.10-0.14/run (GPU按量)",
        "supports_lora": True,
        "params": {
            "width": 768,
            "height": 1024,
            "length": 81,
            "steps": 10,
            "cfg": 3.0,
        },
    },
}

OUTPUT_DIR = Path(__file__).parent.parent / "output" / "images"


def generate_i2v(provider: str, image_path: str, prompt: str, **overrides) -> Path:
    """Generate a video from an image.
    
    Args:
        provider: Provider key (e.g. "replicate-wan")
        image_path: Absolute path to the source image
        prompt: Motion description in English
        **overrides: Provider-specific overrides (num_frames, fps, resolution, etc.)
    
    Returns:
        Path to the generated .mp4 file
    """
    if provider not in I2V_PROVIDERS:
        raise ValueError(f"Unknown I2V provider: {provider}")

    prov_cfg = I2V_PROVIDERS[provider]
    params = dict(prov_cfg["params"])
    params.update(overrides)

    if provider == "replicate-wan":
        from gen_lib.i2v_replicate import generate as _gen_replicate
        return _gen_replicate(
            image_path=image_path,
            prompt=prompt,
            num_frames=params["num_frames"],
            fps=params["fps"],
            resolution=params["resolution"],
            disable_safety_checker=params["disable_safety_checker"],
            go_fast=params["go_fast"],
            lora_url=overrides.get("lora_url"),
            lora_scale=overrides.get("lora_scale", 1.0),
            lora_url_2=overrides.get("lora_url_2"),
            lora_scale_2=overrides.get("lora_scale_2", 1.0),
        )

    if provider == "runpod-wan":
        from gen_lib.i2v_runpod import generate as _gen_runpod
        lora_pairs = overrides.get("lora_pairs")
        if lora_pairs is None:
            # legacy single-lora form
            lora_pairs = []
            if overrides.get("lora_url"):
                lora_pairs.append({"high": overrides["lora_url"], "low": None,
                                   "high_scale": overrides.get("lora_scale", 1.0)})
            if overrides.get("lora_url_2"):
                lora_pairs.append({"high": overrides["lora_url_2"], "low": None,
                                   "high_scale": overrides.get("lora_scale_2", 1.0)})
            if overrides.get("lora_url_3"):
                lora_pairs.append({"high": overrides["lora_url_3"], "low": None,
                                   "high_scale": overrides.get("lora_scale_3", 1.0)})
        return _gen_runpod(
            image_path=image_path,
            prompt=prompt,
            width=params["width"],
            height=params["height"],
            length=params["length"],
            steps=params["steps"],
            cfg=params["cfg"],
            seed=overrides.get("seed", 0),
            lora_pairs=lora_pairs,
        )

    raise ValueError(f"Provider {provider} not implemented")
