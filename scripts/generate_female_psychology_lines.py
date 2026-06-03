from __future__ import annotations

from pathlib import Path


STARTERS = [
    "A confident woman",
    "Emotional safety",
    "Healthy attraction",
    "Strong boundaries",
    "Self-respect",
    "Mutual effort",
    "Clear communication",
    "Secure attachment",
    "High standards",
    "Calm energy",
    "Inner confidence",
    "Self-awareness",
    "Consistent behavior",
    "Emotional maturity",
    "Authentic femininity",
    "Personal growth",
    "Trustworthy actions",
    "Healthy independence",
    "Balanced love",
    "Intentional dating",
]

SUBJECTS = [
    "in relationships",
    "during conflict",
    "while dating",
    "when setting boundaries",
    "in hard conversations",
    "when choosing a partner",
    "under pressure",
    "during uncertainty",
    "in long-term love",
    "when healing",
    "when rebuilding trust",
    "in emotional moments",
    "while protecting peace",
    "during mixed signals",
    "when observing behavior",
    "while choosing standards",
    "during life transitions",
    "when prioritizing herself",
    "while staying feminine",
    "when leading with clarity",
]

VERBS = [
    "chooses",
    "values",
    "protects",
    "builds",
    "maintains",
    "creates",
    "expects",
    "encourages",
    "demands",
    "demonstrates",
    "balances",
    "recognizes",
    "honors",
    "welcomes",
    "develops",
    "practices",
    "cultivates",
    "trusts",
    "filters",
    "focuses on",
    "prefers",
    "rewards",
    "avoids",
    "rejects",
    "embraces",
]

OBJECTS = [
    "consistency over intensity",
    "effort over empty words",
    "peace over chaos",
    "clarity over confusion",
    "respect over attention",
    "stability over games",
    "truth over performance",
    "standards over loneliness",
    "calm over drama",
    "alignment over chemistry alone",
    "actions over promises",
    "character over charm",
    "accountability over excuses",
    "presence over breadcrumbing",
    "patience over panic",
    "trust over control",
    "reciprocity over chasing",
    "growth over ego",
    "honesty over guessing",
    "boundaries over people-pleasing",
]

ENDINGS = [
    "because real love feels safe.",
    "because healthy love is steady.",
    "because clarity protects the heart.",
    "because peace is attractive.",
    "because trust is earned daily.",
    "because standards prevent regret.",
    "because respect sustains attraction.",
    "because security deepens intimacy.",
    "because her energy is valuable.",
    "because self-worth guides choices.",
]


def build_lines(max_lines: int = 10_000) -> list[str]:
    lines: list[str] = []
    for a in STARTERS:
        for b in SUBJECTS:
            for c in VERBS:
                for d in OBJECTS:
                    for e in ENDINGS:
                        line = f"{a} {b} {c} {d} {e}"
                        lines.append(line)
                        if len(lines) >= max_lines:
                            return lines
    return lines


def main() -> None:
    out_file = Path("pages/page1_female_psychology/content/lines.txt")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    lines = build_lines(10_000)
    out_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"WROTE_LINES={len(lines)}")
    print(f"LINES_FILE={out_file.resolve()}")


if __name__ == "__main__":
    main()


