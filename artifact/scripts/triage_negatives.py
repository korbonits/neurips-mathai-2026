#!/usr/bin/env python3
"""Triage natural negative candidates before hand-labeling.

- Dedupes identical (informal, before, after) triples across PRs (superseded /
  reopened PRs mine the same change twice); keeps the lowest PR number.
- Detects rename-only refactors: collects declaration renames across all files
  the PR touched (a name that disappears whose statement, after renaming,
  matches a name that appears); if applying the PR's renames to `formal_before`
  yields `formal_after` (whitespace-normalized), the candidate is bucketed
  `refactor-rename`. Everything else is `semantic-suspect`. Conservative:
  suggests, never drops.
- Groups cascades by (pr, path) so one review change isn't labeled five times.
- Attaches inline review comments on the same file (from enrich_github.py
  comments) plus review summaries.

Reads  data/natural_negative_candidates.jsonl
Writes data/negatives_triaged.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_pairs import REPO, SOURCE_ROOT  # noqa: E402
from mine_review_diffs import blob, git, norm, units_by_name  # noqa: E402


def pr_renames(pr_records: list[dict]) -> dict[str, str]:
    """Map old_name -> new_name for declarations renamed in this PR."""
    r0 = pr_records[0]
    first = r0["provenance"]["before"]["commit"]
    merged = r0["provenance"]["after"]["commit"]
    touched = git("diff", "--name-only", f"{merged}^", merged, "--",
                  f"{SOURCE_ROOT}/*.lean", check=False).splitlines()
    renames: dict[str, str] = {}
    for path in touched:
        bt, at = blob(first, path), blob(merged, path)
        if bt is None or at is None or bt == at:
            continue
        before_units = units_by_name(bt, path)
        after_units = units_by_name(at, path)
        removed = {n: u for n, u in before_units.items() if n not in after_units}
        added = {n: u for n, u in after_units.items() if n not in before_units}
        for old, ou in removed.items():
            for new, nu in added.items():
                renamed = re.sub(rf"\b{re.escape(old)}\b", new, ou.stmt)
                if norm(renamed) == norm(nu.stmt):
                    renames[old] = new
                    break
    return renames


def apply_renames(text: str, renames: dict[str, str]) -> str:
    for old, new in renames.items():
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="data/natural_negative_candidates.jsonl")
    ap.add_argument("--comments", default="data/pr_review_comments.json")
    ap.add_argument("--out", default="data/negatives_triaged.jsonl")
    args = ap.parse_args()

    records = [json.loads(l) for l in open(REPO / args.candidates)]
    comments = {}
    cpath = REPO / args.comments
    if cpath.exists():
        comments = json.loads(cpath.read_text())

    # dedupe
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        key = (norm(r.get("informal") or ""), norm(r["formal_before"]),
               norm(r["formal_after"]))
        by_key[key].append(r)
    for group in by_key.values():
        group.sort(key=lambda r: r["pr"])
        keeper = group[0]
        for dup in group[1:]:
            dup["dup_of"] = keeper["id"]

    # rename detection per PR
    by_pr: dict[int, list[dict]] = defaultdict(list)
    for r in records:
        by_pr[r["pr"]].append(r)
    renames_by_pr = {pr: pr_renames(rs) for pr, rs in sorted(by_pr.items())}

    n_dup = n_refactor = n_semantic = 0
    for r in records:
        pr = r["pr"]
        path = r["provenance"]["after"]["path"]
        r["group"] = f"{pr}:{path}"
        if "dup_of" in r:
            r["bucket"] = "duplicate"
            n_dup += 1
        else:
            renames = renames_by_pr.get(pr, {})
            if renames and norm(apply_renames(r["formal_before"], renames)) == \
                    norm(r["formal_after"]):
                r["bucket"] = "refactor-rename"
                r["renames_applied"] = {o: n for o, n in renames.items()
                                        if re.search(rf"\b{re.escape(o)}\b",
                                                     r["formal_before"])}
                n_refactor += 1
            else:
                r["bucket"] = "semantic-suspect"
                n_semantic += 1
        pc = comments.get(str(pr), {})
        r["review_comments"] = [c for c in pc.get("inline", [])
                                if c.get("path") == path]
        r["review_summaries"] = [v for v in pc.get("reviews", []) if v.get("body")]
        r.setdefault("label_suggested", None)

    with open(REPO / args.out, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_groups = len({r["group"] for r in records if r["bucket"] != "duplicate"})
    n_commented = sum(1 for r in records if r["bucket"] != "duplicate"
                      and r["review_comments"])
    print(f"records: {len(records)}; duplicates: {n_dup}; refactor-rename: "
          f"{n_refactor}; semantic-suspect: {n_semantic}; groups (pr:path): "
          f"{n_groups}; with inline comments on file: {n_commented}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
