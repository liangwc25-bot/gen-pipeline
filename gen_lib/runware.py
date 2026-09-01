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


def _default_cfg(model_key):
    """Default CFG by model family. Flux=3, ZIT=1, SD1.5=7, else (Pony/Illu/SDXL)=6."""
    if model_key.startswith("flux-") or model_key.endswith("-flux"):
        return 3.0
    if model_key.startswith("zimage-") or model_key == "persona-zit":
        return 1.0
    if model_key.endswith("-15"):
        return 7.0
    return 6.0


MODELS = {
    "flux-dev":       {"id": "runware:101@1", "name": "FLUX.1-dev", "price": "$0.0013/张"},
    "flux-schnell":   {"id": "bfl:1@1", "name": "FLUX Schnell", "price": "$0.0023/张"},
    "flux-uncensored":  {"id": "loraimagegen:11111@11111","name": "Fluxedup NSFW",        "price": "$0.0038/张"},
    "flux-ultrareal":   {"id": "khialmaster:978314@1413433", "name": "UltraReal Fine-Tune v4", "price": "~$0.003/张"},
    "flux-artsy-dream": {"id": "civitai:870948@1213649", "name": "Artsy Dream v6 (FP16)", "price": "~$0.003/张"},
    "flux-artsy-vibe":  {"id": "civitai:1162948@1308807", "name": "Artsy Vibe v1 (FP16)", "price": "~$0.003/张"},
    "flux-nepotism":    {"id": "civitai:618792@1326315", "name": "Nepotism XI (DiT)", "price": "~$0.003/张"},
    "flux-blue-pencil": {"id": "civitai:722776@808159", "name": "blue_pencil-flux1 v0.1.0", "price": "~$0.003/张"},
    "flux-fluximation": {"id": "civitai:652994@730546", "name": "Fluximation v1", "price": "~$0.003/张"},
    "flux-2-pro":     {"id": "bfl:5@1", "name": "FLUX.2 Pro", "price": "$0.045/张"},
    # FLUX 1D community checkpoints (Runware cached, probed 2026-08-09)
    "iniverse-mix-flux":   {"id": "civitai:226533@973626", "name": "iNiverse Mix(SFW & NSFW)", "price": "~$0.0038/张"},
    "lah-mysterious-flux": {"id": "civitai:118441@872820", "name": "[Lah] Mysterious", "price": "~$0.0038/张"},
    "khialmaster-flux":    {"id": "khialmaster:978314@1413433", "name": "khialmaster", "price": "~$0.0038/张"},
    "c4pacitor-flux":      {"id": "civitai:694493@1123235", "name": "C4PACITOR", "price": "~$0.0038/张"},
    "asian-flux":          {"id": "civitai:672618@752959", "name": "Flux.1[dev]Asian", "price": "~$0.0038/张"},
    "animeasy-flux":       {"id": "civitai:853344@954733", "name": "AnimEasy Flux", "price": "~$0.0038/张"},
    "myhuman-flux":        {"id": "civitai:775057@989443", "name": "MYHuman-墨幽随拍-Flux", "price": "~$0.0038/张"},
    "redcraft-flux":       {"id": "civitai:958009@1387169", "name": "RedCraft | 红潮2 | 赤佬3 Scaled 加速", "price": "~$0.0038/张"},
    "getphat-flux":       {"id": "civit:861840@1806987", "name": "getPhat v7", "price": "~$0.0038/张"},
    "pony":           {"id": "runware:777@1", "name": "Pony V7 (AuraFlow)", "price": "~$0.005/张"},
    "sdxl":           {"id": "runware:100@1", "name": "SDXL", "price": "~$0.003/张"},
    "pony-xl":        {"id": "liangwc:3@1", "name": "Prefect Pony XL v3", "price": "$0.0013/张"},
    "pony-real":      {"id": "civitai:477851@695106", "name": "DucHaiten-Pony-Real", "price": "$0.0006/张"},
    "prefect-ill-xl": {"id": "liangwc:6@1", "name": "Prefect Illustrious XL v8", "price": "~$0.003/张"},
    "guofeng4-xl":    {"id": "liangwc:guofeng4-xl@1", "name": "国风4 GuoFeng4 XL", "price": "~$0.003/张"},
    "pornmaster":     {"id": "liangwc:pornmaster@1", "name": "PornMaster-色情大师", "price": "~$0.003/张"},
    "lustify":        {"id": "hassakuxl:573152@2155386", "name": "LUSTIFY SDXL", "price": "~$0.003/张"},
    "sdxl-vanilla":   {"id": "liangwc:sdxl-vanilla@1", "name": "SDXL Vanilla 1.0", "price": "~$0.003/张"},
    "xuer-cyan-xl":   {"id": "civitai:416205@594394", "name": "XUER 一青十色", "price": "~$0.003/张"},
    "red-blue-fantasy-pony": {"id": "liangwc:red-blue-fantasy-ckpt@992725", "name": "绪儿-红蓝幻想 (Pony)", "price": "~$0.003/张"},
    "dreamshaper-xl": {"id": "civitai:112902@121931", "name": "DreamShaper XL", "price": "~$0.003/张"},
    "juggernaut-xl":  {"id": "rundiffusion:133005@288982", "name": "JuggernautXL V8", "price": "~$0.003/张"},
    "qwen-edit":      {"id": "runware:108@20", "name": "Qwen-Image-Edit", "price": "~$0.0019/张", "i2i": "ref"},
    "qwen-edit-plus": {"id": "runware:108@22", "name": "Qwen-Image-Edit-Plus", "price": "~$0.0064/张", "i2i": "ref"},
    "flux-klein":     {"id": "runware:400@2", "name": "FLUX.2 [klein] 9B", "price": "~$0.00078/张", "i2i": "ref"},
    "fantasy-reality-xl": {"id": "civitai:230569@260218", "name": "Fantasy Reality Fusion XL", "price": "~$0.003/张"},
    "hoj-illustrious-xl": {"id": "liangwc:hoj-illustrious-xl@2384232", "name": "(HoJ) High on Juice - Semi-realistic IllustriousXL v4.0c", "price": "~$0.003/张"},
    "ponymature-pony": {"id": "liangwc:ponymature-ponyeclipse@477658", "name": "Ponymature SDXL PonyEclipse 1.0", "price": "~$0.003/张"},
    "speciosa-25d": {"id": "liangwc:speciosa-25d@634767", "name": "Speciosa 2.5D v1.2 (Pony)", "price": "~$0.003/张"},
    "speciosa-realistica": {"id": "liangwc:speciosa-realistica@1379842", "name": "Speciosa Realistica v1.2b (Pony)", "price": "~$0.003/张"},
    "speciosa-anime": {"id": "liangwc:speciosa-anime@1416220", "name": "Speciosa Anime v1.5 (Pony)", "price": "~$0.003/张"},
    "dreamisoa-remix": {"id": "liangwc:dreamisoa-remix@3178577", "name": "Dreamisoa_remix SemiReal v2 EVO (Pony)", "price": "~$0.003/张"},
    "wicked-pony-mix": {"id": "liangwc:wicked-pony-mix@1317288", "name": "Wicked Pony Mix v2.1 (Pony)", "price": "~$0.003/张"},
    "bemypony-photo4": {"id": "liangwc:bemypony-photo4@973878", "name": "BeMyPony Photo4 (Pony)", "price": "~$0.003/张"},
    "magicalpony": {"id": "liangwc:magicalpony@713992", "name": "MagicalPony3 (Pony)", "price": "~$0.003/张"},
    "pinkiepie-pony-mix": {"id": "liangwc:pinkiepie-pony-mix@1159818", "name": "PinkiePie pony mix v3.6 Fp16 (Pony)", "price": "~$0.003/张"},
    "dreamisoa-anime": {"id": "liangwc:dreamisoa-anime@3152606", "name": "Dreamisoa_remix_anime v3 EVO (Pony)", "price": "~$0.003/张"},
    "zimage-alibaba": {"id": "runware:z-image@turbo", "name": "Alibaba Z-Image-Turbo", "price": "$0.0006/张"},
    "zimage-moody":   {"id": "persona:620406@2745677", "name": "Moody Pro Mix (Z-Image)", "price": "$0.0013/张"},
    "zimage-stable-yogi": {"id": "liangwc:zimage-turbo-stable-yogi@3096324", "name": "Zimage Turbo by Stable Yogi (2603 Fp8)", "price": "~$0.0013/张"},
    "zimage-ultimate-nsfw": {"id": "liangwc:zimage-ultimate-nsfw@2827368", "name": "Z Image Ultimate NSFW Unlock Turbo v2.0", "price": "~$0.0013/张"},
    "zimage-turbo-anime": {"id": "liangwc:zimage-turbo-anime@2741210", "name": "Z-Image-Turbo Anime V2 Fp8", "price": "~$0.0013/张"},
    "zimage-visionary-nsfw": {"id": "liangwc:zit-visionary-nsfw@2565655", "name": "Z-ImageTurbo VISIONARY NSFW (ZIT-fp8)", "price": "~$0.0013/张"},
    "zimage-tinzit-anime": {"id": "liangwc:tinzit-anime-fp8@3044495", "name": "TinZIT-ANIME-FP8 4steps 完全二次元", "price": "~$0.0013/张"},
    "zimage-lau-anime": {"id": "liangwc:zanimimage-turbo-lau@2540933", "name": "z_animimage_turbo_by_Lau (semi-real bf16)", "price": "~$0.0013/张"},
    "zimage-komposto-ani": {"id": "liangwc:komposto-zit-ani@2485111", "name": "Komposto ZIT_ANI (fp8)", "price": "~$0.0013/张"},
    "zimage-pornmaster-v35": {"id": "liangwc:zimage-pornmaster-v35-bf16@2903129", "name": "PornMaster 色情大师 Z-Image (Turbo V3.5 BF16)", "price": "~$0.0013/张"},
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
    "wai-ani-pony":       {"id": "civitai:404154@1767402", "name": "WAI-ANI-PONYXL", "price": "~$0.003/张"},
    "nova-anime-pony":    {"id": "civitai:376130@994669", "name": "Nova Anime XL", "price": "~$0.003/张"},
    "nova-reality-pony":  {"id": "civitai:453428@1028683", "name": "Nova Reality XL", "price": "~$0.003/张"},
    "atomix-anime-pony":  {"id": "civitai:340158@608850", "name": "Atomix Pony Anime XL", "price": "~$0.003/张"},
    "redcraft-pony":      {"id": "civitai:958009@1484125", "name": "RedCraft 红潮2", "price": "~$0.003/张"},
    "the-deep-dark-pony": {"id": "civitai:221751@634653", "name": "The Deep Dark", "price": "~$0.003/张"},
    "honey-mix-pony":     {"id": "civitai:644900@721415", "name": "Honey Mix High Contrast Anime", "price": "~$0.003/张"},
    "nova-asian-pony":    {"id": "civitai:641919@1076213", "name": "Nova Asian XL", "price": "~$0.003/张"},
    "powerpuffmix-pony":  {"id": "civitai:805817@1162963", "name": "PowerPuffMix", "price": "~$0.003/张"},
    "wai-semireal-pony":  {"id": "civitai:617553@816062", "name": "WAI-SemiReal", "price": "~$0.003/张"},
    "wai-c-pony":         {"id": "civitai:440170@788376", "name": "WAI-C", "price": "~$0.003/张"},
    "atomix-3d-pony":     {"id": "civitai:469465@522337", "name": "Atomix Pony 3D XL", "price": "~$0.003/张"},
    "miaomiao-3d-pony":   {"id": "civitai:431957@728705", "name": "MiaoMiao 3D Harem", "price": "~$0.003/张"},
    "powerpuffanimix-pony": {"id": "civitai:869046@972602", "name": "PowerPuffAnimix", "price": "~$0.003/张"},
    "wai-mature-pony":      {"id": "civitai:875816@980452", "name": "WAI-Mature (Pony)", "price": "~$0.003/张"},
    # Illustrious / NoobAI checkpoints (Runware AIR IDs)
    "wai-illustrious":     {"id": "aiki:827184@2883731", "name": "WAI-Illustrious-SDXL", "price": "~$0.003/张"},
    "aoi-164":             {"id": "choosenmodelanime:4438@7355", "name": "Aoi 164 Character", "price": "~$0.003/张"},
    "cat-citron-anime":    {"id": "choosenmodelanime:131986@1945419", "name": "CAT Citron Anime Treasure", "price": "~$0.003/张"},
    "nova-anime-xl-noob":  {"id": "civitai:376130@1474209", "name": "Nova Anime XL (NoobAI)", "price": "~$0.003/张"},
    "nova-reality-ill":    {"id": "civitai:453428@1478543", "name": "Nova Reality XL (Illustrious)", "price": "~$0.003/张"},
    "miaomiao-harem-ill":  {"id": "civitai:934764@1357881", "name": "MiaoMiao Harem (Illustrious)", "price": "~$0.003/张"},
    "animij-ill":          {"id": "aiki:1353314@2827109", "name": "Animij (Illustrious)", "price": "~$0.003/张"},
    "illustrious-xl-2":    {"id": "imagerouter:1369089@1546777", "name": "Illustrious XL 2.0", "price": "~$0.003/张"},
    "ilustmix-ill":        {"id": "civitai:1110783@1456068", "name": "iLustMix (Illustrious)", "price": "~$0.003/张"},
    "pornmaster-ill":      {"id": "civitai:1045588@1412925", "name": "PornMaster-Pro Illustrious", "price": "~$0.003/张"},
    "pornmaster-anime-ill": {"id": "civitai:1033851@1463869", "name": "PornMaster-Anime NoobXL-V4 (Illustrious)", "price": "~$0.003/张"},
    "matureritual-ill":    {"id": "liangwc:matureritual@2730987", "name": "MatureRitual 熟メス儀式 v204 (Illustrious)", "price": "~$0.003/张"},
    "burgundy-semireal-ill": {"id": "liangwc:burgundy-silk-semireal@3053870", "name": "Burgundy Silk | Asian Semi-Realism 2A (Illustrious)", "price": "~$0.003/张"},
    "burgundy-bimbos-ill":   {"id": "liangwc:burgundy-silk-bimbos@3161087", "name": "Burgundy Silk | Asian Bimbos 2B (Illustrious)", "price": "~$0.003/张"},
    "burgundy-dolls-ill":    {"id": "liangwc:burgundy-silk-dolls@3139629", "name": "Burgundy Silk | Asian Dolls 2B (Illustrious)", "price": "~$0.003/张"},
    "burgundy-milfs-ill":    {"id": "liangwc:burgundy-silk-milfs@3073407", "name": "Burgundy Silk | Asian MILFs 2A (Illustrious)", "price": "~$0.003/张"},
    "miaomiao-mature-ill": {"id": "liangwc:miaomiao-mature@2854190", "name": "MiaoMiao Mature Edition (Illustrious)", "price": "~$0.003/张"},
    "kawaij-ill":          {"id": "civitai:1257951@1434449", "name": "Kawaij (Illustrious)", "price": "~$0.003/张"},
    "nova-orange-ill":     {"id": "civitai:967405@1428332", "name": "Nova Orange XL (Illustrious)", "price": "~$0.003/张"},
    "nova-flat-ill":       {"id": "civitai:1240874@1398523", "name": "Nova Flat XL (Illustrious)", "price": "~$0.003/张"},
    "semilust-ill":        {"id": "civitai:1160480@1449034", "name": "semILust (Illustrious)", "price": "~$0.003/张"},
    "persona-zit":         {"id": "persona:242173@2788849", "name": "Dark Beast 黑兽3.0 (ZIT)", "price": "~$0.003/张"},
    # ZIT checkpoints (Runware AIR IDs)
}

# ── FLUX 家族 (single-interface tab) — Runware-served, per-model param quirks ──
# cfg/steps/neg: None = param not supported by that model (must NOT be sent to Runware)
FLUX_FAMILY = [
    {"key": "flux-schnell",       "id": "runware:100@1",       "name": "FLUX.1 [schnell]",   "cfg": 3.5, "steps": 4,  "neg": True,  "price": "~$0.001/张"},
    {"key": "flux-dev",           "id": "runware:101@1",       "name": "FLUX.1 [dev]",       "cfg": 3.5, "steps": 20, "neg": True,  "price": "~$0.003/张"},
    {"key": "flux-ultra",         "id": "bfl:2@2",             "name": "FLUX.1.1 [pro] Ultra", "cfg": None, "steps": None, "neg": False, "raw": True, "price": "~$0.04/张"},
    {"key": "flux2-klein",        "id": "runware:400@2",       "name": "FLUX.2 [klein] 9B",  "cfg": 3.5, "steps": 20, "neg": True,  "price": "~$0.00078/张"},
    {"key": "flux2-max",          "id": "bfl:7@1",             "name": "FLUX.2 [max]",       "cfg": None, "steps": None, "neg": False, "price": "~$0.03/张"},
    {"key": "juggernaut-pro-flux","id": "rundiffusion:130@100","name": "Juggernaut Pro Flux","cfg": 3.5, "steps": 20, "neg": True,  "price": "~$0.003/张"},
]
FLUX_FAMILY_KEYS = [m["key"] for m in FLUX_FAMILY]

# FLUX Ultra (bfl:2@2) only accepts these exact dimensions
FLUX_ULTRA_DIMS = {
    "16:9": (2752, 1536), "9:16": (1536, 2752), "1:1": (2048, 2048),
    "3:2": (2496, 1664), "2:3": (1664, 2496),
    "4:3": (2368, 1792), "3:4": (1792, 2368),
}

# Aspect ratio → (width, height) — ALL values % 64 == 0 (Runware requirement)
ASPECT_MAP = {
    "16:9": (1216, 704),
    "9:16": (704, 1216),
    "1:1":  (1024, 1024),
    "3:2":  (1152, 768),
    "2:3":  (768, 1152),
    "4:3":  (1024, 768),
    "3:4":  (768, 1024),
}
ASPECT_MAP_SD15 = {
    "16:9": (768, 448),
    "9:16": (448, 768),
    "1:1":  (512, 512),
    "3:2":  (768, 512),
    "2:3":  (512, 768),
    "4:3":  (704, 512),
    "3:4":  (512, 704),
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
    # i2i param mode: 'ref' = referenceImages (instruction editing), 'seed' = seedImage (traditional)
    i2i_mode = model_info.get("i2i", "seed")

    print(f"🎨 Runware: {model_info['name']} ({model_info['price']})")
    print(f"📝 Prompt: {prompt[:120]}{'...' if len(prompt) > 120 else ''}")

    if width and height:
        w, h = width, height
    else:
        is_sd15 = model_key.endswith("-15")
        amap = ASPECT_MAP_SD15 if is_sd15 else ASPECT_MAP
        w, h = amap.get(aspect, (512, 768) if is_sd15 else (672, 1184))

    task = {
        "taskType": "imageInference",
        "taskUUID": str(uuid.uuid4()),
        "model": model_id,
        "positivePrompt": prompt,
        "negativePrompt": negative_prompt or "ugly, deformed, bad anatomy",
        "width": w,
        "height": h,
        "steps": steps,
        "CFGScale": cfg_scale if cfg_scale is not None else _default_cfg(model_key),
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

        if i2i_mode == "ref":
            # Instruction-editing models (Qwen-Edit, FLUX.2 klein): direct data URI
            task["referenceImages"] = [data_uri]
        else:
            # Traditional i2i (ZIT, FLUX Kontext): upload then seedImage + strength
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


def generate_flux_family(prompt: str, *, model_key: str = "flux-dev",
                         negative_prompt: str = "", seed: int = None,
                         aspect: str = "9:16", cfg_scale: float = None,
                         steps: int = None, width: int = None,
                         height: int = None, raw: bool = None) -> tuple:
    """Generate via the FLUX 家族 tab (single interface).

    All 6 models are Runware-served AIR IDs, but with per-model param quirks:
      - flux-ultra (bfl:2@2, FLUX Ultra): no CFGScale, no steps, fixed resolutions
      - flux2-max  (bfl:7@1, FLUX.2 max): no CFGScale, no steps, no negativePrompt
    The task payload only includes params the selected model supports.
    """
    api_key = get_key("RUNWARE_API_KEY")

    info = next((m for m in FLUX_FAMILY if m["key"] == model_key), None)
    if not info:
        raise ValueError(f"Unknown FLUX family model: {model_key}")

    model_id = info["id"]

    # Resolution
    if width and height:
        w, h = width, height
    elif info["key"] == "flux-ultra":
        w, h = FLUX_ULTRA_DIMS.get(aspect, (1536, 2752))
    else:
        w, h = ASPECT_MAP.get(aspect, (704, 1216))

    print(f"🌊 Flux 家族: {info['name']} ({info['price']})  {w}x{h}")
    print(f"📝 Prompt: {prompt[:120]}{'...' if len(prompt) > 120 else ''}")

    task = {
        "taskType": "imageInference",
        "taskUUID": str(uuid.uuid4()),
        "model": model_id,
        "positivePrompt": prompt,
        "width": w,
        "height": h,
        "safety": {"checkContent": False},
        "outputFormat": "PNG",
        "includeCost": True,
        "numberResults": 1,
    }
    if info["steps"] is not None:
        task["steps"] = steps if steps else info["steps"]
    if info["cfg"] is not None:
        task["CFGScale"] = cfg_scale if cfg_scale is not None else info["cfg"]
    if info["neg"]:
        task["negativePrompt"] = negative_prompt or "ugly, deformed, bad anatomy"
    if seed is not None:
        task["seed"] = seed
    # raw (natural/less-processed) — only Ultra/Max support it
    if info.get("raw") and raw is not None:
        task["raw"] = raw

    result = http_post(API_URL, [task], api_key, auth_prefix="Bearer")

    data_list = result.get("data", [])
    if not data_list:
        errors = result.get("errors", [])
        if errors:
            print(f"❌ Runware error: {errors[0].get('message', errors)}")
        else:
            print("❌ No data in response")
        raise RuntimeError("Runware returned no image")

    img_url = data_list[0].get("imageURL", "")
    if not img_url:
        raise RuntimeError("No imageURL in response")

    cost = data_list[0].get("cost", "?")
    used_seed = data_list[0].get("seed", seed)
    print(f"💰 Cost: ${cost}  🎲 Seed: {used_seed}")

    img_data = download_bytes(img_url)
    out = save_image(img_data, prefix=f"runware_{model_key}_{used_seed}",
                     prompt=prompt, model=info["name"],
                     seed=used_seed, lora_id=None)
    return out, used_seed

