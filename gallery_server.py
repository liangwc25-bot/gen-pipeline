#!/usr/bin/env python3
"""Gallery server — serves image gallery with SQLite metadata index."""
import json
import os
import io
import subprocess
import math
import shutil
import time
import urllib.parse
import threading
import uuid
from collections import OrderedDict
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
from pathlib import Path
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from gen_lib.metadata_db import (
    init_db, list_images, count_images, distinct_models,
    set_favorited, set_archived, is_favorited, is_archived,
    get_meta, delete_record, insert,
)
IMAGES_DIR = Path(__file__).parent / "output" / "images"
THUMB_DIR = Path(__file__).parent / "output" / ".thumbnails"
TRASH_DIR = Path(__file__).parent / "output" / ".trash"
PORT = 8089
THUMB_SIZE = (300, 300)

# Async job tracking (for long-running operations like I2V)
JOBS = OrderedDict()
MAX_JOBS = 50

def _trim_jobs():
    """Remove oldest completed jobs when over MAX_JOBS."""
    while len(JOBS) > MAX_JOBS:
        for jid, job in list(JOBS.items()):
            if job.get("status") == "done":
                JOBS.pop(jid)
                break
        else:
            break

# Ensure DB exists
init_db()
# ── Utility ──
def _find_file(filename: str) -> Path | None:
    """Find an image file in IMAGES_DIR."""
    fp = IMAGES_DIR / filename
    return fp if fp.exists() else None
def toggle_favorite(filename: str) -> bool:
    """Toggle favorite. Returns new state."""
    current = is_favorited(filename)
    new_state = not current
    set_favorited(filename, new_state)
    return new_state
def toggle_archive(filename: str) -> dict | None:
    """Toggle archive flag in DB (no file moving)."""
    current = is_archived(filename)
    new_state = not current
    set_archived(filename, new_state)
    return {"archived": new_state, "filename": filename}
def move_to_trash(filename: str) -> dict | None:
    """Move file to trash + delete DB record."""
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    fp = IMAGES_DIR / filename
    if fp.exists():
        shutil.move(str(fp), str(TRASH_DIR / filename))
        delete_record(filename)
        _cleanup_old_trash()
        return {"trashed": True, "filename": filename}
    return None
def _cleanup_old_trash() -> None:
    """Delete trash files older than 7 days."""
    now = time.time()
    week = 7 * 86400
    if not TRASH_DIR.exists():
        return
    for f in list(TRASH_DIR.iterdir()):
        if f.is_file() and (now - f.stat().st_mtime) > week:
            try:
                f.unlink()
            except OSError:
                pass
def make_thumbnail(filepath: Path) -> bytes | None:
    """Generate thumbnail, with disk caching. Returns PNG bytes. Returns None on failure."""
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = THUMB_DIR / (filepath.name + ".thumb.png")

    # Serve from cache if exists and newer than source
    if cache_path.exists() and cache_path.stat().st_mtime >= filepath.stat().st_mtime:
        return cache_path.read_bytes()

    try:
        img = Image.open(filepath)
        img.thumbnail(THUMB_SIZE, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        img.close()
        data = buf.getvalue()
        # Write to cache
        try:
            cache_path.write_bytes(data)
        except OSError:
            pass
        return data
    except Exception:
        return None
def unq(s):
    return urllib.parse.unquote(s)
class GalleryHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        try:
            self._do_get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            import traceback
            traceback.print_exc()
    def do_POST(self):
        if self.path == "/api/batch":
            return self._handle_batch()
        if self.path == "/api/i2v":
            return self._handle_i2v()
        self.send_response(405)
        self.end_headers()
    def _handle_batch(self):
        """Handle batch operations (POST /api/batch)."""
        content_len = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(content_len))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        action = data.get("action", "")
        filenames = data.get("filenames", [])
        success, failed = [], []
        for fn in filenames:
            try:
                if action == "favorite":
                    if not is_favorited(fn):
                        toggle_favorite(fn)
                    success.append(fn)
                elif action == "archive":
                    result = toggle_archive(fn)
                    if result: success.append(fn)
                    else: failed.append(fn)
                elif action == "trash":
                    result = move_to_trash(fn)
                    if result: success.append(fn)
                    else: failed.append(fn)
            except Exception:
                failed.append(fn)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({
            "success": len(success),
            "failed": len(failed),
            "total": len(filenames),
        }).encode())
    def _handle_i2v(self):
        """POST /api/i2v — generate video from an existing image (async)."""
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        filename = data.get("filename", "").strip()
        prompt_i2v = data.get("prompt", "").strip()
        provider = data.get("provider", "replicate-wan")
        if not filename:
            self.send_error(400, "Missing filename")
            return
        if not prompt_i2v:
            self.send_error(400, "Missing prompt")
            return
        input_path = IMAGES_DIR / filename
        if not input_path.exists():
            self.send_error(404, "File not found")
            return
        
        job_id = uuid.uuid4().hex[:8]
        JOBS[job_id] = {"status": "running", "result": None}
        
        overrides = {}
        for k in ("num_frames", "fps", "resolution", "go_fast", "lora_url", "lora_scale"):
            if k in data:
                overrides[k] = data[k]
        
        def _await():
            try:
                from gen_lib.i2v import generate_i2v, I2V_PROVIDERS
                t0 = time.time()
                out_path = generate_i2v(
                    provider=provider,
                    image_path=str(input_path),
                    prompt=prompt_i2v,
                    **overrides,
                )
                elapsed = time.time() - t0
                # Insert into metadata DB
                try:
                    from gen_lib.metadata_db import insert
                    insert(
                        filename=out_path.name,
                        prompt=f"[I2V] {prompt_i2v}",
                        seed="",
                        model=f"i2v-{provider}",
                        params=f"source={filename}",
                        mtime=int(out_path.stat().st_mtime),
                    )
                except Exception:
                    pass
                JOBS[job_id]["result"] = {
                    "success": True,
                    "filename": out_path.name,
                    "url": f"/api/images/{out_path.name}",
                    "provider": provider,
                    "elapsed_s": round(elapsed, 1),
                }
                JOBS[job_id]["status"] = "done"
                _trim_jobs()
            except SystemExit:
                JOBS[job_id]["result"] = {"success": False, "error": "Generation failed (system exit)"}
                JOBS[job_id]["status"] = "done"
                _trim_jobs()
            except Exception as e:
                import traceback
                traceback.print_exc()
                JOBS[job_id]["result"] = {"success": False, "error": str(e)}
                JOBS[job_id]["status"] = "done"
                _trim_jobs()
        
        threading.Thread(target=_await, daemon=True).start()
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({
            "success": True,
            "job_id": job_id,
            "status": "queued",
        }).encode())
    
    def _handle_job(self):
        """GET /api/job?job=xxx — check async job status."""
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        job_id = params.get("job", [None])[0]
        if not job_id:
            self.send_error(400, "Missing job_id")
            return
        job = JOBS.get(job_id)
        if not job:
            self.send_error(404, "Job not found")
            return
        if job["status"] == "done":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            resp = {"job_id": job_id, "status": "done", "result": job["result"]}
            self.wfile.write(json.dumps(resp).encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"job_id": job_id, "status": "running"}).encode())
    def _do_get(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        # Serve gallery HTML
        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            with open(Path(__file__).parent / "gallery.html") as f:
                self.wfile.write(f.read().encode())
            return
        # PWA static files
        _static_files = {
            "/manifest.json": ("application/json", "gallery-manifest.json"),
            "/sw.js": ("application/javascript", "gallery-sw.js"),
            "/icon-192.png": ("image/png", "gallery-icon-192.png"),
            "/icon-512.png": ("image/png", "gallery-icon-512.png"),
        }
        if path in _static_files:
            mime, fname = _static_files[path]
            fpath = Path(__file__).parent / fname
            if fpath.exists():
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(fpath.read_bytes())
            else:
                self.send_error(404)
            return
        # API: list images (from SQLite)
        if path == "/api/images":
            page = int(params.get("page", [1])[0])
            per_page = int(params.get("per_page", [50])[0])
            filter_mode = params.get("filter", ["all"])[0]
            model_filter = params.get("model", [""])[0]
            search = params.get("search", [""])[0]
            archived = filter_mode == "archive"
            favorited_only = filter_mode == "fav"
            all_images = list_images(
                model_filter=model_filter,
                search=search,
                archived=archived,
                favorited_only=favorited_only,
                offset=(page - 1) * per_page,
                limit=per_page,
            )
            total = count_images(
                model_filter=model_filter,
                search=search,
                archived=archived,
                favorited_only=favorited_only,
            )
            total_pages = max(1, math.ceil(total / per_page))
            # Enrich with file stats
            for img in all_images:
                fp = _find_file(img["filename"])
                if fp:
                    st = fp.stat()
                    img["size_kb"] = st.st_size // 1024
                    img["mtime"] = img.get("mtime", 0) or int(st.st_mtime)
                else:
                    img["size_kb"] = 0
                img["favorited"] = bool(img.get("favorited", 0))
                img["archived"] = bool(img.get("archived", 0))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "images": all_images,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "models": distinct_models(),
            }).encode())
            return
        # API: rescan (refresh DB from directories)
        if path == "/api/rescan":
            from gen_lib.metadata_db import backfill
            n = backfill(IMAGES_DIR)
            _cleanup_old_trash()
            main_count = count_images(archived=False)
            arch_count = count_images(archived=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "count": main_count,
                "archived_count": arch_count,
                "indexed": n,
            }).encode())
            return
        # API: toggle favorite
        if path == "/api/favorite":
            filename = params.get("filename", [None])[0]
            if filename:
                new_state = toggle_favorite(filename)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"favorited": new_state, "filename": filename}).encode())
            else:
                self.send_error(400, "Missing filename")
            return
        # API: list favorites (from DB)
        if path == "/api/favorites":
            favs = [img["filename"] for img in list_images(favorited_only=True, limit=99999)]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"favorites": favs}).encode())
            return
        # API: toggle archive
        if path == "/api/archive":
            filename = params.get("filename", [None])[0]
            if filename:
                result = toggle_archive(filename)
                if result is None:
                    self.send_error(404, "File not found in main or archive")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            else:
                self.send_error(400, "Missing filename")
            return
        # API: list archived filenames (from DB)
        if path == "/api/archived":
            archived = [img["filename"] for img in list_images(archived=True, limit=99999)]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"archived": archived}).encode())
            return
        # API: move to trash
        if path == "/api/trash":
            filename = params.get("filename", [None])[0]
            if filename:
                result = move_to_trash(filename)
                if result is None:
                    self.send_error(404, "File not found")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            else:
                self.send_error(400, "Missing filename")
            return
        # API: single-file metadata (from SQLite, fallback to PNG)
        if path == "/api/meta":
            filename = params.get("filename", [None])[0]
            if filename:
                meta = get_meta(filename)
                if meta:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "filename": filename,
                        "prompt": meta.get("prompt", ""),
                        "seed": meta.get("seed", ""),
                        "model": meta.get("model", ""),
                        "params": meta.get("params", ""),
                    }).encode())
                else:
                    self.send_error(404, "File not found in index")
            else:
                self.send_error(400, "Missing filename")
            return
        # API: job status (for async operations like I2V)
        if path == "/api/job":
            return self._handle_job()
        # API: send to Telegram
        if path == "/api/send":
            filename = params.get("filename", [None])[0]
            if filename:
                filepath = IMAGES_DIR / filename
                if filepath.exists():
                    try:
                        result = subprocess.run(
                            ["/root/scripts/tg", str(filepath)],
                            capture_output=True, text=True, timeout=120
                        )
                        ok = result.returncode == 0
                        self.send_response(200 if ok else 500)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "sent": ok,
                            "filename": filename,
                            "error": result.stderr.strip() if not ok else None,
                        }).encode())
                    except subprocess.TimeoutExpired:
                        self.send_response(500)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "sent": False, "filename": filename,
                            "error": "timeout",
                        }).encode())
                else:
                    self.send_error(404, "File not found")
            else:
                self.send_error(400, "Missing filename")
            return
            action = data.get("action", "")
            filenames = data.get("filenames", [])
            success, failed = [], []
            for fn in filenames:
                try:
                    if action == "favorite":
                        if fn not in load_favorites():
                            toggle_favorite(fn)
                        success.append(fn)
                    elif action == "archive":
                        result = toggle_archive(fn)
                        if result: success.append(fn)
                        else: failed.append(fn)
                    elif action == "trash":
                        result = move_to_trash(fn)
                        if result: success.append(fn)
                        else: failed.append(fn)
                except Exception:
                    failed.append(fn)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": len(success),
                "failed": len(failed),
                "total": len(filenames),
            }).encode())
            return
        # Serve thumbnail — try main dir first, then archive
        if path.startswith("/thumb/"):
            filename = unq(path[7:])
            filepath = IMAGES_DIR / filename
            # For videos, use source image's thumbnail
            if not filepath.exists() and filename.endswith('.mp4'):
                # Try without .mp4 extension for files that might have name mismatches
                pass
            if filepath.suffix.lower() == '.mp4' and filepath.exists():
                from gen_lib.metadata_db import get_meta
                meta = get_meta(filename)
                if meta and meta.get('params', '').startswith('source='):
                    source_fn = meta['params'].replace('source=', '')
                    source_path = IMAGES_DIR / source_fn
                    if source_path.exists():
                        filepath = source_path
            if filepath.exists():
                thumb = make_thumbnail(filepath)
                if thumb is None:
                    self.send_error(415, "Unsupported image")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(thumb)))
                self.send_header("Cache-Control", "public, max-age=86400, immutable")
                self.end_headers()
                self.wfile.write(thumb)
            else:
                self.send_error(404)
            return
        # Serve raw image
        if path.startswith("/raw/"):
            filename = unq(path[5:])
            filepath = IMAGES_DIR / filename
            if filepath.exists():
                ext = filepath.suffix.lower()
                mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif", "mp4": "video/mp4"}
                ct = mime.get(ext.lstrip("."), "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                try:
                    with open(filepath, "rb") as f:
                        self.wfile.write(f.read())
                except Exception:
                    pass
            else:
                self.send_error(404)
            return
        self.send_error(404)
    def log_message(self, format, *args):
        pass  # quiet
if __name__ == "__main__":
    print(f"🚀 Gallery server on http://127.0.0.1:{PORT}")
    print(f"   Images: {IMAGES_DIR}")
    import threading
    total_files = len(list(IMAGES_DIR.glob("*"))) if IMAGES_DIR.exists() else 0
    server = ThreadingHTTPServer(("127.0.0.1", PORT), GalleryHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
