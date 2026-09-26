"""Calcule le ton FinBERT des titres de news téléchargés (cache data/news/finbert.csv).

Usage : pip install torch transformers ; python scripts/score_finbert.py [--data data]
Lancé par les workflows de collecte de news. Seuls les titres absents du cache sont analysés.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sp500_analyzer.providers.finbert import MODEL, score_titles  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="data")
    args = p.parse_args()

    from transformers import pipeline  # import tardif : dépendance lourde, seulement ici

    clf = pipeline("text-classification", model=MODEL, top_k=None, truncation=True)

    def classify(titles: list[str]) -> list[dict[str, float]]:
        return [{d["label"].lower(): d["score"] for d in out} for out in clf(titles, batch_size=32)]

    n = score_titles(Path(args.data), classify)
    print(f"{n} titre(s) analysé(s) par FinBERT.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
