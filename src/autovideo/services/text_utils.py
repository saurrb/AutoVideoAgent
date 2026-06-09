from __future__ import annotations

import json
import re
from typing import Any


MOJIBAKE_REPLACEMENTS: dict[str, str] = {
    "Ã¢â¬â": "-",
    "Ã¢â‚¬â€": "-",
    "Ã¢â¬â": "-",
    "Ã¢â‚¬â€œ": "-",
    "Ã¢â¬Ë": "'",
    "Ã¢â¬â¢": "'",
    "Ã¢â‚¬Ëœ": "'",
    "Ã¢â‚¬â„¢": "'",
    "Ã¢â¬Å": '"',
    "Ã¢â¬Â": '"',
    "Ã¢â‚¬Å“": '"',
    "Ã¢â‚¬Â": '"',
    "Ã¢â‚¬ ": '"',
    "Ã¢â‚¬ï¿½": '"',
    "Ã¢â¬Â¦": "...",
    "Ã¢â‚¬Â¦": "...",
    "\u00c3\u00a2\u00c2\u0080\u00c2\u0094": "-",
    "\u00c3\u00a2\u00c2\u0080\u00c2\u0093": "-",
    "\u00c3\u00a2\u00c2\u0080\u00c2\u0098": "'",
    "\u00c3\u00a2\u00c2\u0080\u00c2\u0099": "'",
    "\u00c3\u00a2\u00c2\u0080\u00c2\u009c": '"',
    "\u00c3\u00a2\u00c2\u0080\u00c2\u009d": '"',
    "\u00c3\u00a2\u00c2\u0080\u00c2\u00a6": "...",
    "â€”": "-",
    "â€“": "-",
    "â€™": "'",
    "â€˜": "'",
    "â€œ": '"',
    "â€": '"',
    "â€¦": "...",
    "\u2014": "-",
    "\u2013": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
}


def repair_mojibake(value: str) -> str:
    text = str(value or "")
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(bad, good)

    # Repair common UTF-8 text decoded as cp1252/latin1. Two passes handles
    # cases that were copied through more than one broken layer.
    for _ in range(2):
        if not any(marker in text for marker in ("Ã", "â€™", "â€œ", "â€", "ðŸ", "Å")):
            break
        try:
            repaired = text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
        except Exception:
            break
        if not repaired or repaired == text:
            break
        text = repaired

    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text


def normalize_text(value: str, *, collapse_spaces: bool = False) -> str:
    text = repair_mojibake(str(value or ""))
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = text.strip()
    if collapse_spaces:
        text = " ".join(text.split())
    return text


def normalize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: normalize_payload(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_payload(v) for v in value]
    if isinstance(value, str):
        return normalize_text(value)
    return value


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*", "", str(text or "").strip(), flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned).replace("```", "").strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for idx, char in enumerate(cleaned):
            if char != "{":
                continue
            try:
                payload, _end = decoder.raw_decode(cleaned[idx:])
                break
            except json.JSONDecodeError:
                continue
        else:
            match = re.search(r"\{.*\}", cleaned, flags=re.S)
            if not match:
                raise RuntimeError(f"No JSON object found in model output. Output:\n{cleaned[:2000]}")
            payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON payload must be an object, got: {type(payload).__name__}")
    return payload


def sanitize_text_list(values: Any, *, limit: int = 5, prefix_hash: bool = False) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        text = normalize_text(str(value or ""), collapse_spaces=True)
        if prefix_hash and text:
            text = text if text.startswith("#") else f"#{text.lstrip('#')}"
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result
