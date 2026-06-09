from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class PageConfig:
    page_key: str
    profile: dict[str, Any]


PAGE_CONFIG_ALIASES = {
    "female_psychology": "page1_female_psychology",
    "daily_desire_facts": "page2_daily_desire_facts",
    "dragon_cinema": "page3_dragon_cinema",
}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be an object: {path}")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def _validate_config(page_key: str, cfg: dict[str, Any]) -> None:
    required_top = ["video", "assets", "content", "render", "style"]
    for k in required_top:
        if k not in cfg or not isinstance(cfg[k], dict):
            raise ValueError(f"[{page_key}] Missing required config object: {k}")
    if "resolution" not in cfg["video"] or "fps" not in cfg["video"]:
        raise ValueError(f"[{page_key}] video.resolution and video.fps are required")
    if "logo_path" not in cfg["assets"]:
        raise ValueError(f"[{page_key}] assets.logo_path is required")
    if "xlsx_path" not in cfg["content"] or "sheet_name" not in cfg["content"]:
        raise ValueError(f"[{page_key}] content.xlsx_path and content.sheet_name are required")
    if "background_image_dir" not in cfg["render"] and "background_video" not in cfg["render"]:
        raise ValueError(f"[{page_key}] render.background_image_dir or render.background_video is required")


def load_page_config(project_root: Path, page_key: str) -> PageConfig:
    global_path = project_root / "configs" / "global.yaml"
    config_key = PAGE_CONFIG_ALIASES.get(page_key, page_key)
    page_path = project_root / "configs" / "pages" / f"{config_key}.yaml"
    legacy_page_path = project_root / "configs" / "pages" / f"{page_key}.yaml"
    if not page_path.exists() and legacy_page_path.exists():
        page_path = legacy_page_path
    global_cfg = _read_yaml(global_path) if global_path.exists() else {}
    page_cfg = _read_yaml(page_path)
    preset_name = page_cfg.get("style_preset", global_cfg.get("style_preset", "default_style"))
    preset_path = project_root / "configs" / "presets" / f"{preset_name}.yaml"
    style_cfg = _read_yaml(preset_path)

    merged = _deep_merge(global_cfg, page_cfg)
    merged["style"] = _deep_merge(style_cfg.get("style", {}), merged.get("style", {}))
    _validate_config(page_key, merged)
    return PageConfig(page_key=page_key, profile=merged)


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
