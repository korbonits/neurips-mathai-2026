#!/usr/bin/env python3
"""Rescore natural detection predictions on the class-matched subset.

The synthetic negatives cover only the classes an operator exists for. To
compare natural and synthetic detection without a class-mix confound, this
rescores each model's existing natural detection predictions on the subset of
records whose gold classes are all synthesizable (plus every non-semantic
record), and writes {model}_detection-matched_score.json. No API calls.

Run:  uv run --no-project --with anthropic python3 scripts/rescore_matched.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_pairs import REPO  # noqa: E402
from make_synthetic_negatives import OPERATORS  # noqa: E402
from multi_model_compare import is_semantic, score  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--triaged", default="data/negatives_triaged.jsonl")
    ap.add_argument("--labels", default="model_labels")
    ap.add_argument("--source", default="detection")
    ap.add_argument("--target", default="detection-matched")
    args = ap.parse_args()

    records = [json.loads(l) for l in open(REPO / args.triaged)
               if json.loads(l)["bucket"] != "duplicate"]
    synth = set(OPERATORS)
    matched = [r for r in records
               if not is_semantic(r["label"]["classes"])
               or all(c in synth for c in r["label"]["classes"] if c != "non-semantic")]
    n_sem = sum(1 for r in matched if is_semantic(r["label"]["classes"]))
    print(f"matched subset: {len(matched)} records, {n_sem} semantic "
          f"(full: {len(records)}, "
          f"{sum(1 for r in records if is_semantic(r['label']['classes']))} semantic)",
          file=sys.stderr)

    labels = REPO / args.labels
    n = 0
    for f in sorted(labels.glob(f"*_{args.source}.json")):
        stem = f.name[:-len(f"_{args.source}.json")]
        preds = json.loads(f.read_text())
        s = score(matched, preds)
        s["subset"] = "gold classes all synthesizable, plus non-semantic"
        (labels / f"{stem}_{args.target}_score.json").write_text(json.dumps(s, indent=1))
        n += 1
        if s["n"]:
            print(f"  {stem}: n={s['n']} P={s['precision']:.2f} R={s['recall']:.2f} "
                  f"F1={s['f1']:.2f}", file=sys.stderr)
    print(f"wrote {n} {args.target} score files", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
