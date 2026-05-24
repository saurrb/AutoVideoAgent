import argparse
from pathlib import Path

from openpyxl import Workbook


def main(out_path: Path) -> None:
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

    heading1 = "FEMALE psychology"
    heading2 = "ATTRACTION TRIGGERS"
    cta = "Follow now or this page will disappear from your feed."
    points = [
        "Emotional safety increases desire faster than appearance alone in long term attraction.",
        "Consistency in tone and actions builds trust that makes connection feel magnetic.",
        "Feeling seen without pressure creates deeper bonding than constant persuasion.",
        "Respect during disagreement often strengthens attachment and romantic pull.",
        "Calm confidence lowers emotional resistance and invites openness naturally.",
        "Clear communication lowers anxiety and makes attraction feel emotionally safer.",
        "Patience during conflict often creates stronger attachment than winning arguments.",
        "When she feels respected, her trust increases and affection becomes more natural.",
        "Quiet confidence plus empathy is one of the strongest long term pull factors.",
        "Predictable behavior makes emotional connection feel secure and sustainable.",
        "Authentic listening creates attraction because it signals maturity and control.",
        "Boundaries with kindness increase respect without reducing emotional closeness.",
        "Stable masculine energy helps her nervous system relax into connection.",
        "Intentional affection creates trust that deepens both desire and bonding.",
        "She invests more when she feels valued beyond surface level attention.",
        "Warm leadership with patience reduces confusion and builds emotional gravity.",
        "Healthy mystery with consistency keeps interest high without triggering insecurity.",
        "Owning mistakes quickly increases trust and strengthens emotional intimacy.",
        "A calm response under pressure makes attraction feel safer and deeper.",
        "Emotional steadiness is often more attractive than dramatic intensity.",
    ]
    highlights = [3, 3, 4, 3, 3, 3, 3, 4, 3, 3, 3, 3, 3, 3, 4, 3, 4, 3, 4, 3]

    for idx, (point, hi) in enumerate(zip(points, highlights), start=1):
        ws.append([idx, heading1, heading2, point, hi, cta, 0])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    print(out_path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default="pages/female_psychology/content/reel_content_bank.xlsx",
        help="Path to output Excel workbook.",
    )
    args = ap.parse_args()
    main(Path(args.out))

