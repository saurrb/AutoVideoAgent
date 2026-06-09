from __future__ import annotations

import os
import subprocess
from pathlib import Path


GROK_CREDIT_SIGNALS = (
    "run out of credits",
    "need a grok subscription",
    "spending-limit",
    "personal-team-blocked",
    "403 forbidden",
)

GROK_LIMIT_SIGNALS = (
    "rate limit",
    "rate-limit",
    "exceeded",
    "too many requests",
    "quota",
    "limit reached",
    "try again later",
)


def candidate_grok_paths() -> list[Path]:
    candidates = [
        Path.home() / ".grok" / "bin" / "grok.exe",
        Path("/mnt/c/Users/Saurabh/.grok/bin/grok.exe"),
        Path(r"C:\Users\Saurabh\.grok\bin\grok.exe"),
    ]
    if os.name != "nt":
        home = _default_windows_home()
        if home:
            candidates.insert(0, home / ".grok" / "bin" / "grok.exe")
    return candidates


def _default_windows_home() -> Path | None:
    for candidate in (Path("/mnt/c/Users/Saurabh"), Path("/mnt/c/Users")):
        if candidate.exists():
            return candidate / "Saurabh" if candidate.name == "Users" else candidate
    return None


def resolve_grok_exe() -> Path:
    checked: list[str] = []
    for candidate in candidate_grok_paths():
        checked.append(str(candidate))
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Grok CLI not found. Checked: " + ", ".join(checked))


def is_grok_credit_error(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(signal in lowered for signal in GROK_CREDIT_SIGNALS)


def is_grok_limit_error(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(signal in lowered for signal in GROK_LIMIT_SIGNALS)


def run_grok_text(prompt: str, *, grok_exe: Path | None = None, cwd: Path | None = None) -> str:
    exe = grok_exe or resolve_grok_exe()
    proc = subprocess.run(
        [str(exe), "-p", prompt],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    combined = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    if is_grok_credit_error(combined):
        raise RuntimeError(
            "GROK_CREDITS_EXHAUSTED: Grok returned 403 spending/subscription limit. "
            "Add credits or renew SuperGrok, then rerun the missed slots."
        )
    if is_grok_limit_error(combined):
        raise RuntimeError("GROK_LIMIT_REACHED: Grok rate/quota limit detected. Failing without fallback.")
    if proc.returncode != 0:
        raise RuntimeError(f"Grok text generation failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return proc.stdout or ""
