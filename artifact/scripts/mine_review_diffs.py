#!/usr/bin/env python3
"""Mine candidate natural negatives from PR history.

This repo squash-merges every PR: `git log --merges` on main is empty and all
first-parent commits are single-parent commits titled `... (#N)`. The merge's
"second parent chain" therefore does not exist locally. Fallback (see
docs/methods_notes.md): GitHub exposes each PR's branch head as `refs/pull/N/head` over the
plain git protocol. We fetch those refs for merged PRs, walk from the
merge-base with main to the branch head, and take the earliest branch commit
as the PR's first pushed commit. Limitation: if the author force-pushed, the
original first push is unrecoverable from git and would need the GitHub API
(timeline `head_ref_force_pushed` events); such PRs contribute their
*rewritten* history here.

For every declaration present in both the first pushed commit and the merged
result (restricted to files the squash commit itself touched), the statement
text (no docstring, no proof, no attributes) is compared; records where it
differs go to data/natural_negative_candidates.jsonl.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_pairs import (  # noqa: E402
    REPO, SOURCE_ROOT, TREE, Unit, collect_all_units_from_text, doc_text,
)

PR_RE = re.compile(r"\(#(\d+)\)$")


def git(*args: str, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=TREE, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def blob(commit: str, path: str) -> str | None:
    p = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=TREE,
                       capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def norm(s: str) -> str:
    return " ".join(s.split())


def levenshtein(a: str, b: str, cap: int = 4000) -> int:
    a, b = a[:cap], b[:cap]
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def units_by_name(text: str, path: str) -> dict[str, Unit]:
    units = collect_all_units_from_text(text, Path(path))
    out = {}
    for u in units:
        if u.decl_name and u.stmt is not None:
            out.setdefault(u.decl_name, u)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/natural_negative_candidates.jsonl")
    ap.add_argument("--summary", default="docs/review_summary.md")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--no-fetch", action="store_true",
                    help="use already-fetched refs/remotes/prmine/* only")
    ap.add_argument("--limit", type=int, default=0, help="only scan first N PRs (debug)")
    ap.add_argument("--first-push-map", default=None,
                    help="JSON from enrich_github.py force-pushes: {pr: {first_commit}} "
                         "overrides the branch-history first commit for force-pushed PRs")
    args = ap.parse_args()

    fp_map: dict[int, dict] = {}
    if args.first_push_map:
        fp_map = {int(k): v for k, v in
                  json.loads((REPO / args.first_push_map).read_text()).items()}

    n_merge_commits = len(git("log", "--merges", "--format=%H", "main").split())
    log = git("log", "--first-parent", "--format=%H\t%s", "main")
    squashes = []  # (sha, pr_number, subject)
    for line in log.splitlines():
        sha, subject = line.split("\t", 1)
        m = PR_RE.search(subject)
        if m:
            squashes.append((sha, int(m.group(1)), subject))
    if args.limit:
        squashes = squashes[:args.limit]

    print(f"merge commits on main: {n_merge_commits}; first-parent commits with "
          f"a PR number: {len(squashes)} -> repo squash-merges; falling back to "
          f"refs/pull/N/head (see docs/methods_notes.md)", file=sys.stderr)

    if not args.no_fetch:
        chunk = 100
        prs = [pr for _, pr, _ in squashes]
        for i in range(0, len(prs), chunk):
            refspecs = [f"+refs/pull/{n}/head:refs/remotes/prmine/{n}"
                        for n in prs[i:i + chunk]]
            subprocess.run(["git", "fetch", "-q", args.remote, *refspecs],
                           cwd=TREE, check=False)
            print(f"fetched {min(i + chunk, len(prs))}/{len(prs)} PR head refs",
                  file=sys.stderr)

    candidates = []
    n_scanned = n_with_head = n_multi_commit = 0
    prs_with_change = set()
    for sha, pr, subject in squashes:
        n_scanned += 1
        head = git("rev-parse", "--verify", "-q", f"refs/remotes/prmine/{pr}",
                   check=False).strip()
        if not head:
            continue
        n_with_head += 1
        base = git("merge-base", head, f"{sha}^", check=False).strip()
        if not base:
            continue
        branch_commits = git("rev-list", "--reverse", f"{base}..{head}",
                             check=False).split()
        if not branch_commits:
            continue
        first = branch_commits[0]
        first_source = "branch_history"
        if pr in fp_map:
            first = fp_map[pr]["first_commit"]
            first_source = "force_push_recovery"
        if len(branch_commits) > 1 or pr in fp_map:
            n_multi_commit += 1

        touched = git("diff", "--name-only", f"{sha}^", sha, "--",
                      f"{SOURCE_ROOT}/*.lean", check=False).splitlines()
        for path in touched:
            before_text = blob(first, path)
            after_text = blob(sha, path)
            if before_text is None or after_text is None or before_text == after_text:
                continue
            before_units = units_by_name(before_text, path)
            after_units = units_by_name(after_text, path)
            for name in sorted(set(before_units) & set(after_units)):
                bu, au = before_units[name], after_units[name]
                if norm(bu.stmt) == norm(au.stmt):
                    continue
                doc = doc_text(au.doc_item) if au.doc_item else None
                udiff = "\n".join(difflib.unified_diff(
                    bu.stmt.splitlines(), au.stmt.splitlines(),
                    fromfile=f"{path}@{first[:12]}", tofile=f"{path}@{sha[:12]}",
                    lineterm="",
                ))
                candidates.append({
                    # path-qualified: decl names repeat across files in one PR
                    "id": f"fcpr:{sha}:{path}:{name}",
                    "pr": pr,
                    "informal": doc,
                    "formal_before": bu.stmt,
                    "formal_after": au.stmt,
                    "unified_diff": udiff,
                    "provenance": {
                        "before": {"commit": first, "path": path,
                                   "line_start": bu.decl_item.start_line + 1,
                                   "line_end": bu.decl_item.end_line},
                        "after": {"commit": sha, "path": path,
                                  "line_start": au.decl_item.start_line + 1,
                                  "line_end": au.decl_item.end_line},
                        "pr_head": head,
                        "merge_base": base,
                        "first_push_source": first_source,
                        "squash_subject": subject,
                    },
                    "label": None,
                    "edit_distance": levenshtein(norm(bu.stmt), norm(au.stmt)),
                })
                prs_with_change.add(pr)

    out_path = REPO / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for r in candidates:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    smallest = sorted(candidates, key=lambda r: r["edit_distance"])[:15]
    lines = [
        "# Natural negative mining summary",
        "",
        "## Merge strategy",
        "",
        f"`git log --merges` on `main` finds **{n_merge_commits}** merge commits; all "
        f"**{len(squashes)}** first-parent commits carry a `(#N)` PR number: the repo "
        "**squash-merges**. The PR's first pushed commit is not recoverable from the "
        "squashed history, so this script fetches `refs/pull/N/head` from the remote "
        "and uses the earliest commit after the merge-base with `main` as the first "
        "pushed commit. PRs whose authors force-pushed contribute their rewritten "
        "history only; recovering the true first push for those needs the GitHub API "
        "(timeline `head_ref_force_pushed` events).",
        "",
        "## Counts",
        "",
        f"- Squash (merge) commits scanned: **{n_scanned}**",
        f"- PR head refs found on remote: **{n_with_head}**",
        f"- PRs with more than one branch commit (review iterations visible): **{n_multi_commit}**",
        f"- PRs with at least one statement change: **{len(prs_with_change)}**",
        f"- Total candidate records: **{len(candidates)}**",
        "",
        "## 15 smallest statement diffs (by edit distance, whitespace-normalized)",
        "",
        "| edit dist | pr | id | diff |",
        "|---|---|---|---|",
    ]
    for r in smallest:
        d = " ".join(r["unified_diff"].splitlines()[2:])
        if len(d) > 160:
            d = d[:157] + "..."
        lines.append(f"| {r['edit_distance']} | #{r['pr']} | `{r['id']}` "
                     f"| {d.replace('|', '\\|')} |")

    (REPO / args.summary).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"scanned: {n_scanned}; with head ref: {n_with_head}; "
          f"multi-commit: {n_multi_commit}; PRs with statement change: "
          f"{len(prs_with_change)}; candidates: {len(candidates)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
