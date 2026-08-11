"""Minimal Gemini API client for image generation / editing (the 'teacher'
model that prototypes the pixel-art style and later produces training pairs).

Costs (2026-08, no free tier on image models): gemini-3-pro-image ~USD 0.134
per 1-2K image. Usage is logged to the shared budget DB under 'gemini_image'
(cap set high; the constraint is the user's AI Studio Pro trial, not our cap).
"""

from __future__ import annotations

import base64
import json
import os
import urllib.request
from pathlib import Path

from .apibudget import ApiBudget
from .config import REPO_ROOT

BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3-pro-image"


def gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.strip().startswith("GEMINI_API_KEY="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("GEMINI_API_KEY not set (env var or .env file)")


def generate_image(
    prompt: str,
    input_images: list[Path] | None = None,
    model: str = DEFAULT_MODEL,
    budget: ApiBudget | None = None,
) -> tuple[bytes | None, str]:
    """One generation call. Returns (image bytes or None, text response)."""
    budget = budget or ApiBudget()
    budget.spend(1, api="gemini_image")

    parts: list[dict] = []
    for p in input_images or []:
        parts.append({
            "inline_data": {
                "mime_type": "image/png",
                "data": base64.b64encode(p.read_bytes()).decode(),
            }
        })
    parts.append({"text": prompt})

    body = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }).encode()

    req = urllib.request.Request(
        f"{BASE}/models/{model}:generateContent?key={gemini_key()}",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        out = json.loads(resp.read())

    image_bytes: bytes | None = None
    text = ""
    for part in out["candidates"][0]["content"]["parts"]:
        if "inlineData" in part:
            image_bytes = base64.b64decode(part["inlineData"]["data"])
        elif "text" in part:
            text += part["text"]
    return image_bytes, text
