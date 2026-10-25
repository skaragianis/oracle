"""Detects when an embedding library or model update changes vector output.

Documents ingested before such an update keep their old vectors, so search
silently degrades for them. This is the one test that loads the real model, so
it is deselected by default; run it with `make backend-embedding-check`.

If the change is intended, regenerate the golden and re-add existing documents
after merging:

    ORACLE_UPDATE_GOLDENS=1 make backend-embedding-check
"""

import json
import math
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from oracle.common.embeddings import (
    DEFAULT_MODEL_CACHE_DIR,
    EMBEDDING_MODEL_NAME,
    load_embedder,
)

pytestmark = pytest.mark.embedding_model

GOLDEN_PATH = (
    Path(__file__).parent / "fixtures" / "embeddings" / "bge-small-en-v1.5.golden.json"
)
UPDATE_GOLDENS_ENV = "ORACLE_UPDATE_GOLDENS"
MIN_COSINE_SIMILARITY = 0.9999
SIGNIFICANT_DIGITS = 7

TEXTS = [
    "The quick brown fox jumps over the lazy dog.",
    "Quarterly revenue grew 12% year over year, driven by subscription renewals.",
    "How do I reset my password?",
    "Der Hund läuft schnell durch den Wald.",
    "def add(a, b):\n    return a + b",
    # Chunk-sized (~800 o200k tokens), past the model's 512-token truncation
    " ".join(
        f"Section {n} of the maintenance manual covers inspection interval {n * 7}, "
        f"torque setting {n * 3 + 11} and the replacement of filter type {n % 5}."
        for n in range(1, 33)
    ),
]

REEMBED_ADVICE = (
    "Existing documents were embedded with the old output and will no longer "
    "match queries well: after merging, they must be re-added (re-ingested). "
    f"If this change is intended, regenerate the golden with {UPDATE_GOLDENS_ENV}=1 "
    "make backend-embedding-check and review the diff."
)


def _round(vector: Iterable[float]) -> list[float]:
    return [float(f"{value:.{SIGNIFICANT_DIGITS}g}") for value in vector]


def _snapshot() -> dict[str, Any]:
    embedder = load_embedder(DEFAULT_MODEL_CACHE_DIR)
    passages = [_round(v) for v in embedder.passage_embed(TEXTS)]
    queries = [_round(next(iter(embedder.query_embed(text)))) for text in TEXTS]
    return {
        "model": EMBEDDING_MODEL_NAME,
        "dimension": len(passages[0]),
        "texts": TEXTS,
        "passage": passages,
        "query": queries,
    }


def _dump(snapshot: dict[str, Any]) -> str:
    # One list item per line keeps the golden reviewable (384 floats per vector).
    fields = []
    for key, value in sorted(snapshot.items()):
        if isinstance(value, list):
            items = ",\n".join(
                f"    {json.dumps(item, ensure_ascii=False)}" for item in value
            )
            fields.append(f'  "{key}": [\n{items}\n  ]')
        else:
            fields.append(f'  "{key}": {json.dumps(value)}')
    return "{\n" + ",\n".join(fields) + "\n}\n"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def test_embeddings_match_golden() -> None:
    actual = _snapshot()

    if os.environ.get(UPDATE_GOLDENS_ENV) == "1":
        GOLDEN_PATH.write_text(_dump(actual), encoding="utf-8")

    if not GOLDEN_PATH.exists():
        pytest.fail(
            f"No golden at {GOLDEN_PATH.name}; create it with {UPDATE_GOLDENS_ENV}=1 "
            "and review the new file"
        )
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    assert golden["model"] == actual["model"], (
        f"Golden was made for {golden['model']} but the app uses {actual['model']}. "
        + REEMBED_ADVICE
    )
    assert golden["texts"] == TEXTS, (
        f"The fixed strings changed; regenerate the golden with {UPDATE_GOLDENS_ENV}=1 "
        "make backend-embedding-check and review the diff."
    )
    assert golden["dimension"] == actual["dimension"], (
        f"Embedding dimension changed from {golden['dimension']} to "
        f"{actual['dimension']}. " + REEMBED_ADVICE
    )

    drifted = [
        f"{kind}[{index}] {TEXTS[index][:30]!r}: cosine {similarity:.6f}"
        for kind in ("passage", "query")
        for index, (expected, got) in enumerate(zip(golden[kind], actual[kind]))
        if (similarity := _cosine(expected, got)) <= MIN_COSINE_SIMILARITY
    ]
    assert not drifted, (
        f"Embedding model output changed (cosine must be > {MIN_COSINE_SIMILARITY}):\n"
        + "\n".join(drifted)
        + "\n"
        + REEMBED_ADVICE
    )
