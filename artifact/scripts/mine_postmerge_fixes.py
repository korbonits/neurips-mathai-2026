#!/usr/bin/env python3
"""Mine post-merge statement fixes: commits on main that change the statement
of an already-merged declaration (same name, same file, different statement).

These are errors that SURVIVED review — complementary to the review-time
negatives from mine_review_diffs.py (first push vs merge).

Writes data/postmerge_fixes.jsonl.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_pairs import REPO, SOURCE_ROOT, doc_text  # noqa: E402
from mine_review_diffs import blob, git, norm, units_by_name  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/postmerge_fixes.jsonl")
    ap.add_argument("--branch", default="origin/main")
    args = ap.parse_args()

    commits = git("log", "--first-parent", "--format=%H\t%s", args.branch).splitlines()
    out = []
    n_scanned = 0
    for line in commits:
        sha, subject = line.split("\t", 1)
        # files modified (not added) by this commit
        changed = git("diff", "--diff-filter=M", "--name-only", f"{sha}^", sha,
                      "--", f"{SOURCE_ROOT}/*.lean", check=False).splitlines()
        if not changed:
            continue
        n_scanned += 1
        for path in changed:
            before_text, after_text = blob(f"{sha}^", path), blob(sha, path)
            if before_text is None or after_text is None:
                continue
            bu, au = units_by_name(before_text, path), units_by_name(after_text, path)
            for name in sorted(set(bu) & set(au)):
                b, a = bu[name], au[name]
                if norm(b.stmt) == norm(a.stmt):
                    continue
                doc = doc_text(a.doc_item) if a.doc_item else None
                out.append({
                    "id": f"fcfix:{sha}:{path}:{name}",
                    "informal": doc,
                    "formal_before": b.stmt,
                    "formal_after": a.stmt,
                    "unified_diff": "\n".join(difflib.unified_diff(
                        b.stmt.splitlines(), a.stmt.splitlines(),
                        fromfile=f"{path}@{sha[:12]}^", tofile=f"{path}@{sha[:12]}",
                        lineterm="")),
                    "fix_commit": sha,
                    "fix_subject": subject,
                    "path": path,
                    "decl_name": name,
                    "label": None,
                })

    with open(REPO / args.out, "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    fixes_commits = len({r["fix_commit"] for r in out})
    print(f"commits scanned (modifying existing Lean files): {n_scanned}; "
          f"post-merge statement fixes: {len(out)} declarations across "
          f"{fixes_commits} commits -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
