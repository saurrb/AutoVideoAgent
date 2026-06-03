import argparse
import random
from pathlib import Path

from openpyxl import Workbook


CATEGORIES = [
    "Girl Fact",
    "Guy Fact",
    "Love Fact",
    "Attraction Fact",
    "Dating Fact",
    "Chemistry Fact",
]

HOOK_STARTERS = [
    "If a woman",
    "If a girl",
    "If a guy",
    "Most women",
    "Most men",
    "When attraction",
    "When a woman",
    "When a man",
    "Love gets deeper when",
    "Chemistry gets stronger when",
]

HOOK_MIDDLES = [
    "holds eye contact with a slow smile",
    "leans in and lowers her voice around you",
    "texts you late night just to talk",
    "keeps playful tension without overexplaining",
    "touches your arm and lingers a second longer",
    "asks deeper questions and listens closely",
    "feels safe enough to be soft and open",
    "tests your confidence with teasing energy",
    "matches your rhythm and mirrors your body language",
    "stays present instead of chasing attention",
    "smiles after silence instead of filling every gap",
    "lets anticipation build before physical intimacy",
    "prefers slow foreplay over rushed pressure",
    "craves emotional chemistry before physical heat",
    "chooses steady masculine energy over mixed signals",
]

REVEALS = [
    "she feels trust and desire at the same time.",
    "that is usually a strong sign of real attraction.",
    "your presence feels safe, sensual, and magnetic to her.",
    "she is opening emotionally, not just being social.",
    "that tension often turns into deep romantic chemistry.",
    "she values calm confidence over needy attention.",
    "this is where long-term desire usually begins.",
    "emotional intimacy is becoming physical attraction.",
    "it signals genuine interest, not casual validation.",
    "this is why grounded masculinity outperforms pressure.",
    "she is inviting connection, not playing random games.",
    "that is the spark between affection and temptation.",
    "she feels desired without feeling forced.",
    "this is the zone where passion grows naturally.",
    "she is responding to energy, not just words.",
]


def cap_words(text: str, max_words: int = 16) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(".,") + "."


def highlight_count(text: str) -> int:
    wc = len(text.split())
    if wc >= 13:
        return 4
    if wc >= 10:
        return 3
    return 2


def make_line() -> tuple[str, str]:
    category = random.choice(CATEGORIES)
    hook = f"{random.choice(HOOK_STARTERS)} {random.choice(HOOK_MIDDLES)}"
    reveal = random.choice(REVEALS)
    return category, cap_words(hook), cap_words(reveal)


def to_hook_answer(hook: str, answer: str) -> str:
    hook = hook.rstrip(".!?")
    answer = answer.rstrip(".!?")
    return f"{hook}||{answer}."


def generate_xlsx(out_path: Path, total_rows: int, seed: int) -> None:
    random.seed(seed)
    wb = Workbook()
    ws = wb.active
    ws.title = "content_pool"
    ws.append(
        [
            "id",
            "heading_line1",
            "heading_line2",
            "point_text",
            "highlight_first_words",
            "cta",
            "used",
        ]
    )

    cta = ""
    row_id = 1
    while row_id <= total_rows:
        category, hook, answer = make_line()
        point = to_hook_answer(hook, answer)
        ws.append(
            [
                row_id,
                "DAILY DESIRE FACTS",
                category,
                point,
                highlight_count(hook),
                cta,
                0,
            ]
        )
        row_id += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default="pages/page2_daily_desire_facts/content/reel_content_bank.xlsx",
        help="Output workbook path.",
    )
    ap.add_argument("--rows", type=int, default=1000, help="Number of content rows.")
    ap.add_argument("--seed", type=int, default=90209438344, help="Random seed.")
    args = ap.parse_args()

    out_path = Path(args.out)
    generate_xlsx(out_path, args.rows, args.seed)
    print(out_path)
    print(f"rows={args.rows}")


if __name__ == "__main__":
    main()

