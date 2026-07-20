"""
gen_lib/i2v_replicate.py — Replicate Wan 2.2 I2V Fast provider.

Model: wan-video/wan-2.2-i2v-fast
Price: $0.11/run (flat, 720p)
NSFW: disable_safety_checker=true bypasses moderation
"""
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from io import BytesIO

from gen_lib.common import get_key, OUTPUT_DIR

REPLICATE_API = "https://api.replicate.com/v1"
MODEL = "wan-video/wan-2.2-i2v-fast"

# ── Image to data URI (for API upload) ──────────────────────────────────────

def _image_to_data_uri(path: str, max_mb: int = 3) -> str:
    """Convert a local image to a base64 data URI, resizing if needed."""
    from PIL import Image
    import base64
    
    img = Image.open(path)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    
    # Resize large images to keep data URI under limit
    w, h = img.size
    max_dim = 1280
    if max(w, h) > max_dim:
        ratio = max_dim / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92, optimize=True)
    img.close()
    
    data = buf.getvalue()
    if len(data) > max_mb * 1024 * 1024:
        # Aggressive compression fallback
        buf2 = BytesIO()
        img2 = Image.open(path)
        if img2.mode in ("RGBA", "P"):
            img2 = img2.convert("RGB")
        img2.thumbnail((1024, 1024), Image.LANCZOS)
        img2.save(buf2, format="JPEG", quality=80, optimize=True)
        img2.close()
        data = buf2.getvalue()
    
    b64 = base64.b64encode(data).decode()
    return f"data:image/jpeg;base64,{b64}"


# ── Core ────────────────────────────────────────────────────────────────────

def generate(image_path: str, prompt: str, *,
             num_frames: int = 81,
             fps: int = 20,
             resolution: str = "720p",
             disable_safety_checker: bool = True,
             go_fast: bool = True) -> Path:
    """Generate video from image via Replicate Wan 2.2 I2V Fast.
    
    Returns path to the downloaded .mp4 file.
    """
    api_key = get_key("REPLICATE_API_TOKEN")
    
    # Convert local image to data URI for Replicate
    data_uri = _image_to_data_uri(image_path)
    
    input_payload = {
        "image": data_uri,
        "prompt": prompt,
        "num_frames": num_frames,
        "frames_per_second": fps,
        "resolution": resolution,
        "disable_safety_checker": disable_safety_checker,
        "go_fast": go_fast,
    }
    
    # ── Create prediction ────────────────────────────────────────────────
    create_payload = {
        "version": MODEL,
        "input": input_payload,
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    data = json.dumps(create_payload).encode()
    req = urllib.request.Request(
        f"{REPLICATE_API}/predictions",
        data=data, headers=headers, method="POST",
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            prediction = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"❌ Replicate API error {e.code}: {body[:500]}")
        sys.exit(1)
    
    pred_id = prediction.get("id", "")
    status = prediction.get("status", "")
    print(f"🎬 Replicate prediction {pred_id}: {status}")
    
    # ── Poll until complete ──────────────────────────────────────────────
    if status not in ("succeeded", "failed", "canceled"):
        max_wait = 600  # 10 minutes
        poll_interval = 5
        elapsed = 0
        
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            
            req = urllib.request.Request(
                f"{REPLICATE_API}/predictions/{pred_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    prediction = json.loads(resp.read())
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                print(f"❌ Replicate poll error {e.code}: {body[:300]}")
                sys.exit(1)
            
            status = prediction.get("status", "")
            if status in ("succeeded", "failed", "canceled"):
                break
            
            # Adjust poll interval based on progress
            logs = prediction.get("logs", "")
            if logs and "100%" in logs:
                poll_interval = 2
            
            # Progress indicator
            if elapsed % 30 < poll_interval:
                print(f"   ⏳ {pred_id}: {status} ({elapsed}s)")
    
    if status == "failed":
        error = prediction.get("error", "unknown")
        print(f"❌ Replicate prediction failed: {error}")
        sys.exit(1)
    elif status == "canceled":
        print("❌ Replicate prediction canceled")
        sys.exit(1)
    elif status != "succeeded":
        print(f"❌ Replicate prediction timed out after {elapsed}s")
        sys.exit(1)
    
    # ── Download video ───────────────────────────────────────────────────
    output = prediction.get("output")
    if not output:
        print("❌ No output URL in Replicate response")
        sys.exit(1)
    
    # Handle multiple outputs (some models return arrays)
    if isinstance(output, list):
        output = output[0]
    
    print(f"⬇️  Downloading video: {output[:80]}...")
    
    dl_req = urllib.request.Request(output, headers={"User-Agent": "gen-pipeline/2.0"})
    try:
        with urllib.request.urlopen(dl_req, timeout=120) as resp:
            video_data = resp.read()
    except urllib.error.HTTPError as e:
        print(f"❌ Download failed: HTTP {e.code}")
        sys.exit(1)
    
    # ── Save ─────────────────────────────────────────────────────────────
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    source_stem = Path(image_path).stem[:30]
    fname = f"i2v_{source_stem}_{ts}.mp4"
    out_path = OUTPUT_DIR / fname
    out_path.write_bytes(video_data)
    
    size_mb = len(video_data) / (1024 * 1024)
    print(f"✅ Saved: {out_path}  ({size_mb:.1f} MB)")
    
    return out_path
