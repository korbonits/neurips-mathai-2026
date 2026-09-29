#!/usr/bin/env python3
"""Merge model-suggested labels (suggestions_*.json) into negatives_triaged.jsonl.

Validates class/direction vocabulary against taxonomy.md and reports the
distribution. `label` itself is never touched — only `label_suggested`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_pairs import REPO  # noqa: E402

CLASSES = {
    "wrong-quantifier", "missing-hypothesis", "extraneous-hypothesis",
    "wrong-type-or-domain", "wrong-referent", "wrong-constant-or-bound",
    "wrong-connective", "wrong-answer-marker", "junk-value-trap",
    "definitional-mismatch", "vacuous-or-trivial", "non-semantic",
    "informal-changed", "other",
}
DIRECTIONS = {"before-weaker", "before-stronger", "incomparable", "equivalent",
              "unclear"}
CONFIDENCES = {"high", "medium", "low"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("suggestions", nargs="+", help="suggestions_*.json files")
    ap.add_argument("--triaged", default="data/negatives_triaged.jsonl")
    args = ap.parse_args()

    sug: dict[str, dict] = {}
    for f in args.suggestions:
        for rid, s in json.loads(Path(f).read_text()).items():
            if rid in sug:
                print(f"WARN duplicate suggestion for {rid}", file=sys.stderr)
            sug[rid] = s

    invalid = []
    for rid, s in sug.items():
        if (not set(s.get("classes", [])) <= CLASSES
                or s.get("direction") not in DIRECTIONS
                or s.get("confidence") not in CONFIDENCES
                or not s.get("rationale")):
            invalid.append(rid)
    if invalid:
        for rid in invalid:
            print(f"INVALID {rid}: {sug[rid]}", file=sys.stderr)
        return 1

    path = REPO / args.triaged
    records = [json.loads(l) for l in path.open()]
    n_applied = 0
    missing = []
    for r in records:
        if r["bucket"] == "duplicate":
            continue
        if r["id"] in sug:
            r["label_suggested"] = sug[r["id"]]
            n_applied += 1
        else:
            missing.append(r["id"])
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    labeled = [r for r in records if r.get("label_suggested")]
    cls = Counter(c for r in labeled for c in r["label_suggested"]["classes"])
    dirs = Counter(r["label_suggested"]["direction"] for r in labeled)
    conf = Counter(r["label_suggested"]["confidence"] for r in labeled)
    print(f"applied: {n_applied}; missing suggestions: {len(missing)}", file=sys.stderr)
    for rid in missing:
        print(f"  MISSING {rid}", file=sys.stderr)
    print(f"classes: {dict(cls.most_common())}", file=sys.stderr)
    print(f"direction: {dict(dirs.most_common())}", file=sys.stderr)
    print(f"confidence: {dict(conf.most_common())}", file=sys.stderr)
    disagree = [r["id"] for r in labeled if r["bucket"] == "refactor-rename"
                and "non-semantic" not in r["label_suggested"]["classes"]]
    print(f"refactor-rename overruled by model: {len(disagree)} {disagree}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
