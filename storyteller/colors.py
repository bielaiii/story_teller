from __future__ import annotations

import hashlib


CONTENT_COLOR_PALETTE = (
    "#4f6fae", "#8c5fa8", "#b45f75", "#b06f42",
    "#5d8f7b", "#4f8796", "#786a9e", "#9a6b55",
    "#6d7f9c", "#9a5f83", "#567a63", "#8d7052",
)


def content_color(seed: object) -> str:
    """Choose a stable color from the shared visual palette."""
    digest = hashlib.sha1(str(seed).encode("utf-8")).digest()
    return CONTENT_COLOR_PALETTE[int.from_bytes(digest[:2], "big") % len(CONTENT_COLOR_PALETTE)]
