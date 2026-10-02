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
    """Default CFG by model family. Flux=3, ZIT=1, SD1.5=7, else (Pony/Illu/SDXL)=5 (2026-10-02 定)."""
    if model_key.startswith("flux-") or model_key.endswith("-flux"):
        return 3.0
    if model_key.startswith("zimage-") or model_key == "persona-zit" or model_key == "diving-zit":
        return 1.0
    if model_key.endswith("-15"):
        return 7.0
    return 5.0


MODELS = {
    "flux-dev":       {"id": "runware:101@1", "name": "FLUX.1-dev", "price": "$0.0013/张", "base": "flux"},
    "flux-schnell":   {"id": "bfl:1@1", "name": "FLUX Schnell", "price": "$0.0023/张", "base": "flux"},
    "flux-uncensored":  {"id": "loraimagegen:11111@11111","name": "Fluxedup NSFW",        "price": "$0.0038/张", "base": "flux"},
    "flux-ultrareal":   {"id": "khialmaster:978314@1413433", "name": "UltraReal Fine-Tune v4", "price": "~$0.003/张", "base": "flux"},
    "flux-artsy-dream": {"id": "civitai:870948@1213649", "name": "Artsy Dream v6 (FP16)", "creator": "jurdn", "price": "~$0.003/张", "base": "flux"},
    "flux-artsy-vibe":  {"id": "civitai:1162948@1308807", "name": "Artsy Vibe v1 (FP16)", "creator": "jurdn", "price": "~$0.003/张", "base": "flux"},
    "flux-nepotism":    {"id": "civitai:618792@1326315", "name": "Nepotism XI (DiT)", "creator": "BobsBlazed", "price": "~$0.003/张", "base": "flux"},
    "flux-blue-pencil": {"id": "civitai:722776@808159", "name": "blue_pencil-flux1 v0.1.0", "creator": "blue_pen5805", "price": "~$0.003/张", "base": "flux"},
    "flux-fluximation": {"id": "civitai:652994@730546", "name": "Fluximation v1", "creator": "Aikimi", "price": "~$0.003/张", "base": "flux"},
    "flux-2-pro":     {"id": "bfl:5@1", "name": "FLUX.2 Pro", "price": "$0.045/张", "base": "flux"},
    # FLUX 1D community checkpoints (Runware cached, probed 2026-08-09)
    "iniverse-mix-flux":   {"id": "civitai:226533@973626", "name": "iNiverse Mix(SFW & NSFW)", "creator": "JinnGames", "price": "~$0.0038/张", "base": "flux"},
    "lah-mysterious-flux": {"id": "civitai:118441@872820", "name": "[Lah] Mysterious", "creator": "Lah_Inthe_Futureland", "price": "~$0.0038/张", "base": "flux"},
    "khialmaster-flux":    {"id": "khialmaster:978314@1413433", "name": "khialmaster", "price": "~$0.0038/张", "base": "flux"},
    "c4pacitor-flux":      {"id": "civitai:694493@1123235", "name": "C4PACITOR", "creator": "c0ur4ge", "price": "~$0.0038/张", "base": "flux"},
    "asian-flux":          {"id": "civitai:672618@752959", "name": "Flux.1[dev]Asian", "creator": "fok3827", "price": "~$0.0038/张", "base": "flux"},
    "animeasy-flux":       {"id": "civitai:853344@954733", "name": "AnimEasy Flux", "creator": "Master_Zed", "price": "~$0.0038/张", "base": "flux"},
    "myhuman-flux":        {"id": "civitai:775057@989443", "name": "MYHuman-墨幽随拍-Flux", "creator": "MoYou", "price": "~$0.0038/张", "base": "flux"},
    "redcraft-flux":       {"id": "civitai:958009@1387169", "name": "RedCraft | 红潮2 | 赤佬3 Scaled 加速", "creator": "AiMetatron", "price": "~$0.0038/张", "base": "flux"},
    "getphat-flux":       {"id": "civit:861840@1806987", "name": "getPhat v7", "creator": "getphat", "price": "~$0.0038/张", "base": "flux"},
    "pony":           {"id": "runware:777@1", "name": "Pony V7 (AuraFlow)", "price": "~$0.005/张", "base": "pony"},
    "sdxl":           {"id": "runware:100@1", "name": "SDXL", "price": "~$0.003/张", "base": "sdxl"},
    "pony-xl":        {"id": "liangwc:3@1", "name": "Prefect Pony XL v3", "price": "$0.0013/张", "base": "pony"},
    "pony-real":      {"id": "civitai:477851@695106", "name": "DucHaiten-Pony-Real", "creator": "DucHaiten", "price": "$0.0006/张", "base": "pony"},
    "prefect-ill-xl": {"id": "liangwc:6@1", "name": "Prefect Illustrious XL v8", "price": "~$0.003/张", "base": "illustrious"},
    "guofeng4-xl":    {"id": "liangwc:guofeng4-xl@1", "name": "国风4 GuoFeng4 XL", "price": "~$0.003/张", "base": "sdxl"},
    "pornmaster":     {"id": "liangwc:pornmaster@1", "name": "PornMaster-色情大师", "price": "~$0.003/张", "base": "sdxl"},
    "lustify":        {"id": "hassakuxl:573152@2155386", "name": "LUSTIFY SDXL", "creator": "coyotte", "price": "~$0.003/张", "base": "sdxl"},
    "sdxl-vanilla":   {"id": "liangwc:sdxl-vanilla@1", "name": "SDXL Vanilla 1.0", "price": "~$0.003/张", "base": "sdxl"},
    "xuer-cyan-xl":   {"id": "civitai:416205@594394", "name": "XUER 一青十色", "creator": "XUERYCJ", "price": "~$0.003/张", "base": "sdxl"},
    "red-blue-fantasy-pony": {"id": "liangwc:red-blue-fantasy-ckpt@992725", "name": "绪儿-红蓝幻想 (Pony)", "creator": "XUERYCJ", "price": "~$0.003/张", "base": "pony"},
    "dreamshaper-xl": {"id": "civitai:112902@121931", "name": "DreamShaper XL", "creator": "Lykon", "price": "~$0.003/张", "base": "sdxl"},
    "juggernaut-xl":  {"id": "rundiffusion:133005@288982", "name": "JuggernautXL V8", "creator": "KandooAI", "price": "~$0.003/张", "base": "sdxl"},
    "qwen-edit":      {"id": "runware:108@20", "name": "Qwen-Image-Edit", "creator": "PublicPrompts", "price": "~$0.0019/张", "i2i": "ref"},
    "qwen-edit-plus": {"id": "runware:108@22", "name": "Qwen-Image-Edit-Plus", "price": "~$0.0064/张", "i2i": "ref"},
    "flux-klein":     {"id": "runware:400@2", "name": "FLUX.2 [klein] 9B", "creator": "jinofcoolnes", "price": "~$0.00078/张", "i2i": "ref", "base": "flux"},
    "fantasy-reality-xl": {"id": "civitai:230569@260218", "name": "Fantasy Reality Fusion XL", "creator": "MIAOKA", "price": "~$0.003/张", "base": "sdxl"},
    "hoj-illustrious-xl": {"id": "liangwc:hoj-illustrious-xl@2384232", "name": "(HoJ) High on Juice - Semi-realistic IllustriousXL v4.0c", "creator": "n_Arno", "price": "~$0.003/张", "base": "illustrious"},
    "bismuth-illustrious": {"id": "liangwc:bismuth-illustrious@2897830", "name": "Bismuth Illustrious Mix v8.0", "creator": "Axelros", "price": "~$0.003/张", "base": "illustrious"},
    "red-lily-ill":       {"id": "liangwc:red-lily-ill@2343145", "name": "Red Lily | Illu v1.0", "creator": "Shiiro0", "price": "~$0.003/张", "base": "illustrious"},
    "silene-ill":         {"id": "liangwc:silene-ill@1415266", "name": "Silene Illustrious XL 1.0", "creator": "Shiiro0", "price": "~$0.003/张", "base": "illustrious"},
    "naughtymouse-ill":   {"id": "liangwc:naughtymouse-ill@2907147", "name": "NaughtyMouseMix V10", "creator": "NaughtyMouse", "price": "~$0.003/张", "base": "illustrious"},
    "ra-mix-ill":         {"id": "liangwc:ra-mix-ill@2985291", "name": "RA-Mix v1.0", "creator": "Sexiam", "price": "~$0.003/张", "base": "illustrious"},
    "pearly-opal-ill":    {"id": "liangwc:pearly-opal-ill@2839173", "name": "Pearly Opal Toon mix V2", "creator": "Serephian", "price": "~$0.003/张", "base": "illustrious"},
    "mature-citron-ill":  {"id": "liangwc:mature-citron-sdxl@2760019", "name": "Mature Citron IL (Unstable 3.0)", "creator": "Ziperto", "price": "~$0.003/张", "base": "illustrious"},
    "wai-mature-ill":     {"id": "liangwc:wai-mature-sdxl@3289320", "name": "WAI-Mature-illustrious v3.0", "creator": "WAI0731", "price": "~$0.003/张", "base": "illustrious"},
    "bismuth-mature-ill": {"id": "liangwc:bismuth-mature-sdxl@2798957", "name": "Bismuth Mature Merge Model v3.0", "creator": "20040502wrh789", "price": "~$0.003/张", "base": "illustrious"},
    "mature-female-ill":  {"id": "liangwc:mature-female-sdxl@2300641", "name": "mature_female v1.0", "creator": "rnmd", "price": "~$0.003/张", "base": "illustrious"},
    "mature-milk-ill":    {"id": "liangwc:mature-milk-sdxl@2814428", "name": "Mature Milk MM v1.0", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "kokio-ill":          {"id": "liangwc:kokio-ill@1298658", "name": "Koki'o Illu v2.0", "creator": "Shiiro0", "price": "~$0.003/张", "base": "illustrious"},
    "konbinimix-ill":     {"id": "liangwc:konbinimix-ill@1014358", "name": "KonbiniMix - Illustrious", "creator": "Shiiro0", "price": "~$0.003/张", "base": "illustrious"},
    # Gem Collection by mommymia (8 变体, all Illustrious, 2026-09-09 部署)
    "gem-amethyst-ill":   {"id": "liangwc:gem-amethyst-ill@2379280", "name": "Gem-Amethyst (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "gem-moonstone-ill":  {"id": "liangwc:gem-moonstone-ill@2403224", "name": "Gem-Moonstone (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "gem-proteus-ill":    {"id": "liangwc:gem-proteus-ill@2487621", "name": "Gem-Proteus (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "gem-sapphire-ill":   {"id": "liangwc:gem-sapphire-ill@2565501", "name": "Gem-Sapphire (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "gem-serpentine-ill": {"id": "liangwc:gem-serpentine-ill@2709631", "name": "Gem-Serpentine (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "gem-rose-quartz-ill":{"id": "liangwc:gem-rose-quartz-ill@2896115", "name": "Gem-RoseQuartz (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "gem-opal-ill":       {"id": "liangwc:gem-opal-ill@3192475", "name": "Gem-Opal (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "gem-pearl-ill":      {"id": "liangwc:gem-pearl-ill@3030523", "name": "Gem-Pearl (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    # SDXL9 batch (2026-09-10, all Illustrious)
    "dasiwa-anime-ill":      {"id": "liangwc:dasiwa-anime-ill@3012006", "name": "DaSiWa Illustrious Anime", "creator": "Darksidewalker", "price": "~$0.003/张", "base": "illustrious"},
    "dasiwa-real-ill":       {"id": "liangwc:dasiwa-real-ill@2682302", "name": "DaSiWa Illustrious Realistic", "creator": "Darksidewalker", "price": "~$0.003/张", "base": "illustrious"},
    "phoenix-ill":           {"id": "liangwc:phoenix-ill@3057554", "name": "Phoenix IL v4.0", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "waivete-ill":           {"id": "liangwc:waivete-ill@3223633", "name": "WaiVete V5 v1.0", "creator": "HelgerDD", "price": "~$0.003/张", "base": "illustrious"},
    "a-mix-ill":             {"id": "liangwc:a-mix-ill@1915059", "name": "A-mix [Illustrious]", "creator": "phinjo", "price": "~$0.003/张", "base": "illustrious"},
    "plant-milk-walnut-ill": {"id": "liangwc:plant-milk-walnut-ill@1714002", "name": "Plant Milk-Walnut (Illu)", "creator": "Ocean3", "price": "~$0.003/张", "base": "illustrious"},
    "visionary-ill":         {"id": "liangwc:visionary-ill@1909771", "name": "VISIONARY Illustrious (NEW ERA)", "creator": "VisionaryAI_Studio", "price": "~$0.003/张", "base": "illustrious"},
    "visionary-v3-ill":      {"id": "liangwc:visionary-v3-ill@1919246", "name": "Visionary Illustrious Mix V3", "creator": "VisionaryAI_Studio", "price": "~$0.003/张", "base": "illustrious"},
    "coldmilk-ill":          {"id": "liangwc:coldmilk-ill@3259564", "name": "ColdMilk Illustrious v3.0", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    # Pie Models batch (2026-09-10, mommymia, all Illustrious)
    "pie-cherry-ill":      {"id": "liangwc:pie-cherry-ill@1891751", "name": "Pie-Cherry (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-derby-ill":       {"id": "liangwc:pie-derby-ill@1985550", "name": "Pie-Derby (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-elderberry-ill":  {"id": "liangwc:pie-elderberry-ill@2019688", "name": "Pie-Elderberry (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-fudge-ill":       {"id": "liangwc:pie-fudge-ill@2108004", "name": "Pie-Fudge (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-grape-ill":       {"id": "liangwc:pie-grape-ill@2235514", "name": "Pie-Grape (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-honey-ill":       {"id": "liangwc:pie-honey-ill@2248236", "name": "Pie-Honey (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-impossible-ill":  {"id": "liangwc:pie-impossible-ill@2325846", "name": "Pie-Impossible (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-jam-ill":         {"id": "liangwc:pie-jam-ill@2450907", "name": "Pie-Jam (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-apple-v2-ill":    {"id": "liangwc:pie-apple-v2-ill@2496995", "name": "Pie-Apple v2 (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-keylime-ill":     {"id": "liangwc:pie-keylime-ill@2692143", "name": "Pie-KeyLime (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-lemon-ill":       {"id": "liangwc:pie-lemon-ill@2775592", "name": "Pie-Lemon (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-mango-ill":       {"id": "liangwc:pie-mango-ill@2913030", "name": "Pie-Mango (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-nutella-ill":     {"id": "liangwc:pie-nutella-ill@3009657", "name": "Pie-Nutella (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-oreo-ill":        {"id": "liangwc:pie-oreo-ill@3142094", "name": "Pie-Oreo (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-pecan-ill":       {"id": "liangwc:pie-pecan-ill@3235512", "name": "Pie-Pecan (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "pie-quiche-ill":      {"id": "liangwc:pie-quiche-ill@3301636", "name": "Pie-Quiche (Illu)", "creator": "mommymia", "price": "~$0.003/张", "base": "illustrious"},
    "plant-milk-hemp-ii-ill":       {"id": "liangwc:plant-milk-hemp-ii-ill@1714314", "name": "Plant Milk-Hemp II (Illu)", "creator": "Ocean3", "price": "~$0.003/张", "base": "illustrious"},
    "plant-milk-vanilla-ill":       {"id": "liangwc:plant-milk-vanilla-ill@1547520", "name": "Plant Milk-Vanilla (Illu)", "creator": "Ocean3", "price": "~$0.003/张", "base": "illustrious"},
    "plant-milk-coconut-ill":       {"id": "liangwc:plant-milk-coconut-ill@1549172", "name": "Plant Milk-Coconut (Illu)", "creator": "Ocean3", "price": "~$0.003/张", "base": "illustrious"},
    "plant-milk-almond-ill":        {"id": "liangwc:plant-milk-almond-ill@1494714", "name": "Plant Milk-Almond (Illu)", "creator": "Ocean3", "price": "~$0.003/张", "base": "illustrious"},
    "plant-milk-flax-ill":          {"id": "liangwc:plant-milk-flax-ill@1331188", "name": "Plant Milk-Flax (Illu)", "creator": "Ocean3", "price": "~$0.003/张", "base": "illustrious"},
    "plant-milk-oat-ill":           {"id": "liangwc:plant-milk-oat-ill@1307695", "name": "Plant Milk-Oat (Illu)", "creator": "Ocean3", "price": "~$0.003/张", "base": "illustrious"},
    "vetehine-sinner-ill":          {"id": "liangwc:vetehine-sinner-ill@3248361", "name": "Vetehine-Sinner v0.1 (Illu)", "creator": "Vetehine", "price": "~$0.003/张", "base": "illustrious"},
    "vetehine-crimson-oath-ill":    {"id": "liangwc:vetehine-crimson-oath-ill@3052259", "name": "Vetehine-Crimson OATH v0.2 (Illu)", "creator": "Vetehine", "price": "~$0.003/张", "base": "illustrious"},
    "vetehine-moonstone-ill":       {"id": "liangwc:vetehine-moonstone-ill@3011784", "name": "Vetehine-Moonstone v0.2 (Illu)", "creator": "Vetehine", "price": "~$0.003/张", "base": "illustrious"},
    "vetehine-dreamhex-ill":        {"id": "liangwc:vetehine-dreamhex-ill@3013304", "name": "Vetehine-Dreamhex v5.1 (Illu)", "creator": "Vetehine", "price": "~$0.003/张", "base": "illustrious"},
    "vetehine-divine-toxin-ill":    {"id": "liangwc:vetehine-divine-toxin-ill@2947240", "name": "Vetehine-DivineToxin v3 (Illu)", "creator": "Vetehine", "price": "~$0.003/张", "base": "illustrious"},
    "pleasurechest-v2-ill":         {"id": "liangwc:pleasurechest-v2-ill@2769395", "name": "pleasurechest v2 (Illu)", "creator": "Ereijtic", "price": "~$0.003/张", "base": "illustrious"},
    "tease-n-please-ill":           {"id": "liangwc:tease-n-please-ill@2442626", "name": "tease-n-please α (Illu)", "creator": "Ereijtic", "price": "~$0.003/张", "base": "illustrious"},
    "place2play-no-1-ill":          {"id": "liangwc:place2play-no-1-ill@2392505", "name": "place2play No.1 (Illu)", "creator": "Ereijtic", "price": "~$0.003/张", "base": "illustrious"},
    "anilust-v1-0-ill":             {"id": "liangwc:anilust-v1-0-ill@1168202", "name": "anilust v1.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "morelustrious-v2-0-vae-ill":   {"id": "liangwc:morelustrious-v2-0-vae-ill@1421713", "name": "morelustrious v2.0+VAE (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "reijil-v2-0-ill":              {"id": "liangwc:reijil-v2-0-ill@1362773", "name": "reijil v2.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "illicious-v1-0-ill":           {"id": "liangwc:illicious-v1-0-ill@1410499", "name": "illicious v1.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "anijtoonimic-il-v1-0-ill":     {"id": "liangwc:anijtoonimic-il-v1-0-ill@1435817", "name": "anijtoonimic IL v1.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "iluvorija-v1-0-ill":           {"id": "liangwc:iluvorija-v1-0-ill@1469706", "name": "iluvorija v1.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "nuvijelle-v1-0-ill":           {"id": "liangwc:nuvijelle-v1-0-ill@1637094", "name": "nuvijelle v1.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "ilustreal-v5-0-vae-ill":       {"id": "liangwc:ilustreal-v5-0-vae-ill@1575331", "name": "ilustreal v5.0+VAE (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "anireijl-v1-0-ill":            {"id": "liangwc:anireijl-v1-0-ill@1672279", "name": "anireijl v1.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "dollij-v1-0-ill":              {"id": "liangwc:dollij-v1-0-ill@1738374", "name": "dollij v1.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "aij-v1-0-ill":                 {"id": "liangwc:aij-v1-0-ill@1693974", "name": "aij v1.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "tweenij-v1-0-ill":             {"id": "liangwc:tweenij-v1-0-ill@1716652", "name": "tweenij v1.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "fireflij-v1-0-ill":            {"id": "liangwc:fireflij-v1-0-ill@1742046", "name": "fireflij v1.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "mergeij-pony-il-v4-0-vae-ill": {"id": "liangwc:mergeij-pony-il-v4-0-vae-ill@1745487", "name": "mergeij-pony-il v4.0+VAE (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "keij-no-01-ill":               {"id": "liangwc:keij-no-01-ill@1885003", "name": "keij No.01 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "editijon-k-pop-beta-ill":      {"id": "liangwc:editijon-k-pop-beta-ill@1878651", "name": "editijon-k-pop beta (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "ereijtic-v1-ill":              {"id": "liangwc:ereijtic-v1-ill@1946974", "name": "ereijtic v1 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "myrij-ill":                    {"id": "liangwc:myrij-ill@1970243", "name": "myrij α (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "waijfu-alpha-ill":             {"id": "liangwc:waijfu-alpha-ill@2169147", "name": "waijfu Alpha (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "illustrij-evo-lvl3-ill":       {"id": "liangwc:illustrij-evo-lvl3-ill@2182724", "name": "illustrij-evo LVL3 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "creativitij-v2-2-ill":         {"id": "liangwc:creativitij-v2-2-ill@2281836", "name": "creativitij v2.2 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "aijmore-ill":                  {"id": "liangwc:aijmore-ill@2325513", "name": "aijmore α (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "illustrij-bttr-v1-0-ill":      {"id": "liangwc:illustrij-bttr-v1-0-ill@2331934", "name": "illustrij-bttr v1.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "injoij-v3-ill":                {"id": "liangwc:injoij-v3-ill@2559186", "name": "injoij v3 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "anijed-v1-0-ill":              {"id": "liangwc:anijed-v1-0-ill@2707623", "name": "anijed v1.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "painterlij-1-ill":             {"id": "liangwc:painterlij-1-ill@2749422", "name": "painterlij 1 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "hentaij-1-ill":                {"id": "liangwc:hentaij-1-ill@2777885", "name": "hentaij #1 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "project-r-1-ill":              {"id": "liangwc:project-r-1-ill@2805426", "name": "project-r 1 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "insight-1-ill":                {"id": "liangwc:insight-1-ill@2832979", "name": "insight 1 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "twinlight-v1-ill":             {"id": "liangwc:twinlight-v1-ill@2817831", "name": "twinlight v1 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "illustrij-gen-3-ill":          {"id": "liangwc:illustrij-gen-3-ill@2737444", "name": "illustrij-gen 3 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "better-days-ill":      {"id": "liangwc:better-days-ill@2019115", "name": "Better Days (Illu)", "creator": "killedmyself", "price": "~$0.003/张", "base": "illustrious"},
    "one-obsession-branch-ill": {"id": "liangwc:one-obsession-branch-ill@2702856", "name": "One Obsession Branch (Illu)", "creator": "maxfeifei8", "price": "~$0.003/张", "base": "illustrious"},
    "nova-mature-xl-v4-0-ill": {"id": "liangwc:nova-mature-xl-v4-0-ill@2579194", "name": "Nova Mature XL v4.0 (Illu)", "creator": "Crody", "price": "~$0.003/张", "base": "illustrious"},
    "dutch-v3-0-ill":       {"id": "liangwc:dutch-v3-0-ill@2028237", "name": "Dutch v3.0 (Illu)", "creator": "TheFlyingDutchman", "price": "~$0.003/张", "base": "illustrious"},
    "one-obsession-v24-ill": {"id": "liangwc:one-obsession-v24-ill@3218603", "name": "One Obsession v24 (Illu)", "creator": "maxfeifei8", "price": "~$0.003/张", "base": "illustrious"},
    "posilustrij-v1-0-ill": {"id": "liangwc:posilustrij-v1-0-ill@1262307", "name": "posILustrij v1.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "illustreijl-v2-0-ill": {"id": "liangwc:illustreijl-v2-0-ill@1278876", "name": "IllustreijL v2.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "il-mergeij-v2-0-ill":  {"id": "liangwc:il-mergeij-v2-0-ill@1342115", "name": "IL-mergeij v2.0 (Illu)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "flatiron-anime-riprod-ill": {"id": "liangwc:flatiron-anime-riprod-ill@2624816", "name": "FlatIron Anime RIPROD (Illu)", "creator": "Whistler_ai", "price": "~$0.003/张", "base": "illustrious"},
    "celestreal-v3-0-ill":  {"id": "liangwc:celestreal-v3-0-ill@2550245", "name": "CelestReal v3.0 (Illu)", "creator": "Whistler_ai", "price": "~$0.003/张", "base": "illustrious"},
    "pale-rider-v4-0-ill":  {"id": "liangwc:pale-rider-v4-0-ill@3039900", "name": "AniMayhem Pale Rider v4.0 (Illu)", "creator": "Whistler_ai", "price": "~$0.003/张", "base": "illustrious"},
    "perfectdeliberate-v10-ill": {"id": "liangwc:perfectdeliberate-v10-ill@3187704", "name": "PerfectDeliberate v10 (Illu)", "creator": "Desync", "price": "~$0.003/张", "base": "illustrious"},
    "perfectdeliberate-anime-v5-0-ill": {"id": "liangwc:perfectdeliberate-anime-v5-0-ill@2925672", "name": "PerfectDeliberate-Anime v5.0 (Illu)", "creator": "Desync", "price": "~$0.003/张", "base": "illustrious"},
    "diving-pony":        {"id": "liangwc:divingponyanime@1459310", "name": "Diving-Pony Anime v3.0", "creator": "DivingSuit", "price": "~$0.003/张", "base": "pony"},
    "diving-3d":          {"id": "liangwc:diving3d@2763403", "name": "Diving-Illustrious 3D/CG v3.0", "creator": "DivingSuit", "price": "~$0.003/张", "base": "illustrious"},
    "diving-real":        {"id": "liangwc:divingreal@2490435", "name": "Diving-Illustrious Real-Asian v7.0", "creator": "DivingSuit", "price": "~$0.003/张", "base": "illustrious"},
    "diving-flat":        {"id": "liangwc:divingflat@3001848", "name": "Diving-Illustrious Flat Anime v8.0", "creator": "DivingSuit", "price": "~$0.003/张", "base": "illustrious"},
    "diving-anime":       {"id": "liangwc:divinganime@2939886", "name": "Diving-Illustrious Anime v2.0", "creator": "DivingSuit", "price": "~$0.003/张", "base": "illustrious"},
    "diving-semi-real":   {"id": "liangwc:diving-semireal@1527952", "name": "Diving-Illustrious Semi-Real v1.0", "creator": "DivingSuit", "price": "~$0.003/张", "base": "illustrious"},
    "diving-zit":         {"id": "liangwc:divingzit@3126573", "name": "Diving-Z-Image Turbo v7.0", "creator": "DivingSuit", "price": "~$0.003/张", "base": "zit"},
    "ponymature-pony": {"id": "liangwc:ponymature-ponyeclipse@477658", "name": "Ponymature SDXL PonyEclipse 1.0", "creator": "tkio", "price": "~$0.003/张", "base": "pony"},
    "speciosa-25d": {"id": "liangwc:speciosa-25d@634767", "name": "Speciosa 2.5D v1.2 (Pony)", "price": "~$0.003/张", "base": "pony"},
    "speciosa-realistica": {"id": "liangwc:speciosa-realistica@1379842", "name": "Speciosa Realistica v1.2b (Pony)", "price": "~$0.003/张", "base": "pony"},
    "speciosa-anime": {"id": "liangwc:speciosa-anime@1416220", "name": "Speciosa Anime v1.5 (Pony)", "price": "~$0.003/张", "base": "pony"},
    "dreamisoa-remix": {"id": "liangwc:dreamisoa-remix@3178577", "name": "Dreamisoa_remix SemiReal v2 EVO (Pony)", "creator": "Stoklotka", "price": "~$0.003/张", "base": "pony"},
    "wicked-pony-mix": {"id": "liangwc:wicked-pony-mix@1317288", "name": "Wicked Pony Mix v2.1 (Pony)", "creator": "Axelros", "price": "~$0.003/张", "base": "pony"},
    "bemypony-photo4": {"id": "liangwc:bemypony-photo4@973878", "name": "BeMyPony Photo4 (Pony)", "creator": "0l1v1aR0551", "price": "~$0.003/张", "base": "pony"},
    "magicalpony": {"id": "liangwc:magicalpony@713992", "name": "MagicalPony3 (Pony)", "creator": "0l1v1aR0551", "price": "~$0.003/张", "base": "pony"},
    "pinkiepie-pony-mix": {"id": "liangwc:pinkiepie-pony-mix@1159818", "name": "PinkiePie pony mix v3.6 Fp16 (Pony)", "creator": "mixboy", "price": "~$0.003/张", "base": "pony"},
    "dreamisoa-anime": {"id": "liangwc:dreamisoa-anime@3152606", "name": "Dreamisoa_remix_anime v3 EVO (Pony)", "creator": "Stoklotka", "price": "~$0.003/张", "base": "pony"},
    "konbinimix-pony": {"id": "liangwc:konbinimix-pony@816093", "name": "KonbiniMix Pony/XL v1", "creator": "Shiiro0", "price": "~$0.003/张", "base": "pony"},
    "konbinimix-retro-pony": {"id": "liangwc:konbinimix-retro-pony@827451", "name": "KonbiniMix_Retro Pony/XL v1", "creator": "Shiiro0", "price": "~$0.003/张", "base": "pony"},
    "zimage-base-aio": {"id": "liangwc:zimage-base-aio-test@2637423", "name": "Z-Image Base AIO (FP8)", "creator": "SeeSeeLP", "price": "~$0.003/张", "base": "zit"},
    "zimage-alibaba": {"id": "runware:z-image@turbo", "name": "Alibaba Z-Image-Turbo", "price": "$0.0006/张", "base": "zit"},
    "zimage-moody":   {"id": "persona:620406@2745677", "name": "Moody Pro Mix (Z-Image)", "creator": "catlover1937", "price": "$0.0013/张", "base": "zit"},
    "zimage-stable-yogi": {"id": "liangwc:zimage-turbo-stable-yogi@3096324", "name": "Zimage Turbo by Stable Yogi (2603 Fp8)", "creator": "Stable_Yogi", "price": "~$0.0013/张", "base": "zit"},
    "zimage-ultimate-nsfw": {"id": "liangwc:zimage-ultimate-nsfw@2827368", "name": "Z Image Ultimate NSFW Unlock Turbo v2.0", "creator": "LocalMinimum", "price": "~$0.0013/张", "base": "zit"},
    "zimage-turbo-anime": {"id": "liangwc:zimage-turbo-anime@2741210", "name": "Z-Image-Turbo Anime V2 Fp8", "creator": "rimamashiro42928", "price": "~$0.0013/张", "base": "zit"},
    "zimage-visionary-nsfw": {"id": "liangwc:zit-visionary-nsfw@2565655", "name": "Z-ImageTurbo VISIONARY NSFW (ZIT-fp8)", "creator": "VisionaryAI_Studio", "price": "~$0.0013/张", "base": "zit"},
    "zimage-tinzit-anime": {"id": "liangwc:tinzit-anime-fp8@3044495", "name": "TinZIT-ANIME-FP8 4steps 完全二次元", "creator": "tin18688783", "price": "~$0.0013/张", "base": "zit"},
    "zimage-lau-anime": {"id": "liangwc:zanimimage-turbo-lau@2540933", "name": "z_animimage_turbo_by_Lau (semi-real bf16)", "creator": "LauShine", "price": "~$0.0013/张", "base": "zit"},
    "zimage-komposto-ani": {"id": "liangwc:komposto-zit-ani@2485111", "name": "Komposto ZIT_ANI (fp8)", "creator": "Komposto", "price": "~$0.0013/张", "base": "zit"},
    "zimage-pornmaster-v35": {"id": "liangwc:zimage-pornmaster-v35-bf16@2903129", "name": "PornMaster 色情大师 Z-Image (Turbo V3.5 BF16)", "creator": "iamddtla", "price": "~$0.0013/张", "base": "zit"},
    # SD 1.5 Checkpoints
    "dreamshaper-15":    {"id": "civitai:4384@128713", "name": "DreamShaper 1.5", "creator": "Lykon", "price": "~$0.003/张", "base": "sd15"},
    "majicmix-real-15":  {"id": "civitai:43331@94640", "name": "majicMIX realistic 麦橘写实", "creator": "Merjic", "price": "~$0.003/张", "base": "sd15"},
    "realcartoon3d-15":  {"id": "civitai:94809@1409849", "name": "RealCartoon3D", "creator": "7whitefire7", "price": "~$0.003/张", "base": "sd15"},
    "aniverse-15":       {"id": "civitai:107842@614262", "name": "AniVerse", "creator": "Samael1976", "price": "~$0.003/张", "base": "sd15"},
    "chikmix-15":        {"id": "civitai:9871@59409", "name": "ChikMix", "creator": "xxxholic", "price": "~$0.003/张", "base": "sd15"},
    "realcartoon-real-15": {"id": "civitai:97744@671503", "name": "RealCartoon-Realistic", "creator": "7whitefire7", "price": "~$0.003/张", "base": "sd15"},
    "perfect-world-15":  {"id": "civitai:8281@179446", "name": "Perfect World 完美世界", "creator": "Bloodsuga", "price": "~$0.003/张", "base": "sd15"},
    "majicmix-lux-15":   {"id": "civitai:56967@286238", "name": "majicMIX lux 麦橘辉耀", "creator": "Merjic", "price": "~$0.003/张", "base": "sd15"},
    "dark-sushi-25d-15": {"id": "civitai:48671@141866", "name": "Dark Sushi 2.5D 大颗寿司2.5D", "creator": "Aitasai", "price": "~$0.003/张", "base": "sd15"},
    "guofeng-wuxia-15":  {"id": "civitai:95643@219960", "name": "国风武侠 Chosen Chinese", "creator": "chosen", "price": "~$0.003/张", "base": "sd15"},
    "tastyrice-cg-15":   {"id": "civitai:207481@348685", "name": "TastyRice-CG国风MIX", "creator": "Tasty_Rice", "price": "~$0.003/张", "base": "sd15"},
    "onlyrealistic-15":  {"id": "civitai:112756@139087", "name": "OnlyRealistic 《唯》超高清真人写实", "creator": "Tian__", "price": "~$0.003/张", "base": "sd15"},
    "chilloutmix-15":    {"id": "civitai:6424@11745", "name": "ChilloutMix", "price": "~$0.003/张", "base": "sd15"},
    "chosen-mix-15":     {"id": "civitai:17148@125302", "name": "chosen-mix", "creator": "chosen", "price": "~$0.003/张", "base": "sd15"},
    "abyss-orange-mix-15": {"id": "civitai:4449@5036", "name": "AbyssOrangeMix2 NSFW", "creator": "Havoc", "price": "~$0.003/张", "base": "sd15"},
    "aom3-15":            {"id": "civitai:9942@17233", "name": "AbyssOrangeMix3 AOM3", "creator": "liudinglin", "price": "~$0.003/张", "base": "sd15"},
    "wanxiang-anything-15": {"id": "civitai:9409@90854", "name": "万象熔炉 Anything XL", "creator": "Yuno779", "price": "~$0.003/张", "base": "sd15"},
    "lazymix-15":         {"id": "civitai:10961@300972", "name": "LazyMix+ Real Amateur Nudes", "creator": "kaylazy", "price": "~$0.003/张", "base": "sd15"},
    "aom2-hardcore-15":   {"id": "civitai:4451@5038", "name": "AbyssOrangeMix2 Hardcore", "creator": "Havoc", "price": "~$0.003/张", "base": "sd15"},
    "dark-sushi-mix-15":  {"id": "civitai:24779@93208", "name": "Dark Sushi Mix 大颗寿司", "creator": "Aitasai", "price": "~$0.003/张", "base": "sd15"},
    "realisian-15":       {"id": "civitai:47130@325142", "name": "Realisian", "creator": "Cisney_Gassai", "price": "~$0.003/张", "base": "sd15"},
    "anyhentai-15":       {"id": "civitai:5706@41233", "name": "AnyHentai", "creator": "asdpro123", "price": "~$0.003/张", "base": "sd15"},
    "majicmix-sombre-15": {"id": "civitai:62778@75209", "name": "majicMIX sombre 麦橘唯美", "creator": "Merjic", "price": "~$0.003/张", "base": "sd15"},
    "realcartoon-anime-15": {"id": "civitai:96629@359428", "name": "RealCartoon-Anime", "creator": "7whitefire7", "price": "~$0.003/张", "base": "sd15"},
    "fantexi-15":         {"id": "civitai:18427@95199", "name": "Fantexi v0.9Beta", "creator": "zhazhahui345", "price": "~$0.003/张", "base": "sd15"},
    "orangechillmix-15":  {"id": "civitai:9486@129974", "name": "OrangeChillMix", "creator": "Mikoeiaow", "price": "~$0.003/张", "base": "sd15"},
    "camelliamix-15":     {"id": "civitai:44219@161429", "name": "CamelliaMix 2.5D", "creator": "Mods13", "price": "~$0.003/张", "base": "sd15"},
    "astranime-15":       {"id": "civitai:248011@334482", "name": "AstrAnime", "creator": "Astraali", "price": "~$0.003/张", "base": "sd15"},
    "kawaii-anime-mix-15": {"id": "civitai:104100@837260", "name": "Kawaii Realistic Anime Mix", "creator": "szxex", "price": "~$0.003/张", "base": "sd15"},
    "kakarot-28d-15":     {"id": "civitai:182723@458684", "name": "Kakarot 2.8D", "creator": "vay_kakarot", "price": "~$0.003/张", "base": "sd15"},
    "majicmix-reverie-15": {"id": "civitai:65055@69687", "name": "majicMIX reverie 麦橘梦幻", "creator": "Merjic", "price": "~$0.003/张", "base": "sd15"},
    "majicmix-horror-15": {"id": "civitai:49216@53806", "name": "majicMIX horror 麦橘恐怖", "creator": "Merjic", "price": "~$0.003/张", "base": "sd15"},
    "wai-realmix-pony":   {"id": "civitai:393905@868204", "name": "WAI-REALMIX (Pony)", "creator": "WAI0731", "price": "~$0.003/张", "base": "pony"},
    "wai-ani-hentai-pony": {"id": "civitai:553648@952743", "name": "WAI-ANI-HENTAI-PONYXL", "creator": "WAI0731", "price": "~$0.003/张", "base": "pony"},
    "realcartoon-pony":   {"id": "civitai:618329@1367762", "name": "RealCartoon-Pony", "creator": "7whitefire7", "price": "~$0.003/张", "base": "pony"},
    "wai-ani-pony":       {"id": "civitai:404154@1767402", "name": "WAI-ANI-PONYXL", "creator": "WAI0731", "price": "~$0.003/张", "base": "pony"},
    "nova-anime-pony":    {"id": "civitai:376130@994669", "name": "Nova Anime XL", "creator": "Crody", "price": "~$0.003/张", "base": "pony"},
    "nova-reality-pony":  {"id": "civitai:453428@1028683", "name": "Nova Reality XL", "creator": "Crody", "price": "~$0.003/张", "base": "pony"},
    "atomix-anime-pony":  {"id": "civitai:340158@608850", "name": "Atomix Pony Anime XL", "creator": "AlexLai", "price": "~$0.003/张", "base": "pony"},
    "redcraft-pony":      {"id": "civitai:958009@1484125", "name": "RedCraft 红潮2", "creator": "AiMetatron", "price": "~$0.003/张", "base": "pony"},
    "the-deep-dark-pony": {"id": "civitai:221751@634653", "name": "The Deep Dark", "creator": "Dark_infinity", "price": "~$0.003/张", "base": "pony"},
    "honey-mix-pony":     {"id": "civitai:644900@721415", "name": "Honey Mix High Contrast Anime", "creator": "holostrawberry", "price": "~$0.003/张", "base": "pony"},
    "nova-asian-pony":    {"id": "civitai:641919@1076213", "name": "Nova Asian XL", "creator": "Crody", "price": "~$0.003/张", "base": "pony"},
    "powerpuffmix-pony":  {"id": "civitai:805817@1162963", "name": "PowerPuffMix", "creator": "GZees", "price": "~$0.003/张", "base": "pony"},
    "wai-semireal-pony":  {"id": "civitai:617553@816062", "name": "WAI-SemiReal", "creator": "WAI0731", "price": "~$0.003/张", "base": "pony"},
    "wai-c-pony":         {"id": "civitai:440170@788376", "name": "WAI-C", "creator": "WAI0731", "price": "~$0.003/张", "base": "pony"},
    "atomix-3d-pony":     {"id": "civitai:469465@522337", "name": "Atomix Pony 3D XL", "creator": "AlexLai", "price": "~$0.003/张", "base": "pony"},
    "miaomiao-3d-pony":   {"id": "civitai:431957@728705", "name": "MiaoMiao 3D Harem", "creator": "MIAOKA", "price": "~$0.003/张", "base": "pony"},
    "powerpuffanimix-pony": {"id": "civitai:869046@972602", "name": "PowerPuffAnimix", "creator": "GZees", "price": "~$0.003/张", "base": "pony"},
    "wai-mature-pony":      {"id": "civitai:875816@980452", "name": "WAI-Mature (Pony)", "creator": "WAI0731", "price": "~$0.003/张", "base": "pony"},
    # Illustrious / NoobAI checkpoints (Runware AIR IDs)
    "wai-illustrious":     {"id": "aiki:827184@2883731", "name": "WAI-Illustrious-SDXL", "creator": "WAI0731", "price": "~$0.003/张", "base": "illustrious"},
    "aoi-164":             {"id": "choosenmodelanime:4438@7355", "name": "Aoi 164 Character", "creator": "Numeratic", "price": "~$0.003/张", "base": "illustrious"},
    "cat-citron-anime":    {"id": "choosenmodelanime:131986@1945419", "name": "CAT Citron Anime Treasure", "creator": "CitronLegacy", "price": "~$0.003/张", "base": "illustrious"},
    "nova-anime-xl-noob":  {"id": "civitai:376130@1474209", "name": "Nova Anime XL (NoobAI)", "creator": "Crody", "price": "~$0.003/张", "base": "illustrious"},
    "nova-reality-ill":    {"id": "civitai:453428@1478543", "name": "Nova Reality XL (Illustrious)", "creator": "Crody", "price": "~$0.003/张", "base": "illustrious"},
    "miaomiao-harem-ill":  {"id": "civitai:934764@1357881", "name": "MiaoMiao Harem (Illustrious)", "creator": "MIAOKA", "price": "~$0.003/张", "base": "illustrious"},
    "animij-ill":          {"id": "aiki:1353314@2827109", "name": "Animij (Illustrious)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "illustrious-xl-2":    {"id": "imagerouter:1369089@1546777", "name": "Illustrious XL 2.0", "creator": "ONOMAAI", "price": "~$0.003/张", "base": "illustrious"},
    "ilustmix-ill":        {"id": "civitai:1110783@1456068", "name": "iLustMix (Illustrious)", "creator": "GZees", "price": "~$0.003/张", "base": "illustrious"},
    "pornmaster-ill":      {"id": "civitai:1045588@1412925", "name": "PornMaster-Pro Illustrious", "creator": "iamddtla", "price": "~$0.003/张", "base": "illustrious"},
    "pornmaster-anime-ill": {"id": "civitai:1033851@1463869", "name": "PornMaster-Anime NoobXL-V4 (Illustrious)", "creator": "iamddtla", "price": "~$0.003/张", "base": "illustrious"},
    "matureritual-ill":    {"id": "liangwc:matureritual@2730987", "name": "MatureRitual 熟メス儀式 v204 (Illustrious)", "creator": "EKLL", "price": "~$0.003/张", "base": "illustrious"},
    "burgundy-semireal-ill": {"id": "liangwc:burgundy-silk-semireal@3053870", "name": "Burgundy Silk | Asian Semi-Realism 2A (Illustrious)", "creator": "PrincessCozi", "price": "~$0.003/张", "base": "illustrious"},
    "burgundy-bimbos-ill":   {"id": "liangwc:burgundy-silk-bimbos@3161087", "name": "Burgundy Silk | Asian Bimbos 2B (Illustrious)", "creator": "PrincessCozi", "price": "~$0.003/张", "base": "illustrious"},
    "burgundy-dolls-ill":    {"id": "liangwc:burgundy-silk-dolls@3139629", "name": "Burgundy Silk | Asian Dolls 2B (Illustrious)", "creator": "PrincessCozi", "price": "~$0.003/张", "base": "illustrious"},
    "burgundy-milfs-ill":    {"id": "liangwc:burgundy-silk-milfs@3073407", "name": "Burgundy Silk | Asian MILFs 2A (Illustrious)", "creator": "PrincessCozi", "price": "~$0.003/张", "base": "illustrious"},
    "miaomiao-mature-ill": {"id": "liangwc:miaomiao-mature@2854190", "name": "MiaoMiao Mature Edition (Illustrious)", "creator": "MIAOKA", "price": "~$0.003/张", "base": "illustrious"},
    "kawaij-ill":          {"id": "civitai:1257951@1434449", "name": "Kawaij (Illustrious)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "nova-orange-ill":     {"id": "civitai:967405@1428332", "name": "Nova Orange XL (Illustrious)", "creator": "Crody", "price": "~$0.003/张", "base": "illustrious"},
    "nova-flat-ill":       {"id": "civitai:1240874@1398523", "name": "Nova Flat XL (Illustrious)", "creator": "Crody", "price": "~$0.003/张", "base": "illustrious"},
    "semilust-ill":        {"id": "civitai:1160480@1449034", "name": "semILust (Illustrious)", "creator": "reijlita", "price": "~$0.003/张", "base": "illustrious"},
    "persona-zit":         {"id": "persona:242173@2788849", "name": "Dark Beast 黑兽3.0 (ZIT)", "creator": "AiMetatron", "price": "~$0.003/张", "base": "zit"},
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


# hiresFix 架构白名单（2026-09-11 平台实测，错误码 unsupportedArchitectureHiresFix）。
# 平台支持：SD 1.5 / SDXL 1.0 / SDXL LCM / SDXL Distilled / SDXL Turbo / Pony /
#           SDXL Lightning / SDXL Hyper / SD 1.5 Hyper / NoobAI
# 不支持：FLUX 全系、Z-Image Turbo。
# 我们把这批 checkpoint 统一注册为 sdxl 架构，所以 Illustrious/Pony/SDXL/SD1.5 都能用。
# 不在白名单时**静默跳过**（不抛错、不中断 batch）——前端已按底模灰掉控件，这里只是兜底保险。
HIRES_FIX_BASES = {"illustrious", "pony", "sdxl", "sd15", "noobai"}


def generate(prompt: str, *, model_key: str = "flux-dev",
             negative_prompt: str = "", image_path: str = None,
             strength: float = 0.8, lora_id: str = None,
             lora_scale: float = 0.8, seed: int = None,
             aspect: str = "9:16", cfg_scale: float = None,
             steps: int = 35, sampler: str = None,
             embedding_id: str = None,
             width: int = None, height: int = None,
             hires_fix: bool = False) -> Path:
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

    # 高清修复（hiresFix）——纯开关，无子参数。平台按架构白名单限制，不支持的静默跳过。
    # ⚠️ 副作用：它改变整张图（同 seed 也是另一张），不是"同一张图加细节"；
    #    输出尺寸不变；成本约 +$0.0007，耗时 +5~40s 不等。
    effective_hires = bool(hires_fix) and model_info.get("base") in HIRES_FIX_BASES
    if effective_hires:
        task["advancedFeatures"] = {"hiresFix": True}
        print("✨ High res fix: ON")
    elif hires_fix:
        print(f"⏭️  High res fix skipped（{model_info.get('base')} 架构不支持）")

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

    # Embeddings (textual inversion) — supports single or comma-separated AIR list.
    # 用法：embedding 的 trigger word 要写进 prompt 才生效（同 LoRA 机制）。
    if embedding_id:
        eids = [x.strip() for x in embedding_id.split(",") if x.strip()]
        task["embeddings"] = [{"model": eid} for eid in eids]
        for eid in eids:
            print(f"🧩 Embedding: {eid}")

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
                     prompt=prompt, model=model_info["name"], model_key=model_key,
                     seed=used_seed, lora_id=lora_id,
                     steps=steps, negative_prompt=negative_prompt,
                     cfg_scale=task.get("CFGScale"), sampler=task.get("scheduler"),
                     embedding_id=embedding_id,
                     hires_fix=effective_hires)
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
                     prompt=prompt, model=info["name"], model_key=model_key,
                     seed=used_seed, lora_id=None,
                     steps=task.get("steps") or info["steps"] or 35,
                     negative_prompt=task.get("negativePrompt", ""),
                     cfg_scale=task.get("CFGScale"))
    return out, used_seed

