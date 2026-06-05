"""Speech Semantic Scorer — audit-only speech act classifier.

Phase B: trains TF-IDF + LogisticRegression on combined open speech samples
to predict persuasion strategy labels. Output is audit-only and must never
affect final_q.

Split: by game_id (70/15/15), enforced by split files.

Labels: accusation, interrogation, defense, evidence_use,
        identity_declaration, call_for_action
"""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.metrics import hamming_loss
from sklearn.metrics import precision_score
from sklearn.metrics import recall_score
from sklearn.multioutput import MultiOutputClassifier

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

COMBINED_DIR = ROOT / "data" / "open" / "combined"
SPLITS_DIR = ROOT / "data" / "splits" / "open_data"
MODEL_DIR = ROOT / "models" / "open_data"
SPEECH_LABELS = [
    "accusation",
    "interrogation",
    "defense",
    "evidence_use",
    "identity_declaration",
    "call_for_action",
]


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return items


def _load_game_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return set(path.read_text(encoding="utf-8").strip().split("\n"))


def _extract_features_and_labels(samples: list[dict]) -> tuple[list[str], np.ndarray, list[str]]:
    """Extract utterances and binary label matrices from speech samples."""
    texts: list[str] = []
    labels: list[list[int]] = []
    game_ids: list[str] = []

    for s in samples:
        text = s.get("utterance", "")
        if not text or not text.strip():
            continue
        texts.append(text)

        wl = s.get("weak_labels", {})
        row = []
        for label_name in SPEECH_LABELS:
            label_info = wl.get(label_name, {})
            if isinstance(label_info, dict):
                val = label_info.get("label_value", 0) or 0
                row.append(1 if float(val) > 0.5 else 0)
            else:
                row.append(0)
        labels.append(row)
        game_ids.append(s.get("game_id", ""))

    return texts, np.array(labels, dtype=int), game_ids


def _split_by_game(
    texts: list[str],
    labels: np.ndarray,
    game_ids: list[str],
) -> tuple:
    """Split data by game_id using the pre-computed split files."""
    train_games = _load_game_ids(SPLITS_DIR / "speech_train_games.txt")
    val_games = _load_game_ids(SPLITS_DIR / "speech_val_games.txt")
    test_games = _load_game_ids(SPLITS_DIR / "speech_test_games.txt")

    # If no split files, do 70/15/15 by unique games
    if not train_games:
        unique_games = sorted(set(game_ids))
        n_train = int(len(unique_games) * 0.7)
        n_val = int(len(unique_games) * 0.15)
        train_games = set(unique_games[:n_train])
        val_games = set(unique_games[n_train : n_train + n_val])
        test_games = set(unique_games[n_train + n_val :])

    train_idx = [i for i, g in enumerate(game_ids) if g in train_games]
    val_idx = [i for i, g in enumerate(game_ids) if g in val_games]
    test_idx = [i for i, g in enumerate(game_ids) if g in test_games]

    return (
        [texts[i] for i in train_idx],
        labels[train_idx],
        [texts[i] for i in val_idx],
        labels[val_idx],
        [texts[i] for i in test_idx],
        labels[test_idx],
    )


def train_speech_act_classifier() -> dict[str, Any]:
    """Train SpeechActClassifier v0 from combined speech samples."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading speech samples...")
    samples = _load_jsonl(COMBINED_DIR / "track_b_open_speech_samples.jsonl")
    print(f"  Total samples: {len(samples)}")

    texts, labels, game_ids = _extract_features_and_labels(samples)
    print(f"  With text + labels: {len(texts)}")

    # Label distribution
    label_counts = {SPEECH_LABELS[i]: int(labels[:, i].sum()) for i in range(len(SPEECH_LABELS))}
    print(f"  Label distribution: {label_counts}")

    # Split
    X_train_text, y_train, X_val_text, y_val, X_test_text, y_test = _split_by_game(texts, labels, game_ids)
    print(f"  Train: {len(X_train_text)}, Val: {len(X_val_text)}, Test: {len(X_test_text)}")

    if len(X_train_text) < 10:
        print("  WARNING: too few training samples. Skipping model training.")
        return {"status": "SKIPPED", "reason": "insufficient_samples"}

    # TF-IDF vectorization
    print("\nVectorizing...")
    vectorizer = TfidfVectorizer(
        max_features=5000,
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.9,
        stop_words="english",
    )
    X_train = vectorizer.fit_transform(X_train_text)
    X_val = vectorizer.transform(X_val_text)
    X_test = vectorizer.transform(X_test_text)

    print(f"  Vocabulary size: {len(vectorizer.vocabulary_)}")

    # Train multi-label classifier
    print("\nTraining MultiOutputClassifier(LogisticRegression)...")
    clf = MultiOutputClassifier(
        LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42),
    )
    clf.fit(X_train, y_train)

    # Evaluate
    y_train_pred = clf.predict(X_train)
    y_val_pred = clf.predict(X_val)
    y_test_pred = clf.predict(X_test)

    train_acc = float(np.mean(y_train_pred == y_train))
    val_acc = float(np.mean(y_val_pred == y_val))
    test_acc = float(np.mean(y_test_pred == y_test))

    print(f"\n  Train accuracy (exact): {train_acc:.4f}")
    print(f"  Val accuracy (exact):   {val_acc:.4f}")
    print(f"  Test accuracy (exact):  {test_acc:.4f}")

    val_hamming = float(hamming_loss(y_val, y_val_pred))
    test_hamming = float(hamming_loss(y_test, y_test_pred))
    print(f"  Val hamming loss:  {val_hamming:.4f}")
    print(f"  Test hamming loss: {test_hamming:.4f}")

    # Per-label metrics with F1
    per_label: dict[str, dict] = {}
    test_macro_precisions = []
    test_macro_recalls = []
    test_macro_f1s = []
    for i, name in enumerate(SPEECH_LABELS):
        y_true_col = y_test[:, i]
        y_pred_col = y_test_pred[:, i]
        support = int(y_true_col.sum())
        if support > 0:
            p = float(precision_score(y_true_col, y_pred_col, zero_division=0))
            r = float(recall_score(y_true_col, y_pred_col, zero_division=0))
            f1 = float(f1_score(y_true_col, y_pred_col, zero_division=0))
            test_macro_precisions.append(p)
            test_macro_recalls.append(r)
            test_macro_f1s.append(f1)
            per_label[name] = {
                "support": support,
                "precision": round(p, 4),
                "recall": round(r, 4),
                "f1": round(f1, 4),
            }
        else:
            per_label[name] = {
                "support": 0,
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
            }

    # Macro/micro F1
    test_macro_f1 = float(np.mean(test_macro_f1s)) if test_macro_f1s else 0.0
    test_micro_f1 = float(f1_score(y_test, y_test_pred, average="micro", zero_division=0))
    test_macro_precision = float(np.mean(test_macro_precisions)) if test_macro_precisions else 0.0
    test_macro_recall = float(np.mean(test_macro_recalls)) if test_macro_recalls else 0.0

    print(f"  Test macro F1:  {test_macro_f1:.4f}")
    print(f"  Test micro F1:  {test_micro_f1:.4f}")
    print(f"  Test macro P:   {test_macro_precision:.4f}")
    print(f"  Test macro R:   {test_macro_recall:.4f}")

    # Most important features per label
    top_features: dict[str, list] = {}
    feature_names = vectorizer.get_feature_names_out()
    for i, name in enumerate(SPEECH_LABELS):
        estimator = clf.estimators_[i]
        if hasattr(estimator, "coef_"):
            coef = estimator.coef_[0]
            top_indices = np.argsort(np.abs(coef))[-10:][::-1]
            top_features[name] = [{"feature": str(feature_names[j]), "weight": float(coef[j])} for j in top_indices]

    # Save model
    model_path = MODEL_DIR / "speech_act_classifier_v0.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(
            {
                "vectorizer": vectorizer,
                "classifier": clf,
                "labels": SPEECH_LABELS,
                "version": "v0",
                "audit_only": True,
            },
            f,
        )
    print(f"\nModel saved: {model_path} ({model_path.stat().st_size} bytes)")

    # Save metrics
    metrics = {
        "model": "speech_act_classifier_v0",
        "version": "v0",
        "audit_only": True,
        "train_samples": len(X_train_text),
        "val_samples": len(X_val_text),
        "test_samples": len(X_test_text),
        "split_n_games": {
            "train": len({game_ids[i] for i in range(len(game_ids)) if i < len(X_train_text) and i < len(game_ids)}),
            "val": len(
                {
                    game_ids[i]
                    for i in range(len(X_train_text), len(X_train_text) + len(X_val_text))
                    if i < len(game_ids)
                }
            ),
            "test": len(
                {game_ids[i] for i in range(len(X_train_text) + len(X_val_text), len(game_ids)) if i < len(game_ids)}
            ),
        },
        "vocabulary_size": len(vectorizer.vocabulary_),
        "train_exact_accuracy": round(train_acc, 4),
        "val_exact_accuracy": round(val_acc, 4),
        "test_exact_accuracy": round(test_acc, 4),
        "val_hamming_loss": round(val_hamming, 4),
        "test_hamming_loss": round(test_hamming, 4),
        "test_macro_f1": round(test_macro_f1, 4),
        "test_micro_f1": round(test_micro_f1, 4),
        "test_macro_precision": round(test_macro_precision, 4),
        "test_macro_recall": round(test_macro_recall, 4),
        "label_distribution": label_counts,
        "per_label_metrics": per_label,
        "top_features": top_features,
    }

    metrics_path = COMBINED_DIR / "speech_act_classifier_v0_metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"Metrics saved: {metrics_path}")

    return {"status": "TRAINED", "metrics": metrics}


def main():
    result = train_speech_act_classifier()
    if result["status"] == "TRAINED":
        print("\nSpeechActClassifier v0 training complete.")
    else:
        print(f"\nTraining skipped: {result.get('reason', 'unknown')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
