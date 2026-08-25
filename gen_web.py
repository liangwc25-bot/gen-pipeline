#!/usr/bin/env python3
"""gen_web.py — Web API wrapper for gen.py

Called by server.py /api/generate endpoint.
Reads JSON from stdin, runs gen functions safely (no sys.exit), writes JSON to stdout.
"""

import sys
import json
import os
import tempfile
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # gen-pipeline root for gen_lib imports

_orig_exit = sys.exit
def _safe_exit(code=0):
    raise RuntimeError(f"gen.py called exit({code})")
sys.exit = _safe_exit

from gen_lib.common import load_env, OUTPUT_DIR

NSFW_MASTER_LORA = "civitai:667086@746602"

def result_ok(path=None, url=None, message="ok"):
    data = {"success": True, "message": message}
    if path:
        data["path"] = str(path)
        if path.exists():
            data["url"] = f"/api/output-images/{path.name}"
            data["size"] = path.stat().st_size
    if url:
        data["url"] = url
    return data

def result_err(msg):
    return {"success": False, "error": str(msg)}


def _translate_prompt(prompt: str, args: dict) -> tuple[str | None, str | None]:
    """Translate CN prompt to EN if translate flag is set.
    Returns (translated_prompt, error_message). One is always None.
    """
    if not args.get("translate") or not prompt:
        return prompt, None
    from gen_lib.translate import translate_cn_to_en
    translated = translate_cn_to_en(prompt)
    if translated:
        return translated, None
    return None, "翻译失败 — Hermes API server 无响应或超时，生成已取消"


def _generate_runware(args: dict) -> dict:
    """Runware path."""
    from gen_lib.runware import generate as gen_runware
    prompt = args.get("prompt", "").strip()
    prompt, err = _translate_prompt(prompt, args)
    if err:
        return result_err(err)
    negative = args.get("negative_prompt", "")
    model = args.get("model", "flux-dev")
    seed = args.get("seed")
    lora_id = args.get("lora_id")
    lora_scale = args.get("lora_scale", 0.8)
    cfg_scale = args.get("cfg_scale")  # float or None (None = use model default)
    steps = args.get("steps")
    aspect = args.get("aspect", "9:16")
    sampler = args.get("sampler")
    nsfw_lora = args.get("nsfw_lora", False)
    nsfw = args.get("nsfw", model in ("pony-xl", "prefect-ill-xl"))

    # Qwen-Edit: save data URI to temp file
    _qwen_tmp = None
    raw_image = args.get("image_path", "")
    if raw_image:
        import tempfile, base64
        b64_data = raw_image.split(",")[-1] if "," in raw_image else raw_image
        _qwen_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        _qwen_tmp.write(base64.b64decode(b64_data))
        _qwen_tmp.close()

    if not prompt:
        return result_err("Prompt is required")

    effective_lora_id = lora_id
    effective_lora_scale = lora_scale

    if nsfw_lora and model == "flux-dev":
        if lora_id:
            effective_lora_id = f"{NSFW_MASTER_LORA},{lora_id}"
            effective_lora_scale = f"1.0,{lora_scale}"
        else:
            effective_lora_id = NSFW_MASTER_LORA
            effective_lora_scale = 1.0

    try:
        import time, io
        t0 = time.time()
        _old_stderr, _old_stdout = sys.stderr, sys.stdout
        _stderr_buf = io.StringIO()
        sys.stderr = sys.stdout = _stderr_buf
        try:
            bwidth = args.get("width")
            bheight = args.get("height")
            result = gen_runware(prompt,
                model_key=model, negative_prompt=negative,
                lora_id=effective_lora_id, lora_scale=effective_lora_scale,
                seed=seed, image_path=_qwen_tmp.name if _qwen_tmp else None,
                cfg_scale=cfg_scale, aspect=aspect,
                steps=int(steps) if steps else 35,
                sampler=sampler if sampler else None,
                width=int(bwidth) if bwidth else None,
                height=int(bheight) if bheight else None)
            if isinstance(result, tuple):
                result, used_seed = result
            else:
                used_seed = None
        finally:
            sys.stdout, sys.stderr = _old_stdout, _old_stderr
            _log = _stderr_buf.getvalue()
            _stderr_buf.close()

        elapsed = time.time() - t0
        resp = result_ok(path=result, message=f"Done in {elapsed:.1f}s")
        if result and result.exists():
            resp["size"] = result.stat().st_size
            resp["seed"] = used_seed
            # Write to metadata index
            try:
                from gen_lib.metadata_db import insert
                # Build params string matching save_image() AUTOMATIC1111 format
                _param_parts = [f"Steps: {int(steps) if steps else 35}"]
                if used_seed is not None:
                    _param_parts.append(f"Seed: {used_seed}")
                if aspect:
                    _w, _h = {"9:16":(704,1216),"16:9":(1216,704),"1:1":(1024,1024),"3:2":(1152,768),"2:3":(768,1152),"4:3":(1024,768),"3:4":(768,1024)}.get(aspect, (704,1216))
                    _param_parts.append(f"Size: {_w}x{_h}")
                _param_parts.append(f"Model: {model}")
                if lora_id:
                    _param_parts.append(f"Lora: {lora_id}")
                if cfg_scale:
                    _param_parts.append(f"CFG: {cfg_scale}")
                if sampler:
                    _param_parts.append(f"Sampler: {sampler}")
                insert(
                    filename=result.name,
                    prompt=prompt,
                    seed=str(used_seed) if used_seed is not None else "",
                    model=model,
                    params=", ".join(_param_parts),
                    mtime=int(result.stat().st_mtime),
                )
            except Exception:
                pass
        return resp
    except Exception as e:
        return result_err(f"{type(e).__name__}: {e}\n{_log if '_log' in dir() else ''}")


def _generate_modelslab(args: dict) -> dict:
    """ModelsLab path — Pony, Illustrious, SDXL, FLUX.
    NSFW via rating_explicit for Pony/Illustrious, safety_checker off for all.
    """
    from gen_lib.modelslab import generate as gen_modelslab
    prompt = args.get("prompt", "").strip()
    prompt, err = _translate_prompt(prompt, args)
    if err:
        return result_err(err)
    negative = args.get("negative_prompt", "")
    model = args.get("model", "pony")
    seed = args.get("seed")
    lora_model = args.get("lora_model")
    lora_strength = float(args.get("lora_strength", 0.7))

    if not prompt:
        return result_err("Prompt is required")

    try:
        import time, io
        t0 = time.time()
        _old_stderr, _old_stdout = sys.stderr, sys.stdout
        _stderr_buf = io.StringIO()
        sys.stderr = sys.stdout = _stderr_buf
        try:
            result = gen_modelslab(prompt,
                model_key=model,
                negative_prompt=negative,
                seed=seed,
                lora_model=lora_model,
                lora_strength=lora_strength)
        finally:
            sys.stdout, sys.stderr = _old_stdout, _old_stderr
            _log = _stderr_buf.getvalue()
            _stderr_buf.close()

        elapsed = time.time() - t0
        resp = result_ok(path=result, message=f"Done in {elapsed:.1f}s")
        if result and result.exists():
            resp["size"] = result.stat().st_size
            resp["seed"] = seed
            # Write to metadata index
            try:
                from gen_lib.metadata_db import insert
                insert(
                    filename=result.name,
                    prompt=prompt,
                    seed=str(seed) if seed is not None else "",
                    model=model,
                    params="",
                    mtime=int(result.stat().st_mtime),
                )
            except Exception:
                pass
        return resp
    except Exception as e:
        return result_err(f"{type(e).__name__}: {e}\n{_log if '_log' in dir() else ''}")


def _generate_flux_family(args: dict) -> dict:
    """FLUX 家族 path — 6 curated FLUX models served via Runware, single interface."""
    from gen_lib.runware import generate_flux_family as gen_flux
    prompt = args.get("prompt", "").strip()
    prompt, err = _translate_prompt(prompt, args)
    if err:
        return result_err(err)
    model = args.get("model", "flux-dev")
    if not prompt:
        return result_err("Prompt is required")
    try:
        import time, io
        t0 = time.time()
        _old_stderr, _old_stdout = sys.stderr, sys.stdout
        _stderr_buf = io.StringIO()
        sys.stderr = sys.stdout = _stderr_buf
        try:
            result = gen_flux(prompt,
                model_key=model,
                negative_prompt=args.get("negative_prompt", ""),
                seed=args.get("seed"),
                aspect=args.get("aspect", "9:16"),
                cfg_scale=args.get("cfg_scale"),
                steps=int(args["steps"]) if args.get("steps") else None,
                raw=args.get("raw"))
        finally:
            sys.stdout, sys.stderr = _old_stdout, _old_stderr
            _log = _stderr_buf.getvalue()
            _stderr_buf.close()

        elapsed = time.time() - t0
        path, used_seed = result
        resp = result_ok(path=path, message=f"Done in {elapsed:.1f}s")
        if path and path.exists():
            resp["size"] = path.stat().st_size
            resp["seed"] = used_seed
            try:
                from gen_lib.metadata_db import insert
                insert(
                    filename=path.name, prompt=prompt,
                    seed=str(used_seed) if used_seed is not None else "",
                    model=model, params=f"Model: {model}",
                    mtime=int(path.stat().st_mtime),
                )
            except Exception:
                pass
        return resp
    except Exception as e:
        return result_err(f"{type(e).__name__}: {e}\n{_log if '_log' in dir() else ''}")


def generate(args: dict) -> dict:
    """Dispatch to Runware, ModelsLab, or FLUX 家族 based on platform field."""
    load_env()  # ensure env vars loaded before platform dispatch
    platform = args.get("platform", "runware")
    if platform == "modelslab":
        return _generate_modelslab(args)
    if platform == "flux":
        return _generate_flux_family(args)
    return _generate_runware(args)


def list_loras(model: str = None) -> dict:
    """Return available LoRAs from registry, optionally filtered by base_model.
    Only returns LoRAs with runware_air_id (verified on Runware)."""
    import json as _json
    registry_path = Path(__file__).parent / "lora_registry.json"
    try:
        with open(registry_path) as f:
            registry = _json.load(f)
    except Exception:
        return {"success": False, "error": "Cannot read lora registry", "loras": []}

    all_loras = registry.get("loras", [])
    # Normalize model aliases for filtering
    model_aliases = {"pony-xl": "pony", "pony-real": "pony", "hoj-illustrious-xl": "illustrious", "ponymature-pony": "pony", "prefect-ill-xl": "illustrious", "flux-uncensored": "flux-dev", "flux-ultrareal": "flux-dev", "flux-artsy-dream": "flux-dev", "flux-artsy-vibe": "flux-dev", "flux-nepotism": "flux-dev", "flux-blue-pencil": "flux-dev", "flux-fluximation": "flux-dev", "iniverse-mix-flux": "flux-dev", "lah-mysterious-flux": "flux-dev", "khialmaster-flux": "flux-dev", "c4pacitor-flux": "flux-dev", "asian-flux": "flux-dev", "animeasy-flux": "flux-dev", "myhuman-flux": "flux-dev", "redcraft-flux": "flux-dev", "guofeng4-xl": "sdxl", "pornmaster": "sdxl", "lustify": "sdxl", "sdxl-vanilla": "sdxl", "dreamshaper-xl": "sdxl", "juggernaut-xl": "sdxl", "fantasy-reality-xl": "sdxl", "xuer-cyan-xl": "sdxl", "flux-klein": "flux-klein", "zimage-alibaba": "zimage-turbo", "zimage-moody": "zimage-turbo", "zimage-stable-yogi": "zimage-turbo", "zimage-ultimate-nsfw": "zimage-turbo", "zimage-turbo-anime": "zimage-turbo", "zimage-visionary-nsfw": "zimage-turbo", "zimage-tinzit-anime": "zimage-turbo", "zimage-lau-anime": "zimage-turbo", "zimage-komposto-ani": "zimage-turbo", "zimage-pornmaster-v35": "zimage-turbo", "dreamshaper-15": "sd15", "majicmix-real-15": "sd15", "realcartoon3d-15": "sd15", "aniverse-15": "sd15", "chikmix-15": "sd15", "realcartoon-real-15": "sd15", "perfect-world-15": "sd15", "majicmix-lux-15": "sd15", "dark-sushi-25d-15": "sd15", "guofeng-wuxia-15": "sd15", "tastyrice-cg-15": "sd15", "onlyrealistic-15": "sd15", "chilloutmix-15": "sd15", "chosen-mix-15": "sd15", "abyss-orange-mix-15": "sd15", "nwsj-real-mix-sdxl": "sdxl", "aom3-15": "sd15", "wanxiang-anything-15": "sd15", "lazymix-15": "sd15", "aom2-hardcore-15": "sd15", "dark-sushi-mix-15": "sd15", "realisian-15": "sd15", "anyhentai-15": "sd15", "majicmix-sombre-15": "sd15", "realcartoon-anime-15": "sd15", "fantexi-15": "sd15", "orangechillmix-15": "sd15", "camelliamix-15": "sd15", "astranime-15": "sd15", "kawaii-anime-mix-15": "sd15", "kakarot-28d-15": "sd15", "majicmix-reverie-15": "sd15", "majicmix-horror-15": "sd15", "wai-realmix-pony": "pony", "wai-ani-hentai-pony": "pony", "realcartoon-pony": "pony", "wai-ani-pony": "pony", "nova-anime-pony": "pony", "nova-reality-pony": "pony", "atomix-anime-pony": "pony", "redcraft-pony": "pony", "the-deep-dark-pony": "pony", "honey-mix-pony": "pony", "nova-asian-pony": "pony", "powerpuffmix-pony": "pony", "wai-semireal-pony": "pony", "wai-c-pony": "pony", "atomix-3d-pony": "pony", "miaomiao-3d-pony": "pony", "powerpuffanimix-pony": "pony", "wai-mature-pony": "pony", "red-blue-fantasy-pony": "pony", "wai-illustrious": "illustrious", "aoi-164": "illustrious", "cat-citron-anime": "illustrious", "nova-anime-xl-noob": "illustrious", "nova-reality-ill": "illustrious", "miaomiao-harem-ill": "illustrious", "animij-ill": "illustrious", "illustrious-xl-2": "illustrious", "ilustmix-ill": "illustrious", "pornmaster-ill": "illustrious", "kawaij-ill": "illustrious", "nova-orange-ill": "illustrious", "nova-flat-ill": "illustrious", "semilust-ill": "illustrious", "pornmaster-anime-ill": "illustrious", "matureritual-ill": "illustrious", "burgundy-semireal-ill": "illustrious", "burgundy-bimbos-ill": "illustrious", "burgundy-dolls-ill": "illustrious", "burgundy-milfs-ill": "illustrious", "miaomiao-mature-ill": "illustrious", "persona-zit": "zimage-turbo"}
    match_base = model_aliases.get(model, model) if model else None
    result = []
    for l in all_loras:
        air_id = l.get("runware_air_id", "")
        if not air_id:
            continue  # skip prompt-only / unverified
        if match_base and l.get("base_model") != match_base:
            continue  # filter by model compatibility
        result.append({
            "id": l["id"],
            "name": l["name"],
            "air_id": air_id,
            "default_scale": l.get("default_scale", 0.8),
            "scale_range": l.get("scale_range", [0.1, 2.0]),
            "description": l.get("description", ""),
            "category": l.get("category", ""),
            "trigger_words": l.get("trigger_words", []),
        })
    return {"success": True, "loras": result}


def list_models(platform: str = "runware") -> dict:
    """Return available models for either Runware or ModelsLab."""
    if platform == "modelslab":
        from gen_lib.modelslab import MODELS as ML_MODELS
        models = [{"id": k, "name": v["name"], "price": v["price"]}
                  for k, v in ML_MODELS.items()]
        return {"success": True, "models": models}
    if platform == "flux":
        from gen_lib.runware import FLUX_FAMILY
        models = [{"id": m["key"], "name": m["name"], "price": m["price"]}
                  for m in FLUX_FAMILY]
        return {"success": True, "models": models}
    else:
        from gen_lib.runware import MODELS as RUNWARE_MODELS
        web_models = ["flux-dev", "flux-uncensored", "flux-ultrareal", "flux-artsy-dream", "flux-artsy-vibe", "flux-nepotism", "flux-blue-pencil", "flux-fluximation", "iniverse-mix-flux", "lah-mysterious-flux", "khialmaster-flux", "c4pacitor-flux", "asian-flux", "animeasy-flux", "myhuman-flux", "redcraft-flux", "pony-xl", "pony-real", "prefect-ill-xl", "guofeng4-xl", "pornmaster", "lustify", "sdxl-vanilla", "dreamshaper-xl", "juggernaut-xl", "fantasy-reality-xl", "xuer-cyan-xl", "hoj-illustrious-xl", "nwsj-real-mix-sdxl", "wai-illustrious", "aoi-164", "cat-citron-anime", "nova-anime-xl-noob", "nova-reality-ill", "miaomiao-harem-ill", "animij-ill", "illustrious-xl-2", "ilustmix-ill", "pornmaster-ill", "kawaij-ill", "nova-orange-ill", "nova-flat-ill", "semilust-ill", "pornmaster-anime-ill", "matureritual-ill", "burgundy-semireal-ill", "burgundy-bimbos-ill", "burgundy-dolls-ill", "burgundy-milfs-ill", "miaomiao-mature-ill", "wai-realmix-pony", "wai-ani-hentai-pony", "realcartoon-pony", "wai-ani-pony", "nova-anime-pony", "nova-reality-pony", "atomix-anime-pony", "redcraft-pony", "the-deep-dark-pony", "honey-mix-pony", "nova-asian-pony", "powerpuffmix-pony", "wai-semireal-pony", "wai-c-pony", "atomix-3d-pony", "miaomiao-3d-pony", "powerpuffanimix-pony", "wai-mature-pony", "red-blue-fantasy-pony", "ponymature-pony", "zimage-alibaba", "zimage-moody", "zimage-stable-yogi", "zimage-ultimate-nsfw", "zimage-turbo-anime", "zimage-visionary-nsfw", "zimage-tinzit-anime", "zimage-lau-anime", "zimage-komposto-ani", "zimage-pornmaster-v35", "persona-zit", "qwen-edit", "qwen-edit-plus", "flux-klein", "dreamshaper-15", "majicmix-real-15", "realcartoon3d-15", "aniverse-15", "chikmix-15", "realcartoon-real-15", "perfect-world-15", "majicmix-lux-15", "dark-sushi-25d-15", "guofeng-wuxia-15", "tastyrice-cg-15", "onlyrealistic-15", "chilloutmix-15", "chosen-mix-15", "abyss-orange-mix-15", "aom3-15", "wanxiang-anything-15", "lazymix-15", "aom2-hardcore-15", "dark-sushi-mix-15", "realisian-15", "anyhentai-15", "majicmix-sombre-15", "realcartoon-anime-15", "fantexi-15", "orangechillmix-15", "camelliamix-15", "astranime-15", "kawaii-anime-mix-15", "kakarot-28d-15", "majicmix-reverie-15", "majicmix-horror-15"]
        models = [{"id": k, "name": RUNWARE_MODELS[k]["name"], "price": RUNWARE_MODELS[k]["price"]}
                  for k in web_models if k in RUNWARE_MODELS]
        return {"success": True, "models": models}


if __name__ == "__main__":
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON"}))
        sys.exit(1)

    action = data.get("action", "generate")
    if action == "generate":
        result = generate(data)
    elif action == "list_models":
        result = list_models(data.get("platform", "runware"))
    elif action == "list_loras":
        result = list_loras(data.get("model"))
    else:
        result = {"success": False, "error": f"Unknown action: {action}"}

    print(json.dumps(result, ensure_ascii=False))
