#!/usr/bin/env python3
"""Gen pipeline server — gen.html + async generation API"""
import json, os, time, subprocess, threading, uuid
from collections import OrderedDict
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# ── Config ──
_env_file = Path(__file__).parent / ".env"
_runware_key = ""
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        if line.startswith("RUNWARE_API_KEY="):
            _runware_key = line.split("=", 1)[1].strip().strip('"').strip("'")
RUNWARE_KEY = _runware_key or os.environ.get("RUNWARE_API_KEY", "")
GEN_DIR = Path(__file__).parent
GEN_WEB_PY = GEN_DIR / "gen_web.py"
OUTPUT_DIR = GEN_DIR / "output" / "images"
SNIPPETS_FILE = GEN_DIR / "snippets.json"

# Import GIF zoom
from gen_lib.gif_zoom import make_gif

# Completed jobs cap — prevent unbounded memory growth (OOM kills)
JOBS = OrderedDict()
MAX_JOBS = 50
GEN_SEM = threading.BoundedSemaphore(6)  # max concurrent gen_web.py for normal generate

# Batch jobs (model comparison)
BATCH_JOBS = OrderedDict()
MAX_BATCH_JOBS = 30
BATCH_CONCURRENCY = 6  # max concurrent gen_web.py processes per batch


def _trim_batch_jobs():
    while len(BATCH_JOBS) > MAX_BATCH_JOBS:
        for bid, bjob in list(BATCH_JOBS.items()):
            if bjob["status"] == "done":
                BATCH_JOBS.pop(bid)
                break
        else:
            break


def _trim_jobs():
    """Remove oldest completed jobs when over MAX_JOBS."""
    while len(JOBS) > MAX_JOBS:
        for jid, job in list(JOBS.items()):
            if job["status"] == "done":
                JOBS.pop(jid)
                break
        else:
            break  # nothing left to trim


# ── HTTP Handler ──

class GenHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse
        self._parsed_path = urlparse(self.path).path
        
        # API endpoints
        if self._parsed_path == "/api/list-loras":
            return self._handle_list_loras()
        if self._parsed_path == "/api/list-models":
            return self._handle_list_models()
        if self._parsed_path.startswith("/api/output-images/"):
            return self._handle_output_image()
        if self._parsed_path.startswith("/api/job"):
            return self._handle_job()
        if self._parsed_path.startswith("/api/batch"):
            return self._handle_batch_get()
        if self._parsed_path == "/api/snippets":
            return self._handle_get_snippets()
        
        # Static files
        if self._parsed_path == "/":
            self._parsed_path = "/gen.html"
        
        _static = {
            "/gen.html": "text/html",
            "/batch.html": "text/html",
            "/gen-manifest.json": "application/json",
            "/icon-192.png": "image/png",
            "/icon-512.png": "image/png",
        }
        if self._parsed_path in _static:
            fp = GEN_DIR / self._parsed_path.lstrip("/")
            if fp.exists():
                self.send_response(200)
                self.send_header("Content-Type", _static[self._parsed_path])
                self.end_headers()
                self.wfile.write(fp.read_bytes())
                return
        
        self.send_error(404)

    def do_POST(self):
        if self.path == "/api/generate":
            return self._handle_generate()
        if self.path == "/api/batch":
            return self._handle_batch()
        if self.path == "/api/gif-zoom":
            return self._handle_gif_zoom()
        if self.path == "/api/snippets":
            return self._handle_post_snippets()
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not found")

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _handle_list_loras(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        model = qs.get("model", [None])[0]
        try:
            r = subprocess.run(
                ["python3", str(GEN_WEB_PY)],
                input=json.dumps({"action": "list_loras", "model": model}),
                capture_output=True, text=True, timeout=15,
            )
            result = json.loads(r.stdout.strip())
        except Exception as e:
            result = {"success": False, "error": str(e), "loras": []}
        self._json_response(result)

    def _handle_list_models(self):
        try:
            r = subprocess.run(
                ["python3", str(GEN_WEB_PY)],
                input=json.dumps({"action": "list_models", "platform": "runware"}),
                capture_output=True, text=True, timeout=15,
            )
            result = json.loads(r.stdout.strip())
        except Exception as e:
            result = {"success": False, "error": str(e), "models": []}
        self._json_response(result)

    def _handle_output_image(self):
        filename = self.path.split("/api/output-images/", 1)[1]
        filepath = OUTPUT_DIR / filename
        if not filepath.exists() or not filepath.is_file():
            self.send_error(404)
            return
        ext = filepath.suffix.lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif", ".mp4": "video/mp4"}.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(filepath.read_bytes())

    def _handle_generate(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json_response({"success": False, "error": "Invalid JSON"}, 400)

        data["action"] = "generate"
        job_id = uuid.uuid4().hex[:8]

        JOBS[job_id] = {"status": "queued", "result": None}

        def _await():
            GEN_SEM.acquire()
            JOBS[job_id]["status"] = "running"
            try:
                proc = subprocess.Popen(
                    ["python3", str(GEN_WEB_PY)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True,
                )
                proc.stdin.write(json.dumps(data))
                proc.stdin.close()

                try:
                    proc.wait(timeout=300)
                    stdout = proc.stdout.read()
                    try:
                        result = json.loads(stdout.strip())
                    except json.JSONDecodeError:
                        result = {"success": False, "error": f"Output invalid: {stdout[:300]}"}
                except subprocess.TimeoutExpired:
                    proc.kill()
                    result = {"success": False, "error": "Timed out (300s)"}
                except Exception as e:
                    result = {"success": False, "error": str(e)}

                JOBS[job_id]["result"] = result
                JOBS[job_id]["status"] = "done"
                _trim_jobs()
            finally:
                GEN_SEM.release()

        threading.Thread(target=_await, daemon=True).start()
        self._json_response({"success": True, "job_id": job_id, "status": "queued"})

    def _handle_batch(self):
        """POST /api/batch — fire the same prompt across N checkpoints concurrently."""
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json_response({"success": False, "error": "Invalid JSON"}, 400)

        models = data.get("models", [])
        if not models or not isinstance(models, list):
            return self._json_response({"success": False, "error": "models[] required"}, 400)

        prompt = data.get("prompt", "").strip()
        if not prompt:
            return self._json_response({"success": False, "error": "Prompt is required"}, 400)

        batch_id = uuid.uuid4().hex[:8]
        shared = {
            "action": "generate",
            "prompt": prompt,
            "negative_prompt": data.get("negative_prompt", ""),
            "lora_id": data.get("lora_id"),
            "lora_scale": data.get("lora_scale", 0.8),
            "cfg_scale": data.get("cfg_scale"),
            "steps": data.get("steps", 35),
            "aspect": data.get("aspect", "9:16"),
            "sampler": data.get("sampler"),
            "seed": data.get("seed"),
            "nsfw_lora": data.get("nsfw_lora", False),
            "translate": data.get("translate", False),
        }

        batch_entry = {"status": "running", "total": len(models), "completed": 0, "models": {}}
        sem = threading.BoundedSemaphore(BATCH_CONCURRENCY)

        for model_key in models:
            payload = dict(shared)
            payload["model"] = model_key
            if shared["seed"] is None:
                payload["seed"] = None  # let each get its own random seed

            batch_entry["models"][model_key] = {"status": "queued"}

            def _run_model(mk, pl):
                sem.acquire()
                batch_entry["models"][mk]["status"] = "running"
                proc = subprocess.Popen(
                    ["python3", str(GEN_WEB_PY)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True,
                )
                proc.stdin.write(json.dumps(pl))
                proc.stdin.close()

                try:
                    proc.wait(timeout=300)
                    stdout = proc.stdout.read()
                    try:
                        result = json.loads(stdout.strip())
                    except json.JSONDecodeError:
                        result = {"success": False, "error": f"Output invalid: {stdout[:300]}"}
                except subprocess.TimeoutExpired:
                    proc.kill()
                    result = {"success": False, "error": "Timed out (300s)"}
                except Exception as e:
                    result = {"success": False, "error": str(e)}

                batch_entry["models"][mk]["result"] = result
                batch_entry["models"][mk]["status"] = "done"
                batch_entry["completed"] += 1

                sem.release()

                if batch_entry["completed"] >= batch_entry["total"]:
                    batch_entry["status"] = "done"
                    _trim_batch_jobs()

            threading.Thread(target=_run_model, args=(model_key, payload), daemon=True).start()

        BATCH_JOBS[batch_id] = batch_entry
        self._json_response({
            "success": True,
            "batch_id": batch_id,
            "status": "queued",
            "total": len(models),
        })

    def _handle_batch_get(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        batch_id = qs.get("batch_id", [""])[0]
        if not batch_id:
            return self._json_response({"error": "Missing batch_id"}, 400)
        bj = BATCH_JOBS.get(batch_id)
        if not bj:
            return self._json_response({"error": "Batch not found"}, 404)

        models_status = {}
        for mk, ms in bj["models"].items():
            if ms["status"] == "done":
                models_status[mk] = {"status": "done", "result": ms.get("result")}
            else:
                models_status[mk] = {"status": "running"}

        return self._json_response({
            "batch_id": batch_id,
            "status": bj["status"],
            "total": bj["total"],
            "completed": bj["completed"],
            "models": models_status,
        })

    def _handle_job(self):
        job_id = self.path.split("/api/job?job=", 1)[-1].split("&")[0] if "?" in self.path else ""
        if not job_id:
            return self._json_response({"error": "Missing job_id"}, 400)
        job = JOBS.get(job_id)
        if not job:
            return self._json_response({"error": "Job not found"}, 404)
        if job["status"] == "done":
            return self._json_response({"job_id": job_id, "status": "done", "result": job["result"]})
        return self._json_response({"job_id": job_id, "status": "running"})

    def _handle_get_snippets(self):
        if SNIPPETS_FILE.exists():
            try:
                data = json.loads(SNIPPETS_FILE.read_text())
            except (json.JSONDecodeError, Exception):
                data = {}
        else:
            data = {}
        self._json_response({"success": True, "snippets": data})

    def _handle_post_snippets(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json_response({"success": False, "error": "Invalid JSON"}, 400)
        snippets = data.get("snippets")
        if not isinstance(snippets, dict):
            return self._json_response({"success": False, "error": "snippets must be an object"}, 400)
        try:
            SNIPPETS_FILE.write_text(json.dumps(snippets, ensure_ascii=False, indent=2))
        except Exception as e:
            return self._json_response({"success": False, "error": str(e)})
        self._json_response({"success": True})

    def _handle_gif_zoom(self):
        """POST /api/gif-zoom — create a breathing GIF from an existing image."""
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json_response({"success": False, "error": "Invalid JSON"}, 400)

        filename = data.get("filename", "").strip()
        if not filename:
            return self._json_response({"success": False, "error": "Missing filename"}, 400)

        input_path = OUTPUT_DIR / filename
        if not input_path.exists():
            return self._json_response({"success": False, "error": f"File not found: {filename}"}, 404)

        if input_path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            return self._json_response({"success": False, "error": "Unsupported format"}, 400)

        stem = input_path.stem
        output_name = f"{stem}_breathing.gif"
        output_path = OUTPUT_DIR / output_name

        try:
            import time
            t0 = time.time()
            make_gif(
                input_path, output_path,
                zoom_factor=data.get("zoom_factor", 0.04),
                pan_x=data.get("pan_x", 4),
                pan_y=data.get("pan_y", 3),
                fps=data.get("fps", 12),
                cycle_s=data.get("cycle_s", 2.0),
                cycles=data.get("cycles", 1),
            )
            elapsed = time.time() - t0
            return self._json_response({
                "success": True,
                "filename": output_name,
                "url": f"/api/output-images/{output_name}",
                "size": output_path.stat().st_size,
                "elapsed_s": round(elapsed, 2),
            })
        except subprocess.CalledProcessError as e:
            return self._json_response({"success": False, "error": f"FFmpeg error: {e.stderr[:300]}"})
        except Exception as e:
            return self._json_response({"success": False, "error": str(e)})

# ── Start ──

if __name__ == "__main__":
    PORT = 8091
    server = HTTPServer(("127.0.0.1", PORT), GenHandler)
    print(f"Gen pipeline → http://127.0.0.1:{PORT}")
    server.serve_forever()
