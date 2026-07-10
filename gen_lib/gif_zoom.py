#!/usr/bin/env python3
"""gif_zoom.py — Ken Burns breathing GIF from a single image.

Takes a high-res image, generates subtle zoom/pan frames, outputs a GIF.
No model calls, just PIL + FFmpeg palette optimised GIF.
"""

import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


def make_gif(
    input_path: Path,
    output_path: Path,
    *,
    zoom_factor: float = 0.04,      # total zoom range (0.04 = ±2% from centre)
    pan_x: int = 4,                  # max horizontal sway in px
    pan_y: int = 3,                  # max vertical sway in px
    fps: int = 12,                   # frames per second
    cycle_s: float = 2.0,            # seconds per full cycle
    cycles: int = 1,                 # number of cycles
    loop: int = 0,                   # 0 = infinite loop
) -> Path:
    """Create a subtle breathing/swaying Ken Burns GIF from a single image."""
    img = Image.open(input_path).convert("RGBA")
    w, h = img.size
    cx, cy = w / 2.0, h / 2.0

    total_frames = max(4, int(fps * cycle_s * cycles))
    phase_steps = fps * cycle_s  # frames per full 2π cycle

    # Use temp dir for intermediate PNG frames
    with tempfile.TemporaryDirectory(prefix="gif_zoom_") as tmpdir:
        tmp = Path(tmpdir)

        for i in range(total_frames):
            t = i / phase_steps  # cycles 0..1 per cycle
            angle = 2.0 * math.pi * t

            # Smooth sine-based zoom: zoom=1 oscillates between ±zoom_factor/2
            zoom = 1.0 + (zoom_factor / 2.0) * math.sin(angle)

            # Sway: gentle phase-shifted sine for each axis
            sway_x = int(pan_x * math.sin(angle + math.pi * 0.25)) if pan_x else 0
            sway_y = int(pan_y * math.sin(angle + math.pi * 0.75)) if pan_y else 0

            # Source crop: zoom > 1 → crop in; zoom < 1 → pad
            crop_w = int(w / zoom)
            crop_h = int(h / zoom)

            # Clamp to valid size
            crop_w = max(1, min(crop_w, w))
            crop_h = max(1, min(crop_h, h))

            left = int(cx - crop_w / 2.0 + sway_x)
            top = int(cy - crop_h / 2.0 + sway_y)

            # Ensure crop rect is within image bounds
            left = max(0, min(left, w - crop_w))
            top = max(0, min(top, h - crop_h))

            frame = img.crop((left, top, left + crop_w, top + crop_h))
            frame = frame.resize((w, h), Image.Resampling.LANCZOS)
            frame = frame.convert("RGB")  # GIF doesn't support RGBA well
            frame.save(tmp / f"f{i:04d}.png")

        # FFmpeg palette-optimised GIF (best quality for GIF format)
        palette_path = tmp / "palette.png"
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(tmp / "f%04d.png"),
             "-vf", "split[s0][s1];[s0]palettegen=max_colors=256:stats_mode=diff[s0];"
                     "[s1][s0]paletteuse=dither=bayer:bayer_scale=5",
             "-loop", str(loop), str(output_path)],
            capture_output=True, text=True, timeout=60, check=True,
        )

    return output_path
