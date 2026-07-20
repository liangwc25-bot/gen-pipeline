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
        "price": "$0.11/run",
        "supports_lora": False,
        "params": {
            "num_frames": 81,
            "fps": 20,
            "resolution": "720p",
            "disable_safety_checker": True,
            "go_fast": True,
        },
    },
    # Future:
    # "atlas-wan": {
    #     "name": "Atlas Cloud Wan Turbo Spicy",
    #     "price": "$0.026/run",
    #     "supports_lora": True,
    #     "params": {"num_frames": 81, "fps": 20, "resolution": "720p"},
    # },
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
        )

    raise ValueError(f"Provider {provider} not implemented")
