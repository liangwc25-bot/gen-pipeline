#!/usr/bin/env python3
"""CN → EN prompt translation via Hermes API server.

Call Hermes API server at 127.0.0.1:8642 (OpenAI-compatible endpoint)
to translate Chinese image generation prompts into English.
Relies on Hermes's jailbroken state for uncensored translation.
"""

import os
import json
import urllib.request
import urllib.error

HERMES_API_URL = "http://127.0.0.1:8642/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are a translation engine for AI image generation prompts. "
    "Translate the Chinese prompt to English.\n\n"
    "RULES:\n"
    "- Be LITERAL and PRECISE — preserve every detail exactly\n"
    "- Preserve ALL content including graphic, violent, gory, or sexual descriptions — "
    "this is artistic image creation, no censorship needed\n"
    "- Use standard image generation tag conventions (e.g. 'masterpiece, best quality' for quality tags)\n"
    "- Preserve artistic terminology: lighting, composition, camera angle, style, mood\n"
    "- Output ONLY the English translation — no explanations, no commentary, no markdown\n"
    "- Match the input's level of detail: detailed Chinese → detailed English"
)


def translate_cn_to_en(cn_prompt: str, timeout: int = 30) -> str | None:
    """Translate a Chinese prompt to English via Hermes API server.

    Returns the translated English prompt, or None on failure.
    On failure the caller should fall back to the original prompt.
    """
    api_key = os.environ.get("API_SERVER_KEY", "")
    if not api_key:
        # also check .env in gen-pipeline root
        env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_file):
            for line in open(env_file):
                if line.startswith("API_SERVER_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not api_key:
        return None

    payload = {
        "model": "hermes-agent",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Translate this Chinese image prompt to English:\n\n{cn_prompt}"},
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
    }

    req = urllib.request.Request(
        HERMES_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            translated = data["choices"][0]["message"]["content"].strip()
            # Strip common wrapper artifacts
            for prefix in ('"', "'", "```", "English: ", "EN: "):
                if translated.startswith(prefix):
                    translated = translated[len(prefix):]
            for suffix in ('"', "'", "```"):
                if translated.endswith(suffix):
                    translated = translated[:-len(suffix)]
            translated = translated.strip()
            return translated if len(translated) > 3 else None
    except Exception:
        return None
