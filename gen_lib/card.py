"""
gen_lib/card.py — 把「图片 + 生成参数」合成一张配方卡 PNG。

用途：Gallery 大图里一键导出「图 + metadata」为单张图，直接发 Telegram 存档/分享。

设计要点
--------
- 纯服务端 Pillow 合成：不调外部 API、不花钱、1 秒内出图。
- **等宽字体**：鹿鹿有轻微老花眼，等宽字符辨识度更高（DejaVu Sans Mono）。
- ⚠️ DejaVu Sans Mono **不含中文字形**，而 ZIT 的 prompt 常是中文，且 Pillow
  **没有自动 font fallback** → 必须按字符切换字体（中日韩走 WQY Zen Hei）。
- 两种模式：
    full = Prompt + Negative + 参数行（可完整复现）
    slim = 只参数行（干净，当出处标注用）
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── 字体 ────────────────────────────────────────────────────────────────────
LATIN = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
LATIN_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
CJK = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"

# ── 配色（与 gallery 暗色主题一致）──────────────────────────────────────────
BG = (17, 17, 24)
TEXT = (228, 233, 240)
DIM = (150, 152, 160)
ACCENT = (140, 112, 255)
LABEL = (120, 122, 132)
RULE = (44, 44, 58)

PAD = 34
GAP = 22

_fcache: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in _fcache:
        _fcache[key] = ImageFont.truetype(LATIN_BOLD if bold else LATIN, size)
    return _fcache[key]


def _cjk(size: int) -> ImageFont.FreeTypeFont:
    key = (-size, True)  # 负数 key 避免与拉丁字体冲突
    if key not in _fcache:
        _fcache[key] = ImageFont.truetype(CJK, size, index=0)
    return _fcache[key]


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x2E80 <= o <= 0x9FFF) or (0xF900 <= o <= 0xFAFF) \
        or (0xFF00 <= o <= 0xFFEF) or (0x3000 <= o <= 0x303F)


def _fl(ch: str, size: int):
    """按字符挑字体：中日韩 → WQY，其余 → DejaVu Mono。"""
    return _cjk(size) if _is_cjk(ch) else _font(size)


def _w(text: str, size: int) -> float:
    return sum(_fl(c, size).getlength(c) for c in text)


def _wrap(text: str, size: int, max_w: float) -> list[str]:
    """按像素宽度折行；能断在空格就断空格，否则硬断（长 AIR / 长词）。"""
    out: list[str] = []
    for para in text.split("\n"):
        cur, cur_w = "", 0.0
        for ch in para:
            cw = _fl(ch, size).getlength(ch)
            if cur and cur_w + cw > max_w:
                sp = cur.rfind(" ")
                if sp > len(cur) * 0.55:
                    out.append(cur[:sp])
                    cur = cur[sp + 1:]
                    cur_w = _w(cur, size)
                else:
                    out.append(cur)
                    cur, cur_w = "", 0.0
            cur += ch
            cur_w += cw
        out.append(cur)
    return out


def _draw_line(d: ImageDraw.ImageDraw, x: float, y: float, text: str,
               size: int, fill) -> None:
    """逐字符绘制（不同字符可能用不同字体），x 按各字体真实宽度递进。"""
    cx = x
    for ch in text:
        f = _fl(ch, size)
        d.text((cx, y), ch, font=f, fill=fill)
        cx += f.getlength(ch)


def build_card(image_path: str | Path, *, prompt: str = "", params: str = "",
               negative: str = "", mode: str = "full",
               out_path: str | Path) -> Path:
    """合成配方卡并写入 out_path。返回 out_path。

    mode='full' → Prompt + Negative + 参数行
    mode='slim' → 只参数行
    """
    src = Image.open(image_path).convert("RGB")
    iw, ih = src.size

    W = max(iw + PAD * 2, 780)
    inner = W - PAD * 2

    # 参数行里去掉 Model: xxx（已经在标题里单独显示了），避免重复
    params_clean = params
    model_name = ""
    if params_clean:
        parts = [p.strip() for p in params_clean.split(",")]
        kept = []
        for p in parts:
            if p.startswith("Model: "):
                model_name = p[len("Model: "):]
            else:
                kept.append(p)
        params_clean = ", ".join(kept)

    size_line = f"{iw}×{ih}"

    body_size = 25 if mode == "slim" else 23
    title_size = 30
    label_size = 20

    canvas_h = ih + PAD * 2 + 2600  # 先开足高度，画完按实际用量裁掉
    card = Image.new("RGB", (W, canvas_h), BG)
    d = ImageDraw.Draw(card)

    # 1) 图片
    card.paste(src, (PAD, PAD))
    y = PAD + ih + GAP

    # 2) 分隔线
    d.line([(PAD, y), (W - PAD, y)], fill=RULE, width=2)
    y += GAP

    # 3) 标题：模型名（粗体）+ 尺寸（暗）
    if model_name:
        _draw_line(d, PAD, y, model_name, title_size, (255, 255, 255))
        mw = _w(model_name, title_size)
        _draw_line(d, PAD + mw + 14, y + 7, size_line, label_size, DIM)
        y += title_size + 16
    else:
        _draw_line(d, PAD, y, size_line, label_size, DIM)
        y += label_size + 16

    def block(label: str, body: str, body_color=TEXT) -> None:
        nonlocal y
        if not body.strip():
            return
        _draw_line(d, PAD, y, label, label_size, LABEL)
        y += label_size + 10
        for ln in _wrap(body, body_size, inner):
            _draw_line(d, PAD, y, ln, body_size, body_color)
            y += int(body_size * 1.42)
        y += 16

    if mode == "full":
        block("PROMPT", prompt)
        block("NEGATIVE", negative, DIM)
    block("PARAMETERS", params_clean, ACCENT if mode == "slim" else TEXT)

    # 4) 按实际内容裁掉多余空白
    y += PAD - GAP
    card = card.crop((0, 0, W, min(y, canvas_h)))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # ⚠️ 默认存 JPEG 而非 PNG：本机到 api.telegram.org 的上传只有 ~95~140 KB/s
    # （对比 httpbin 228 KB/s），1227KB 的 PNG 光上传就要 ~12s，而 371KB 的 JPEG
    # 只要 ~3.5s。q92 + subsampling=0 下文字与 PNG 肉眼无差别（实测确认）。
    if out_path.suffix.lower() in (".jpg", ".jpeg"):
        card.save(out_path, "JPEG", quality=92, subsampling=0, optimize=True)
    else:
        card.save(out_path, "PNG")
    return out_path
