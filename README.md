# gen-pipeline

Self-hosted AI image generation pipeline — a browser UI (`gen.html`) that talks to
multiple image providers (Runware, ModelsLab, ...), saves every result as a PNG with
full AUTOMATIC1111-style metadata embedded, and indexes everything into a searchable
gallery with a SQLite backend.

Pure-Python (stdlib + Pillow). No framework, no database server, no Docker required.

## What's in the box

- **gen_server.py** — serves the gen UI + an async generation API (port **8091**).
- **gallery_server.py** — serves the image gallery UI (port **8089**).
- **gen.py** — optional CLI entry point with extra providers (fal/grok/together/replicate/openrouter/modelslab).
- **gen_lib/** — providers & helpers (runware, modelslab, metadata_db, common, i2v_*).
- **output/** — generated images (`output/images/`) + gallery index (`output/metadata.db`).
  Git-ignored: your local data lives here, it is not part of the repo.

## Quick start

```bash
git clone <this-repo> gen-pipeline
cd gen-pipeline

# 1. Install deps (Python 3.10+)
pip install -r requirements.txt

#    System dependency: ffmpeg is required for video thumbnails (gallery) and
#    the Ken Burns GIF feature. On Debian/Ubuntu:  sudo apt install ffmpeg

# 2. Configure keys
cp .env.example .env
#    edit .env — at minimum RUNWARE_API_KEY (and MODELSLAB_API_KEY for ModelsLab)

# 3. Run the two servers (each in its own terminal, or your favourite supervisor)
python3 gen_server.py       # -> http://127.0.0.1:8091   (gen UI)
python3 gallery_server.py   # -> http://127.0.0.1:8089   (gallery)
```

Open http://127.0.0.1:8091 in a browser. Generate an image; it appears in the
gallery at http://127.0.0.1:8089 automatically.

> **systemd / supervision:** the project ships no service files on purpose — run
> it however you like (`systemd`, `supervisord`, `tmux`, `nohup`). Both servers bind
> `127.0.0.1` only, so pair them with a reverse proxy if you want them on the internet.

## Configuration (.env)

Every key is read from a single `.env` at the **project root** (loaded by
`gen_lib/common.py::load_env`). Copy `.env.example` → `.env` and fill in.

| Key | Needed by | Notes |
|-----|-----------|-------|
| `RUNWARE_API_KEY` | gen web UI | **required** to run the UI |
| `MODELSLAB_API_KEY` | gen web UI (ModelsLab models) | required only if you use those models |
| `FAL_KEY` | gen.py CLI (`fal`) | optional |
| `XAI_API_KEY` | gen.py CLI (`grok`) | optional |
| `TOGETHER_API_KEY` | gen.py CLI (`together`) | optional |
| `REPLICATE_API_TOKEN` | gen.py CLI (`replicate`) + I2V | optional |
| `OPENROUTER_API_KEY` | gen.py CLI (`openrouter`) | optional |
| `RUNPOD_API_KEY` | I2V (`runpod-wan`) | optional |
| `RUNPOD_S3_*` / `RUNPOD_NETVOL_ID` | I2V via RunPod | optional; RunPod S3 + network volume |

## Project structure

```
gen-pipeline/
├── gen_server.py          # web UI + async gen API (8091)
├── gallery_server.py      # gallery UI (8089)
├── gen.py                 # CLI
├── gen.html               # gen web UI
├── gallery.html           # gallery web UI
├── i2v.html               # image-to-video page (served by gallery_server)
├── gen_lib/
│   ├── common.py          # env loading, image saving (embeds metadata), helpers
│   ├── runware.py         # Runware provider
│   ├── modelslab.py       # ModelsLab provider
│   ├── metadata_db.py     # SQLite + FTS5 gallery index
│   ├── fal.py / grok.py / together.py / replicate.py / openrouter.py  # CLI providers
│   ├── i2v.py / i2v_replicate.py / i2v_runpod.py   # image-to-video
│   └── check_vae.py       # offline VAE-health check (dev tool)
├── lora_registry.json     # LoRA catalog shipped with the service
├── i2v_lora_registry.json
├── i2v_snippets.json
├── snippets.json          # user prompt snippets (git-ignored; create if missing)
├── requirements.txt
├── .env.example
└── output/                # git-ignored local data (images + metadata.db)
```

## Reverse proxy (optional, for internet access)

Both servers bind `127.0.0.1`. To expose them publicly, put a reverse proxy in
front (e.g. Caddy / nginx). This repo is unopinionated about that layer.

Example Caddy block:

```caddyfile
gen.0x01.qzz.io {
    reverse_proxy 127.0.0.1:8091
}
img.0x01.qzz.io {
    reverse_proxy 127.0.0.1:8089
}
```

## Notes / conventions

- Every saved PNG embeds its full generation params in a `parameters` tEXt chunk
  (AUTOMATIC1111 format) — the gallery reads these back, so metadata survives
  re-indexing and is portable to other A1111-compatible tools.
- `snippets.json` holds your personal prompt presets and is **git-ignored**. If the
  file is missing the UI simply starts with no presets — it won't crash.
- `output/` is your data: images + `metadata.db`. Back it up; it is not in git.
- The gallery DB is the source of truth for favorites/archives (stored in SQLite,
  not in any JSON sidecar).
