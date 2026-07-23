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
    "sdxl-base": "sdxl-base",
    "SD XL Base": "sdxl-base",
    "civitai:101055@126613": "sdxl-base",
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
}


def _normalize_model(raw: str) -> str:
    """Normalize a model name to its canonical short key."""
    if not raw:
        return ""
    return MODEL_NORMALIZE.get(raw, raw)


def _conn() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH))
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
                offset: int = 0, limit: int = 50) -> list[dict]:
    """List images with optional filters. Returns [{filename, ...}, ...].
    
    video_only: None=all, True=video only, False=image only.
    """
    db = _conn()
    db.row_factory = sqlite3.Row

    conditions = ["archived = ?"]
    params: list = [int(archived)]

    if model_filter:
        conditions.append("model = ?")
        params.append(model_filter)

    if favorited_only:
        conditions.append("favorited = 1")
    
    if video_only is True:
        conditions.append("(model LIKE 'i2v-%' OR model = 'Wan 2.2 Video')")
    elif video_only is False:
        conditions.append("(model NOT LIKE 'i2v-%' AND model != 'Wan 2.2 Video')")

    where = " AND ".join(conditions)

    if search:
        # FTS5 search — join against images_fts for ranking
        fts_where = "images_fts MATCH ?"
        fts_params = [search]
        if model_filter:
            # model already filtered above, but FTS also indexes model — fine for double-filter
            pass
        query = f"""
            SELECT i.* FROM images i
            INNER JOIN images_fts fts ON i.rowid = fts.rowid
            WHERE {fts_where} AND {where}
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
                 favorited_only: bool = False, video_only: bool = None) -> int:
    """Count images matching filters.
    
    video_only: None=all, True=video only, False=image only.
    """
    db = _conn()

    conditions = ["archived = ?"]
    params: list = [int(archived)]

    if model_filter:
        conditions.append("model = ?")
        params.append(model_filter)

    if favorited_only:
        conditions.append("favorited = 1")
    
    if video_only is True:
        conditions.append("(model LIKE 'i2v-%' OR model = 'Wan 2.2 Video')")
    elif video_only is False:
        conditions.append("(model NOT LIKE 'i2v-%' AND model != 'Wan 2.2 Video')")

    where = " AND ".join(conditions)

    if search:
        query = f"""
            SELECT COUNT(*) FROM images i
            INNER JOIN images_fts fts ON i.rowid = fts.rowid
            WHERE images_fts MATCH ? AND {where}
        """
        row = db.execute(query, [search] + params).fetchone()
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
            meta = _parse_png(f) if f.suffix.lower() == ".png" else {}
            mtime = int(f.stat().st_mtime)
            db.execute("""
                INSERT OR REPLACE INTO images (filename, prompt, seed, model, params, favorited, archived, mtime)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
