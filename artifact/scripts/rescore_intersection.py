#!/usr/bin/env python3
"""Rescore several conditions on the records they all answered.

For a paired comparison across conditions (blind vs existence-only hint vs
class hint), partial coverage in one condition would give the arms different
denominators. This restricts every listed condition, per model, to the
intersection of record ids present in all of them, and writes
{model}_{cond}-common_score.json for each. No API calls.

Run:  uv run --no-project --with anthropic python3 scripts/rescore_intersection.py \\
          --conditions detection,detection-exists,detection-hint
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_pairs import REPO  # noqa: E402
from multi_model_compare import score  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--triaged", default="data/negatives_triaged.jsonl")
    ap.add_argument("--labels", default="model_labels")
    ap.add_argument("--conditions", required=True)
    ap.add_argument("--suffix", default="-common")
    args = ap.parse_args()

    records = [json.loads(l) for l in open(REPO / args.triaged)
               if json.loads(l)["bucket"] != "duplicate"]
    conds = args.conditions.split(",")
    labels = REPO / args.labels
    models = sorted({f.name[:-len(f"_{conds[0]}.json")]
                     for f in labels.glob(f"*_{conds[0]}.json")})
    for m in models:
        preds = {}
        for c in conds:
            f = labels / f"{m}_{c}.json"
            if not f.exists():
                break
            preds[c] = json.loads(f.read_text())
        if len(preds) < len(conds):
            continue
        common = set.intersection(*(set(p) for p in preds.values()))
        sub = [r for r in records if r["id"] in common]
        n_sem = sum(1 for r in sub if set(r["label"]["classes"]) - {"non-semantic"})
        for c in conds:
            s = score(sub, preds[c])
            s["subset"] = f"records answered in all of {conds} ({len(sub)}; {n_sem} semantic)"
            (labels / f"{m}_{c}{args.suffix}_score.json").write_text(json.dumps(s, indent=1))
        print(f"{m}: {len(sub)} common records, {n_sem} semantic", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
