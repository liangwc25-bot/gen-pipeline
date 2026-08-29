#!/usr/bin/env python3
"""Metadata index for gallery images — SQLite + FTS5.

Replaces directory-based archive and JSON-based favorites with a single DB.
FTS5 enables millisecond full-text search across thousands of images.
"""

import sqlite3
import os
import time
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "output" / "metadata.db"

# Normalize historical model names to consistent short keys
MODEL_NORMALIZE = {
    "flux-dev": "flux-dev",
    "FLUX.1-dev": "flux-dev",
    "FLUX.1-dev (runware:101@1)": "flux-dev",
    "Runware FLUX.1-dev (runware:101@1)": "flux-dev",
    "black-forest-labs/flux-dev": "flux-dev",
    "Fluxedup NSFW": "flux-uncensored",
    "FLUX Uncensored": "flux-uncensored",
    "FLUX (社区verified)": "flux-uncensored",
    "UltraReal Fine-Tune v4": "flux-uncensored",
    "UltraReal Fine-Tune FP8": "flux-uncensored",
    "Replicate FLUX.1-dev NSFW": "flux-uncensored",
    "pony-xl": "pony-xl",
    "Pony Diffusion": "pony-xl",
    "Prefect Pony XL v3": "pony-xl",
    "liangwc:3@1": "pony-xl",
    "prefect-ill-xl": "prefect-ill-xl",
    "Illustrious (Hassaku XL)": "prefect-ill-xl",
    "Prefect Illustrious XL v8": "prefect-ill-xl",
    "liangwc:6@1": "prefect-ill-xl",
    "guofeng4-xl": "guofeng4-xl",
    "国风4 GuoFeng4 XL": "guofeng4-xl",
    "liangwc:guofeng4-xl@1": "guofeng4-xl",
    "pornmaster": "pornmaster",
    "PornMaster-色情大师": "pornmaster",
    "liangwc:pornmaster@1": "pornmaster",
    "lustify": "lustify",
    "LUSTIFY SDXL": "lustify",
    "hassakuxl:573152@2155386": "lustify",
    "sdxl-vanilla": "sdxl-vanilla",
    "SDXL Vanilla 1.0": "sdxl-vanilla",
    "liangwc:sdxl-vanilla@1": "sdxl-vanilla",
    "dreamshaper-xl": "dreamshaper-xl",
    "DreamShaper XL": "dreamshaper-xl",
    "civitai:112902@121931": "dreamshaper-xl",
    "juggernaut-xl": "juggernaut-xl",
    "JuggernautXL V8": "juggernaut-xl",
    "rundiffusion:133005@288982": "juggernaut-xl",
    "Qwen-Image-Edit": "qwen-edit",
    "SDXL": "sdxl",
    "gif-zoom": "gif-zoom",
    "i2v-replicate-wan": "Wan 2.2 Video",
    "Test": "test",
    # ── SD1.5 checkpoint 显示名 → `*-15` key（2026-08-17）──
    # 之前 DB 存的是显示名，`model LIKE '%-15'` 筛选命中 0。归一化后 SD1.5 快速筛选可用。
    "DreamShaper 1.5": "dreamshaper-15",
    "majicMIX realistic 麦橘写实": "majicmix-real-15",
    "RealCartoon3D": "realcartoon3d-15",
    "AniVerse": "aniverse-15",
    "ChikMix": "chikmix-15",
    "RealCartoon-Realistic": "realcartoon-real-15",
    "Perfect World 完美世界": "perfect-world-15",
    "majicMIX lux 麦橘辉耀": "majicmix-lux-15",
    "Dark Sushi 2.5D 大颗寿司2.5D": "dark-sushi-25d-15",
    "国风武侠 Chosen Chinese": "guofeng-wuxia-15",
    "TastyRice-CG国风MIX": "tastyrice-cg-15",
    "OnlyRealistic 《唯》超高清真人写实": "onlyrealistic-15",
    "ChilloutMix": "chilloutmix-15",
    "chosen-mix": "chosen-mix-15",
    "AbyssOrangeMix2 NSFW": "abyss-orange-mix-15",
    "AbyssOrangeMix3 AOM3": "aom3-15",
    "万象熔炉 Anything XL": "wanxiang-anything-15",
    "LazyMix+ Real Amateur Nudes": "lazymix-15",
    "AbyssOrangeMix2 Hardcore": "aom2-hardcore-15",
    "Dark Sushi Mix 大颗寿司": "dark-sushi-mix-15",
    "Realisian": "realisian-15",
    "AnyHentai": "anyhentai-15",
    "majicMIX sombre 麦橘唯美": "majicmix-sombre-15",
    "RealCartoon-Anime": "realcartoon-anime-15",
    "Fantexi v0.9Beta": "fantexi-15",
    "OrangeChillMix": "orangechillmix-15",
    "CamelliaMix 2.5D": "camelliamix-15",
    "AstrAnime": "astranime-15",
    "Kawaii Realistic Anime Mix": "kawaii-anime-mix-15",
    "Kakarot 2.8D": "kakarot-28d-15",
    "majicMIX reverie 麦橘梦幻": "majicmix-reverie-15",
    "majicMIX horror 麦橘恐怖": "majicmix-horror-15",
    # ── Z-Image 显示名 → key（2026-08-17，同 SD1.5 问题）──
    "Alibaba Z-Image-Turbo": "zimage-alibaba",
    "Moody Pro Mix (Z-Image)": "zimage-moody",
    "Z Image Ultimate NSFW Unlock Turbo v2.0": "zimage-ultimate-nsfw",
    "Z-ImageTurbo VISIONARY NSFW (ZIT-fp8)": "zimage-visionary-nsfw",
    "Z-Image-Turbo Anime V2 Fp8": "zimage-turbo-anime",
    "Zimage Turbo by Stable Yogi (2603 Fp8)": "zimage-stable-yogi",
    "Komposto ZIT_ANI (fp8)": "zimage-komposto-ani",
    "TinZIT-ANIME-FP8 4steps 完全二次元": "zimage-tinzit-anime",
    "z_animimage_turbo_by_Lau (semi-real bf16)": "zimage-lau-anime",
    "PornMaster 色情大师 Z-Image (Turbo V3.5 BF16)": "zimage-pornmaster-v35",
    "Dark Beast 黑兽3.0 (ZIT)": "persona-zit",  # key 不以 zimage- 开头，筛选需加 OR
    "TwinFlow Z-Image-Turbo": "zimage-twinflow",
}


def _normalize_model(raw: str) -> str:
    """Normalize a model name to its canonical short key."""
    if not raw:
        return ""
    return MODEL_NORMALIZE.get(raw, raw)


# ── Gallery model filter: category-based (not exact single key) ──
# Many checkpoints share a base but store different model keys (e.g. all the
# `*-pony` / `*-ill` variants). Filtering by one exact key like 'pony-xl'
# silently drops those. We match by base category via model name patterns.
# 'sd15' / 'zit' kept as-is (they already catch their whole family).
def _model_filter_sql(f):
    """Return the WHERE condition for a model category filter."""
    if f == "sd15":
        return "model LIKE '%-15'"
    if f == "zit":
        return "(model LIKE 'zimage-%' OR model LIKE '%-zit')"
    if f == "pony":
        return "(LOWER(model) LIKE '%pony%')"
    if f == "illustrious":
        return ("(LOWER(model) LIKE '%-ill' OR LOWER(model) LIKE '%ill-xl' "
                "OR LOWER(model) LIKE '%illustrious%' OR LOWER(model) LIKE '%-noob' "
                "OR LOWER(model) LIKE '%noobai%')")
    if f == "flux":
        return "(LOWER(model) LIKE '%flux%')"
    return ""  # unknown/empty → no filter


def _model_filter_params(f):
    """Return the bound params for a model category filter (none for pattern-only)."""
    return []


def _conn() -> sqlite3.Connection:
    # timeout=10: during a rescan backfill still holds short write-lock windows
    # (~1-3s per 50-row batch). 5s was too tight and favorites occasionally
    # timed out with "database is locked" (2026-08-09). 10s = wait, never fail.
    db = sqlite3.connect(str(DB_PATH), timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    return db


def init_db() -> None:
    """Create tables if they don't exist."""
    db = _conn()
    db.execute("""
        CREATE TABLE IF NOT EXISTS images (
            filename   TEXT PRIMARY KEY,
            prompt     TEXT NOT NULL DEFAULT '',
            seed       TEXT NOT NULL DEFAULT '',
            model      TEXT NOT NULL DEFAULT '',
            params     TEXT NOT NULL DEFAULT '',
            favorited  INTEGER NOT NULL DEFAULT 0,
            archived   INTEGER NOT NULL DEFAULT 0,
            mtime      INTEGER NOT NULL DEFAULT 0
        )
    """)
    # Indexes for fast filtering
    db.execute("CREATE INDEX IF NOT EXISTS idx_favorited ON images(favorited)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_archived ON images(archived)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_mtime ON images(mtime DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_model ON images(model)")
    # FTS5 content-sync table — stays in sync with images automatically
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS images_fts USING fts5(
            prompt, model, content='images', content_rowid='rowid'
        )
    """)
    # Triggers to keep FTS in sync
    db.executescript("""
        CREATE TRIGGER IF NOT EXISTS images_ai AFTER INSERT ON images BEGIN
            INSERT INTO images_fts(rowid, prompt, model) VALUES (new.rowid, new.prompt, new.model);
        END;
        CREATE TRIGGER IF NOT EXISTS images_ad AFTER DELETE ON images BEGIN
            INSERT INTO images_fts(images_fts, rowid, prompt, model) VALUES ('delete', old.rowid, old.prompt, old.model);
        END;
        CREATE TRIGGER IF NOT EXISTS images_au AFTER UPDATE ON images BEGIN
            INSERT INTO images_fts(images_fts, rowid, prompt, model) VALUES ('delete', old.rowid, old.prompt, old.model);
            INSERT INTO images_fts(rowid, prompt, model) VALUES (new.rowid, new.prompt, new.model);
        END;
    """)
    db.commit()
    db.close()


def insert(filename: str, prompt: str = "", seed: str = "", model: str = "",
           params: str = "", mtime: int = 0) -> None:
    """Insert or replace a metadata row. Called after each generation."""
    model = _normalize_model(model)
    db = _conn()
    db.execute("""
        INSERT OR REPLACE INTO images (filename, prompt, seed, model, params, mtime)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (filename, prompt, seed, model, params, mtime))
    db.commit()
    db.close()


def set_favorited(filename: str, state: bool) -> None:
    db = _conn()
    db.execute("UPDATE images SET favorited = ? WHERE filename = ?", (int(state), filename))
    db.commit()
    db.close()


def set_archived(filename: str, state: bool) -> None:
    db = _conn()
    db.execute("UPDATE images SET archived = ? WHERE filename = ?", (int(state), filename))
    db.commit()
    db.close()


def is_favorited(filename: str) -> bool:
    db = _conn()
    row = db.execute("SELECT favorited FROM images WHERE filename = ?", (filename,)).fetchone()
    db.close()
    return bool(row and row[0])


def is_archived(filename: str) -> bool:
    db = _conn()
    row = db.execute("SELECT archived FROM images WHERE filename = ?", (filename,)).fetchone()
    db.close()
    return bool(row and row[0])


def list_images(model_filter: str = "", search: str = "", archived: bool = False,
                favorited_only: bool = False, video_only: bool = None,
                time_filter: str = "", offset: int = 0, limit: int = 50) -> list[dict]:
    """List images with optional filters. Returns [{filename, ...}, ...].
    
    video_only: None=all, True=video only, False=image only.
    time_filter: 'today' (since midnight UTC), 'week' (last 7 days), '' (all).
    model_filter: exact key, or 'sd15' (all *-15), 'zit' (all zimage-*).
    """
    db = _conn()
    db.row_factory = sqlite3.Row

    conditions = []
    params: list = []
    if not favorited_only:
        # Fav view shows ALL favorites including archived ones —
        # favorite + archive can coexist (2026-08-09)
        conditions.append("archived = ?")
        params.append(int(archived))

    if model_filter:
        _fc = _model_filter_sql(model_filter)
        if _fc:
            conditions.append(_fc)
            params.extend(_model_filter_params(model_filter))

    if favorited_only:
        conditions.append("favorited = 1")
    
    if video_only is True:
        conditions.append("(model LIKE 'i2v-%' OR model = 'Wan 2.2 Video')")
    elif video_only is False:
        conditions.append("(model NOT LIKE 'i2v-%' AND model != 'Wan 2.2 Video')")

    if time_filter == "today":
        conditions.append("mtime >= unixepoch('now', 'start of day')")
    elif time_filter == "week":
        conditions.append("mtime >= unixepoch('now', '-7 days')")

    where = " AND ".join(conditions)

    if search:
        # FTS5 search — add * prefix match unless user already has FTS5 syntax
        fts_query = search if any(c in search for c in '*"()') else f"{search}*"
        fts_where = "images_fts MATCH ?"
        fts_params = [fts_query]
        # In FTS join path, qualify model references with table alias 'i'
        where_qualified = where.replace("model ", "i.model ").replace("model)", "i.model)")
        query = f"""
            SELECT i.* FROM images i
            INNER JOIN images_fts fts ON i.rowid = fts.rowid
            WHERE {fts_where} AND {where_qualified}
            ORDER BY rank
            LIMIT ? OFFSET ?
        """
        params_full = fts_params + params + [limit, offset]
    else:
        query = f"""
            SELECT * FROM images
            WHERE {where}
            ORDER BY mtime DESC
            LIMIT ? OFFSET ?
        """
        params_full = params + [limit, offset]

    rows = db.execute(query, params_full).fetchall()
    db.close()
    return [dict(r) for r in rows]


def count_images(model_filter: str = "", search: str = "", archived: bool = False,
                 favorited_only: bool = False, video_only: bool = None,
                 time_filter: str = "") -> int:
    """Count images matching filters.
    
    video_only: None=all, True=video only, False=image only.
    time_filter: 'today' (since midnight UTC), 'week' (last 7 days), '' (all).
    model_filter: exact key, or 'sd15' (all *-15), 'zit' (all zimage-*).
    """
    db = _conn()

    conditions = []
    params: list = []
    if not favorited_only:
        # Same coexistence rule as list_images (2026-08-09)
        conditions.append("archived = ?")
        params.append(int(archived))

    if model_filter:
        _fc = _model_filter_sql(model_filter)
        if _fc:
            conditions.append(_fc)
            params.extend(_model_filter_params(model_filter))

    if favorited_only:
        conditions.append("favorited = 1")
    
    if video_only is True:
        conditions.append("(model LIKE 'i2v-%' OR model = 'Wan 2.2 Video')")
    elif video_only is False:
        conditions.append("(model NOT LIKE 'i2v-%' AND model != 'Wan 2.2 Video')")

    if time_filter == "today":
        conditions.append("mtime >= unixepoch('now', 'start of day')")
    elif time_filter == "week":
        conditions.append("mtime >= unixepoch('now', '-7 days')")

    where = " AND ".join(conditions)

    if search:
        fts_query = search if any(c in search for c in '*"()') else f"{search}*"
        where_qualified = where.replace("model ", "i.model ").replace("model)", "i.model)")
        query = f"""
            SELECT COUNT(*) FROM images i
            INNER JOIN images_fts fts ON i.rowid = fts.rowid
            WHERE images_fts MATCH ? AND {where_qualified}
        """
        row = db.execute(query, [fts_query] + params).fetchone()
    else:
        query = f"SELECT COUNT(*) FROM images WHERE {where}"
        row = db.execute(query, params).fetchone()

    db.close()
    return row[0] if row else 0


def distinct_models() -> list[str]:
    """Return all distinct model names in the DB."""
    db = _conn()
    rows = db.execute("SELECT DISTINCT model FROM images WHERE model != '' ORDER BY model").fetchall()
    db.close()
    return [r[0] for r in rows]


def get_meta(filename: str) -> dict | None:
    """Get metadata for a single file."""
    db = _conn()
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM images WHERE filename = ?", (filename,)).fetchone()
    db.close()
    return dict(row) if row else None


def delete_record(filename: str) -> None:
    """Remove a record (e.g., when file is trashed)."""
    db = _conn()
    db.execute("DELETE FROM images WHERE filename = ?", (filename,))
    db.commit()
    db.close()


def backfill(image_dir: Path, archive_dir: Path | None = None) -> int:
    """Scan existing images and populate the DB from PNG metadata.
    Also migrates favorites from the old JSON file.
    Returns number of images indexed.
    """
    from PIL import Image

    # Import favorites from old JSON
    favs = set()
    fav_file = Path.home() / ".hermes" / "gallery_favorites.json"
    if fav_file.exists():
        try:
            import json as _json
            data = _json.loads(fav_file.read_text())
            if isinstance(data, list):
                favs = set(data)
        except Exception:
            pass

    db = _conn()
    indexed = 0

    def _parse_png(filepath: Path) -> dict:
        """Extract metadata from PNG text chunks."""
        meta = {"prompt": "", "seed": "", "model": "", "params": ""}
        try:
            img = Image.open(filepath)
            raw = img.text if hasattr(img, 'text') else {}
            img.close()

            # Look for AUTOMATIC1111-style "parameters" or raw text
            for key in ("parameters", "prompt", "Description"):
                if key in raw:
                    text = raw[key]
                    meta["prompt"] = text.split("\n")[0].strip()
                    # Try seed
                    for line in text.split("\n"):
                        if line.strip().startswith("Seed: "):
                            meta["seed"] = line.strip()[6:]
                        if "Model:" in line:
                            meta["model"] = line.split("Model:", 1)[1].strip().split(",")[0].strip()
                    break
        except Exception:
            pass
        return meta

    dirs = [image_dir]
    if archive_dir and archive_dir.exists():
        dirs.append(archive_dir)

    for d in dirs:
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                continue
            try:
                meta = _parse_png(f) if f.suffix.lower() == ".png" else {}
                mtime = int(f.stat().st_mtime)
            except FileNotFoundError:
                continue  # file moved/trashed by another thread
            db.execute("""
                INSERT INTO images (filename, prompt, seed, model, params, favorited, archived, mtime)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(filename) DO UPDATE SET
                    prompt = excluded.prompt,
                    seed = excluded.seed,
                    model = excluded.model,
                    params = excluded.params,
                    mtime = excluded.mtime
            """, (
                f.name,
                meta.get("prompt", ""),
                meta.get("seed", ""),
                _normalize_model(meta.get("model", "")),
                meta.get("params", ""),
                1 if f.name in favs else 0,
                1 if archive_dir and d == archive_dir else 0,
                mtime,
            ))
            indexed += 1
            # Commit in batches — a single giant transaction would hold the
            # write lock for 30-60s and block favorites/archive/trash (2026-08-09)
            # 50 rows keeps the lock window ~1-2s, safely under busy_timeout=5s
            if indexed % 50 == 0:
                db.commit()

    db.commit()
    # Clean up ghost entries: remove DB records for files no longer on disk
    # Batch the DELETE too — a single huge NOT IN + FTS sync can hold the
    # write lock 5s+ and still block favorites during rescan (2026-08-09)
    if not archive_dir:
        all_disk = {f.name for f in image_dir.iterdir() if f.is_file()}
        if all_disk:
            placeholders = ",".join("?" for _ in all_disk)
            ghosts = [r[0] for r in db.execute(
                "SELECT filename FROM images WHERE archived = 0 AND filename NOT IN ({})".format(placeholders),
                list(all_disk)).fetchall()]
            for i in range(0, len(ghosts), 100):
                batch = ghosts[i:i + 100]
                db.execute("DELETE FROM images WHERE filename IN ({})".format(
                    ",".join("?" for _ in batch)), batch)
                db.commit()
        else:
            db.execute("DELETE FROM images WHERE archived = 0")
            db.commit()
    db.close()
    return indexed


def normalize_existing() -> int:
    """Normalize model names in existing records."""
    db = _conn()
    updated = 0
    for raw, normalized in MODEL_NORMALIZE.items():
        if raw == normalized:
            continue
        cur = db.execute("UPDATE images SET model = ? WHERE model = ?", (normalized, raw))
        updated += cur.rowcount
    db.commit()
    db.close()
    return updated
