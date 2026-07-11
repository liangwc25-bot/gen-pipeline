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

# Import GIF zoom
from gen_lib.gif_zoom import make_gif

# Completed jobs cap — prevent unbounded memory growth (OOM kills)
JOBS = OrderedDict()
MAX_JOBS = 50


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
        
        # Static files
        if self._parsed_path == "/":
            self._parsed_path = "/gen.html"
        
        _static = {"/gen.html": "text/html", "/gen-manifest.json": "application/json"}
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
        if self.path == "/api/gif-zoom":
            return self._handle_gif_zoom()
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

        proc = subprocess.Popen(
            ["python3", str(GEN_WEB_PY)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        proc.stdin.write(json.dumps(data))
        proc.stdin.close()

        JOBS[job_id] = {"status": "running", "result": None, "proc": proc}

        def _await():
            try:
                proc.wait(timeout=300)
                stdout = proc.stdout.read()
                try:
                    result = json.loads(stdout.strip())
                except json.JSONDecodeError:
                    result = {"success": False, "error": f"Output invalid: {stdout[:300]}"}
                JOBS[job_id]["result"] = result
                JOBS[job_id]["status"] = "done"
                JOBS[job_id].pop("proc", None)
                _trim_jobs()
            except subprocess.TimeoutExpired:
                proc.kill()
                JOBS[job_id]["result"] = {"success": False, "error": "Timed out (300s)"}
                JOBS[job_id]["status"] = "done"
                JOBS[job_id].pop("proc", None)
                _trim_jobs()
            except Exception as e:
                JOBS[job_id]["result"] = {"success": False, "error": str(e)}
                JOBS[job_id]["status"] = "done"
                JOBS[job_id].pop("proc", None)
                _trim_jobs()

        threading.Thread(target=_await, daemon=True).start()
        self._json_response({"success": True, "job_id": job_id, "status": "queued"})

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
