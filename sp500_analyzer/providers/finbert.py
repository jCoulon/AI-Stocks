"""Scores de ton FinBERT des titres de news, précalculés et mis en cache.

FinBERT (ProsusAI/finbert, open source) est un modèle BERT entraîné sur des textes financiers :
il classe un titre en positif / négatif / neutre. Le score retenu est P(positif) − P(négatif),
entre −1 et 1, comme le lexique qu'il remplace. Le modèle (PyTorch) ne tourne que dans le
workflow GitHub ; l'outil lit seulement le cache <dossier>/news/finbert.csv.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Callable

from .realnews import read_news_rows, title_key

CACHE = Path("news") / "finbert.csv"
MODEL = "ProsusAI/finbert"
_NOT_NEWS = {"couverture.csv", "finbert.csv"}

#: classify(titres) -> [{"positive": p, "negative": p, "neutral": p}, ...]
Classifier = Callable[[list[str]], list[dict[str, float]]]


def news_files(root: Path) -> list[Path]:
    folder = root / "news"
    files = [p for p in folder.glob("*.csv") if p.name not in _NOT_NEWS]
    for sub in ("google", "rss"):
        files += [p for p in (folder / sub).glob("*.csv") if p.name not in _NOT_NEWS]
    return sorted(files)


def social_texts(root: Path) -> list[str]:
    """Textes des messages sociaux sans étiquette d'auteur (Reddit, StockTwits non étiquetés),
    à noter par FinBERT."""
    out = []
    for path in sorted((root / "social").glob("*/*.csv")):
        with open(path, newline="", encoding="utf-8") as f:
            out += [r["Text"] for r in csv.DictReader(f) if r.get("Text") and not r.get("Sentiment")]
    return out


def load_scores(root: Path) -> dict[str, float]:
    path = root / CACHE
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["Key"]: float(r["Score"]) for r in csv.DictReader(f)}


def score_titles(root: Path, classify: Classifier, batch: int = 64, log=print) -> int:
    """Calcule le score des titres pas encore en cache ; renvoie le nombre de nouveaux scores."""
    path = root / CACHE
    rows: dict[str, list] = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            rows = {r["Key"]: [r["Positive"], r["Negative"], r["Neutral"], r["Score"], r["Title"]]
                    for r in csv.DictReader(f)}
    todo: dict[str, str] = {}
    texts = [row[3] for file in news_files(root) for row in read_news_rows(file)]
    texts += social_texts(root)
    for text in texts:
        key = title_key(text)
        if key and key not in rows:
            todo.setdefault(key, text)
    items = list(todo.items())
    log(f"  FinBERT : {len(items)} nouveau(x) titre(s) à analyser ({len(rows)} déjà en cache)")
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        for (key, title), probs in zip(chunk, classify([t for _, t in chunk])):
            pos, neg, neu = (float(probs.get(k, 0.0)) for k in ("positive", "negative", "neutral"))
            rows[key] = [f"{pos:.4f}", f"{neg:.4f}", f"{neu:.4f}", f"{pos - neg:.4f}", title]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Key", "Positive", "Negative", "Neutral", "Score", "Title"])
        for key in sorted(rows):
            w.writerow([key, *rows[key]])
    return len(items)
