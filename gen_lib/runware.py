"""
gen_lib/runware.py — Runware AI image generation.

Premier platform: cheapest FLUX ($0.0013), Pony SDXL, CivitAI LoRA,
IP-Adapter face preservation, NSFW via safety.checkContent=false.

Image-to-image requires two-step flow: imageUpload → seedImage UUID.
"""

import uuid
import json
import base64
import sys
import urllib.request
import urllib.error
from pathlib import Path
from gen_lib.common import get_key, save_image, http_post, download_bytes

MODELS = {
    "flux-dev":       {"id": "runware:101@1", "name": "FLUX.1-dev", "price": "$0.0013/张"},
    "flux-schnell":   {"id": "bfl:1@1", "name": "FLUX Schnell", "price": "$0.0023/张"},
    "flux-uncensored": {"id": "loraimagegen:11111@11111", "name": "Fluxedup NSFW", "price": "$0.0038/张"},
    "flux-2-pro":     {"id": "bfl:5@1", "name": "FLUX.2 Pro", "price": "$0.045/张"},
    "pony":           {"id": "runware:777@1", "name": "Pony V7 (AuraFlow)", "price": "~$0.005/张"},
    "sdxl":           {"id": "runware:100@1", "name": "SDXL", "price": "~$0.003/张"},
    "pony-xl":        {"id": "liangwc:3@1", "name": "Prefect Pony XL v3", "price": "$0.0013/张"},
    "pony-real":      {"id": "civitai:477851@695106", "name": "DucHaiten-Pony-Real", "price": "$0.0006/张"},
    "prefect-ill-xl": {"id": "liangwc:6@1", "name": "Prefect Illustrious XL v8", "price": "~$0.003/张"},
    "guofeng4-xl":    {"id": "liangwc:guofeng4-xl@1", "name": "国风4 GuoFeng4 XL", "price": "~$0.003/张"},
    "pornmaster":     {"id": "liangwc:pornmaster@1", "name": "PornMaster-色情大师", "price": "~$0.003/张"},
    "lustify":        {"id": "hassakuxl:573152@2155386", "name": "LUSTIFY SDXL", "price": "~$0.003/张"},
    "sdxl-vanilla":   {"id": "liangwc:sdxl-vanilla@1", "name": "SDXL Vanilla 1.0", "price": "~$0.003/张"},
    "dreamshaper-xl": {"id": "civitai:112902@121931", "name": "DreamShaper XL", "price": "~$0.003/张"},
    "juggernaut-xl":  {"id": "rundiffusion:133005@288982", "name": "JuggernautXL V8", "price": "~$0.003/张"},
    "qwen-edit":      {"id": "liangwc:qwen-edit-2509-abliterated@1", "name": "Qwen-Edit 无审查版", "price": "~$0.003/张"},
    "fantasy-reality-xl": {"id": "civitai:230569@260218", "name": "Fantasy Reality Fusion XL", "price": "~$0.003/张"},
    "zimage-alibaba": {"id": "runware:z-image@turbo", "name": "Alibaba Z-Image-Turbo", "price": "$0.0006/张"},
    "zimage-moody":   {"id": "persona:620406@2745677", "name": "Moody Pro Mix (Z-Image)", "price": "$0.0013/张"},
    # SD 1.5 Checkpoints
    "dreamshaper-15":    {"id": "civitai:4384@128713", "name": "DreamShaper 1.5", "price": "~$0.003/张"},
    "majicmix-real-15":  {"id": "civitai:43331@94640", "name": "majicMIX realistic 麦橘写实", "price": "~$0.003/张"},
    "realcartoon3d-15":  {"id": "civitai:94809@1409849", "name": "RealCartoon3D", "price": "~$0.003/张"},
    "aniverse-15":       {"id": "civitai:107842@614262", "name": "AniVerse", "price": "~$0.003/张"},
    "chikmix-15":        {"id": "civitai:9871@59409", "name": "ChikMix", "price": "~$0.003/张"},
    "realcartoon-real-15": {"id": "civitai:97744@671503", "name": "RealCartoon-Realistic", "price": "~$0.003/张"},
    "perfect-world-15":  {"id": "civitai:8281@179446", "name": "Perfect World 完美世界", "price": "~$0.003/张"},
    "majicmix-lux-15":   {"id": "civitai:56967@286238", "name": "majicMIX lux 麦橘辉耀", "price": "~$0.003/张"},
    "dark-sushi-25d-15": {"id": "civitai:48671@141866", "name": "Dark Sushi 2.5D 大颗寿司2.5D", "price": "~$0.003/张"},
    "guofeng-wuxia-15":  {"id": "civitai:95643@219960", "name": "国风武侠 Chosen Chinese", "price": "~$0.003/张"},
    "tastyrice-cg-15":   {"id": "civitai:207481@348685", "name": "TastyRice-CG国风MIX", "price": "~$0.003/张"},
    "onlyrealistic-15":  {"id": "civitai:112756@139087", "name": "OnlyRealistic 《唯》超高清真人写实", "price": "~$0.003/张"},
    "chilloutmix-15":    {"id": "civitai:6424@11745", "name": "ChilloutMix", "price": "~$0.003/张"},
    "chosen-mix-15":     {"id": "civitai:17148@125302", "name": "chosen-mix", "price": "~$0.003/张"},
    "abyss-orange-mix-15": {"id": "civitai:4449@5036", "name": "AbyssOrangeMix2 NSFW", "price": "~$0.003/张"},
    "aom3-15":            {"id": "civitai:9942@17233", "name": "AbyssOrangeMix3 AOM3", "price": "~$0.003/张"},
    "wanxiang-anything-15": {"id": "civitai:9409@90854", "name": "万象熔炉 Anything XL", "price": "~$0.003/张"},
    "lazymix-15":         {"id": "civitai:10961@300972", "name": "LazyMix+ Real Amateur Nudes", "price": "~$0.003/张"},
    "aom2-hardcore-15":   {"id": "civitai:4451@5038", "name": "AbyssOrangeMix2 Hardcore", "price": "~$0.003/张"},
    "dark-sushi-mix-15":  {"id": "civitai:24779@93208", "name": "Dark Sushi Mix 大颗寿司", "price": "~$0.003/张"},
    "realisian-15":       {"id": "civitai:47130@325142", "name": "Realisian", "price": "~$0.003/张"},
    "anyhentai-15":       {"id": "civitai:5706@41233", "name": "AnyHentai", "price": "~$0.003/张"},
    "majicmix-sombre-15": {"id": "civitai:62778@75209", "name": "majicMIX sombre 麦橘唯美", "price": "~$0.003/张"},
    "realcartoon-anime-15": {"id": "civitai:96629@359428", "name": "RealCartoon-Anime", "price": "~$0.003/张"},
    "fantexi-15":         {"id": "civitai:18427@95199", "name": "Fantexi v0.9Beta", "price": "~$0.003/张"},
    "orangechillmix-15":  {"id": "civitai:9486@129974", "name": "OrangeChillMix", "price": "~$0.003/张"},
    "camelliamix-15":     {"id": "civitai:44219@161429", "name": "CamelliaMix 2.5D", "price": "~$0.003/张"},
    "astranime-15":       {"id": "civitai:248011@334482", "name": "AstrAnime", "price": "~$0.003/张"},
    "kawaii-anime-mix-15": {"id": "civitai:104100@837260", "name": "Kawaii Realistic Anime Mix", "price": "~$0.003/张"},
    "kakarot-28d-15":     {"id": "civitai:182723@458684", "name": "Kakarot 2.8D", "price": "~$0.003/张"},
    "majicmix-reverie-15": {"id": "civitai:65055@69687", "name": "majicMIX reverie 麦橘梦幻", "price": "~$0.003/张"},
    "majicmix-horror-15": {"id": "civitai:49216@53806", "name": "majicMIX horror 麦橘恐怖", "price": "~$0.003/张"},
    "wai-realmix-pony":   {"id": "civitai:393905@868204", "name": "WAI-REALMIX (Pony)", "price": "~$0.003/张"},
    "wai-ani-hentai-pony": {"id": "civitai:553648@952743", "name": "WAI-ANI-HENTAI-PONYXL", "price": "~$0.003/张"},
    "realcartoon-pony":   {"id": "civitai:618329@1367762", "name": "RealCartoon-Pony", "price": "~$0.003/张"},
    "nwsj-real-mix-sdxl":  {"id": "civitai:125026@136555", "name": "NwsjRealMix SDXL", "price": "~$0.003/张"},
}

# Aspect ratio → (width, height)
ASPECT_MAP = {
    "16:9": (1024, 768),
    "9:16": (768, 1024),
    "1:1":  (1024, 1024),
    "3:2":  (1152, 768),
    "2:3":  (768, 1152),
    "4:3":  (1088, 832),
    "3:4":  (832, 1088),
}

API_URL = "https://api.runware.ai/v1"


def _upload_image(api_key: str, data_uri: str) -> str:
    """Upload image to Runware, return imageUUID for use with seedImage."""
    payload = [{
        "taskType": "imageUpload",
        "taskUUID": str(uuid.uuid4()),
        "image": data_uri,
    }]
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        API_URL, data=data,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"❌ Runware imageUpload failed: {body[:300]}")
        sys.exit(1)

    upload_data = result.get("data", [])
    if not upload_data or not upload_data[0].get("imageUUID"):
        print(f"❌ Runware upload no imageUUID")
        sys.exit(1)
    return upload_data[0]["imageUUID"]


def generate(prompt: str, *, model_key: str = "flux-dev",
             negative_prompt: str = "", image_path: str = None,
             strength: float = 0.8, lora_id: str = None,
             lora_scale: float = 0.8, seed: int = None,
             aspect: str = "9:16", cfg_scale: float = None,
             steps: int = 35, sampler: str = None,
             width: int = None, height: int = None) -> Path:
    """Generate image via Runware AI."""
    api_key = get_key("RUNWARE_API_KEY")

    if model_key not in MODELS:
        print(f"❌ Unknown model: {model_key}")
        print(f"   Available: {', '.join(MODELS.keys())}")
        sys.exit(1)

    model_info = MODELS[model_key]
    model_id = model_info["id"]
    is_qwen = (model_key == "qwen-edit")

    print(f"🎨 Runware: {model_info['name']} ({model_info['price']})")
    print(f"📝 Prompt: {prompt[:120]}{'...' if len(prompt) > 120 else ''}")

    if width and height:
        w, h = width, height
    else:
        w, h = ASPECT_MAP.get(aspect, (1024, 768))

    task = {
        "taskType": "imageInference",
        "taskUUID": str(uuid.uuid4()),
        "model": model_id,
        "positivePrompt": prompt,
        "negativePrompt": negative_prompt or "ugly, deformed, bad anatomy",
        "width": w,
        "height": h,
        "steps": steps,
        "CFGScale": cfg_scale if cfg_scale is not None else (7.0 if model_key in ("dreamshaper-15", "majicmix-real-15", "realcartoon3d-15", "aniverse-15", "chikmix-15", "realcartoon-real-15", "perfect-world-15", "majicmix-lux-15", "dark-sushi-25d-15", "guofeng-wuxia-15", "tastyrice-cg-15", "onlyrealistic-15") else 6.0 if model_key in ("pony-xl", "pony-real", "prefect-ill-xl", "guofeng4-xl", "pornmaster", "sdxl-vanilla", "dreamshaper-xl", "juggernaut-xl", "lustify", "fantasy-reality-xl") else 3.5),
        "safety": {"checkContent": False},
        "outputFormat": "PNG",
        "includeCost": True,
        "numberResults": 1,
    }
    if seed is not None:
        task["seed"] = seed

    # Image-to-image: two-step flow for Runware (non-Qwen)
    if image_path:
        img_data = Path(image_path).read_bytes()
        mime = "image/png" if str(image_path).endswith(".png") else "image/jpeg"
        b64 = base64.b64encode(img_data).decode()
        data_uri = f"data:{mime};base64,{b64}"

        if is_qwen:
            # Qwen uses referenceImages (direct data URI), not seedImage
            task["referenceImages"] = [data_uri]
        else:
            image_uuid = _upload_image(api_key, data_uri)
            task["seedImage"] = image_uuid
            task["strength"] = strength
            print(f"🖼️  Reference: {Path(image_path).name} (UUID={image_uuid[:12]}..., strength={strength})")

    # LoRA — supports single or comma-separated multiple IDs
    # Formats:
    #   lora_id="civitai:667086@746602"  lora_scale=1.0
    #   lora_id="civitai:667086@746602,civitai:888235@501154"  lora_scale="1.0,0.6"
    #   lora_id="civitai:667086@746602,civitai:888235@501154"  lora_scale=0.8  (same scale for all)
    if lora_id:
        ids = [x.strip() for x in lora_id.split(",") if x.strip()]
        if isinstance(lora_scale, str):
            scales = [float(x.strip()) for x in lora_scale.split(",") if x.strip()]
            if len(scales) == 1 and len(ids) > 1:
                scales = scales * len(ids)
            elif len(scales) < len(ids):
                scales += [0.8] * (len(ids) - len(scales))
        else:
            scales = [lora_scale] * len(ids)

        task["lora"] = [{"model": mid, "weight": s}
                        for mid, s in zip(ids, scales[:len(ids)])]
        for mid, s in zip(ids, scales[:len(ids)]):
            print(f"🔗 LoRA: {mid} (scale={s})")

    if sampler:
        task["scheduler"] = sampler

    result = http_post(API_URL, [task], api_key, auth_prefix="Bearer")

    data_list = result.get("data", [])
    if not data_list:
        errors = result.get("errors", [])
        if errors:
            print(f"❌ Runware error: {errors[0].get('message', errors)}")
        else:
            print(f"❌ No data in response")
        sys.exit(1)

    img_url = data_list[0].get("imageURL", "")
    if not img_url:
        print(f"❌ No imageURL in response")
        sys.exit(1)

    cost = data_list[0].get("cost", "?")
    used_seed = data_list[0].get("seed", seed)
    print(f"💰 Cost: ${cost}  🎲 Seed: {used_seed}")

    img_data = download_bytes(img_url)
    out = save_image(img_data, prefix=f"runware_{model_key}_{used_seed}",
                     prompt=prompt, model=model_info["name"],
                     seed=used_seed, lora_id=lora_id)
    return out, used_seed
