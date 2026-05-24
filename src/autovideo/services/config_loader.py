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


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be an object: {path}")
    return data


def load_page_config(project_root: Path, page_key: str) -> PageConfig:
    page_path = project_root / "configs" / "pages" / f"{page_key}.yaml"
    page_cfg = _read_yaml(page_path)
    preset_name = page_cfg.get("style_preset", "default_style")
    preset_path = project_root / "configs" / "presets" / f"{preset_name}.yaml"
    style_cfg = _read_yaml(preset_path)

    merged = dict(page_cfg)
    merged["style"] = style_cfg.get("style", {})
    return PageConfig(page_key=page_key, profile=merged)


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
