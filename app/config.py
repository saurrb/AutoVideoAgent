from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    ffmpeg_exe: Path
    lines_file: Path
    music_file: Path
    font_file: Path
    output_dir: Path
    db_file: Path
    meta_config_file: Path
    post_to_facebook: bool
    logo_file: Path | None


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_settings() -> Settings:
    load_env_file(Path(".env"))
    return Settings(
        ffmpeg_exe=Path(os.environ["FFMPEG_EXE"]),
        lines_file=Path(os.environ["LINES_FILE"]),
        music_file=Path(os.environ["MUSIC_FILE"]),
        font_file=Path(os.environ.get("FONT_FILE", r"C:\Windows\Fonts\arial.ttf")),
        output_dir=Path(os.environ["OUTPUT_DIR"]),
        db_file=Path(os.environ["DB_FILE"]),
        meta_config_file=Path(os.environ["META_CONFIG_FILE"]),
        post_to_facebook=os.environ.get("POST_TO_FACEBOOK", "false").lower() == "true",
        logo_file=Path(os.environ["LOGO_FILE"]) if os.environ.get("LOGO_FILE") else None,
    )
