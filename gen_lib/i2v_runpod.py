"""
gen_lib/i2v_runpod.py — RunPod serverless Wan2.2 I2V provider.

Calls the `wan22-video` serverless endpoint (wlsdml1114/generate_video Hub worker),
which returns video as base64. Supports multiple LoRA pairs (up to 4).

LoRA handling: the worker loads LoRA files from /runpod-volume/loras/ by filename.
So before generating, each requested LoRA is ensured to exist on the network volume
(if given as an https:// URL, it is downloaded + uploaded once, cached by name).
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.request
import urllib.error
from pathlib import Path

from gen_lib.common import load_env, get_key

load_env()

ENDPOINT_ID = "ozrgkurs060xux"  # wan22-video
OUTPUT_DIR = Path(__file__).parent.parent / "output" / "images"

# Network volume LoRA dir (worker reads /runpod-volume/loras/) + S3 mapping
LORA_VOLUME_PREFIX = "loras/"          # key prefix on the volume
WORKER_LORA_DIR = "/runpod-volume/loras"


def _api_key() -> str:
    return get_key("RUNPOD_API_KEY")


def _post_runsync(payload: dict, timeout: int = 1800):
    """POST /runsync and return (elapsed_s, response_dict)."""
    req = urllib.request.Request(
        f"https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync",
        data=json.dumps({"input": payload}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {_api_key()}"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode())
    return time.time() - t0, resp


def _ensure_lora_on_volume(url: str) -> str:
    """Download a LoRA (https://...) and upload to network volume loras/, return filename.

    If url is already a bare filename, return it as-is (assumed present on volume).
    Uses the same S3 (boto3) credentials as rp_upload scripts.
    """
    if not url or not url.startswith("http"):
        return url or ""
    name = Path(url.split("?")[0]).name
    if not name.endswith((".safetensors", ".pt")):
        name = name + ".safetensors"

    # Check if already on volume (cheap HEAD via boto3)
    try:
        import boto3
        from botocore.config import Config
        # Credentials come from the project-root .env (loaded at module import via
        # load_env()): RUNPOD_S3_ENDPOINT / RUNPOD_S3_ACCESS_KEY / RUNPOD_S3_SECRET_KEY /
        # RUNPOD_NETVOL_ID / RUNPOD_S3_REGION. No external file lookups.
        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ["RUNPOD_S3_ENDPOINT"],
            aws_access_key_id=os.environ["RUNPOD_S3_ACCESS_KEY"],
            aws_secret_access_key=os.environ["RUNPOD_S3_SECRET_KEY"],
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                          retries={"max_attempts": 8, "mode": "standard"}),
            region_name=os.environ.get("RUNPOD_S3_REGION", "eu-ro-1"),
        )
        bucket = os.environ["RUNPOD_NETVOL_ID"]
        key = LORA_VOLUME_PREFIX + name
        try:
            s3.head_object(Bucket=bucket, Key=key)
            return name  # already present
        except Exception:
            pass
        # download to temp (use curl - R2/CF rejects bare Python UA), then upload via multipart
        import subprocess
        tmp = Path("/tmp") / name
        dl = subprocess.run(["curl", "-sL", "-o", str(tmp), url], capture_output=True)
        if dl.returncode != 0 or not tmp.exists():
            raise RuntimeError(f"curl download failed rc={dl.returncode}")
        # multipart upload (single put_object times out for large files on RunPod S3)
        sz = tmp.stat().st_size
        mpu = s3.create_multipart_upload(Bucket=bucket, Key=key)
        uid = mpu["UploadId"]
        CHUNK = 8 * 1024 * 1024
        parts, part_no = [], 1
        try:
            with open(tmp, "rb") as f:
                while True:
                    data = f.read(CHUNK)
                    if not data:
                        break
                    r = s3.upload_part(Bucket=bucket, Key=key, UploadId=uid,
                                       PartNumber=part_no, Body=data)
                    parts.append({"PartNumber": part_no, "ETag": r["ETag"]})
                    part_no += 1
            s3.complete_multipart_upload(Bucket=bucket, Key=key, UploadId=uid,
                MultipartUpload={"Parts": parts})
        except Exception:
            try: s3.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=uid)
            except Exception: pass
            raise
        tmp.unlink(missing_ok=True)
        return name
    except Exception as e:
        raise RuntimeError(f"Failed to stage LoRA {url} on network volume: {e}")


def generate(image_path: str, prompt: str, *,
             width: int = 768,
             height: int = 1024,
             length: int = 81,
             steps: int = 10,
             seed: int = 0,
             cfg: float = 3.0,
             lora_pairs: list = None) -> Path:
    """Generate video via RunPod wan22-video endpoint. Returns path to .mp4.

    Args:
        image_path: local source image
        prompt: motion description
        lora_pairs: list of dicts, each {high, low, high_scale, low_scale}
            where high/low are HF URLs or volume filenames (up to 4 pairs).
        Returns path to downloaded .mp4.
    """
    img_b64 = base64.b64encode(open(image_path, "rb").read()).decode()

    # Build worker lora_pairs. Each pair: high/low are worker-visible filenames.
    pairs = []
    for pr in (lora_pairs or []):
        high_url = pr.get("high") or ""
        low_url = pr.get("low") or ""
        if not high_url and not low_url:
            continue
        high_name = _ensure_lora_on_volume(high_url) if high_url else None
        low_name = _ensure_lora_on_volume(low_url) if low_url else None
        pair = {}
        if high_name:
            pair["high"] = high_name
            pair["high_weight"] = float(pr.get("high_scale", 1.0))
        if low_name:
            pair["low"] = low_name
            pair["low_weight"] = float(pr.get("low_scale", 1.0))
        pairs.append(pair)

    payload = {
        "image_base64": img_b64,
        "prompt": prompt,
        "width": int(width),
        "height": int(height),
        "length": int(length),
        "steps": int(steps),
        "seed": int(seed),
        "cfg": float(cfg),
    }
    if pairs:
        payload["lora_pairs"] = pairs

    print(f"[i2v_runpod] submitting to {ENDPOINT_ID} "
          f"({width}x{height} len={length} steps={steps} loras={len(pairs)})", flush=True)
    elapsed, resp = _post_runsync(payload)

    if resp.get("status") != "COMPLETED":
        err = resp.get("error") or resp.get("output") or resp
        raise RuntimeError(f"RunPod job failed after {elapsed:.0f}s: {str(err)}")

    out = resp.get("output") or {}
    video_b64 = out.get("video", "")
    if not video_b64:
        raise RuntimeError("RunPod job completed but no video in output")

    raw = base64.b64decode(video_b64)
    ts = time.strftime("%Y%m%d_%H%M%S")
    source_stem = Path(image_path).stem
    fname = f"i2v_runpod_{source_stem}_{width}x{height}_{length}f_{ts}.mp4"
    out_path = OUTPUT_DIR / fname
    out_path.write_bytes(raw)
    print(f"[i2v_runpod] saved {out_path} ({len(raw)/1024:.0f} KB, "
          f"exec {elapsed:.0f}s)", flush=True)
    return out_path
