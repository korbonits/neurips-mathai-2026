#!/usr/bin/env python3
"""GitHub API enrichment for the review-diff mining (see docs/methods_notes.md).

Subcommands:
  force-pushes  Recover each merged PR's pre-force-push history via GraphQL
                HeadRefForcePushedEvent (beforeCommit), fetch the dangling
                SHAs over git, and compute the true first pushed commit.
                Writes data/first_push_map.json.
  comments      Dump inline review comments + review summaries for the PRs
                appearing in a candidates JSONL.
                Writes data/pr_review_comments.json.

Requires an authenticated `gh` CLI.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_pairs import REPO, TREE  # noqa: E402
from mine_review_diffs import PR_RE, git  # noqa: E402

OWNER, NAME = "google-deepmind", "formal-conjectures"


def gh_json(*args: str) -> object:
    p = subprocess.run(["gh", *args], cwd=TREE, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {p.stderr.strip()[:300]}")
    return json.loads(p.stdout)


def merged_prs() -> list[tuple[str, int]]:
    out = []
    for line in git("log", "--first-parent", "--format=%H\t%s", "main").splitlines():
        sha, subject = line.split("\t", 1)
        m = PR_RE.search(subject)
        if m:
            out.append((sha, int(m.group(1))))
    return out


def cmd_force_pushes(args) -> None:
    squashes = merged_prs()
    events: dict[int, list[dict]] = {}
    chunk = 50
    for i in range(0, len(squashes), chunk):
        batch = squashes[i:i + chunk]
        fields = "\n".join(
            f'p{pr}: pullRequest(number: {pr}) {{'
            f' timelineItems(first: 50, itemTypes: [HEAD_REF_FORCE_PUSHED_EVENT])'
            f' {{ nodes {{ ... on HeadRefForcePushedEvent'
            f' {{ createdAt beforeCommit {{ oid }} }} }} }} }}'
            for _, pr in batch)
        q = f'{{ repository(owner: "{OWNER}", name: "{NAME}") {{ {fields} }} }}'
        data = gh_json("api", "graphql", "-f", f"query={q}")
        repo = data["data"]["repository"]
        for _, pr in batch:
            nodes = (repo.get(f"p{pr}") or {}).get("timelineItems", {}).get("nodes", [])
            events[pr] = [n for n in nodes if n]
        print(f"graphql: {min(i + chunk, len(squashes))}/{len(squashes)} PRs",
              file=sys.stderr)

    # earliest force-push whose beforeCommit survived
    targets: dict[int, str] = {}
    n_forced = n_gcd = 0
    for pr, evs in events.items():
        if not evs:
            continue
        n_forced += 1
        evs = sorted(evs, key=lambda e: e["createdAt"])
        oid = next((e["beforeCommit"]["oid"] for e in evs if e.get("beforeCommit")), None)
        if oid is None:
            n_gcd += 1
            continue
        targets[pr] = oid

    oids = sorted(set(targets.values()))
    for i in range(0, len(oids), 50):
        subprocess.run(["git", "fetch", "-q", "origin", *oids[i:i + 50]],
                       cwd=TREE, check=False)
        print(f"fetched {min(i + 50, len(oids))}/{len(oids)} dangling SHAs",
              file=sys.stderr)

    sha_by_pr = {pr: sha for sha, pr in squashes}
    out = {}
    n_unfetchable = 0
    for pr, oid in sorted(targets.items()):
        if subprocess.run(["git", "cat-file", "-e", oid], cwd=TREE,
                          capture_output=True).returncode != 0:
            n_unfetchable += 1
            continue
        squash = sha_by_pr[pr]
        base = git("merge-base", oid, f"{squash}^", check=False).strip()
        if not base:
            continue
        chain = git("rev-list", "--reverse", f"{base}..{oid}", check=False).split()
        if not chain:
            continue
        out[str(pr)] = {"first_commit": chain[0], "pre_force_push_head": oid,
                        "original_commits": len(chain)}

    path = REPO / args.out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"merged PRs: {len(squashes)}; force-pushed: {n_forced}; "
          f"beforeCommit GC'd: {n_gcd}; unfetchable: {n_unfetchable}; "
          f"recovered first pushes: {len(out)} -> {args.out}", file=sys.stderr)


def cmd_comments(args) -> None:
    prs = sorted({json.loads(l)["pr"] for l in open(REPO / args.candidates)})
    out = {}
    for i, pr in enumerate(prs, 1):
        inline = gh_json("api", f"repos/{OWNER}/{NAME}/pulls/{pr}/comments",
                         "--paginate")
        reviews = gh_json("api", f"repos/{OWNER}/{NAME}/pulls/{pr}/reviews",
                          "--paginate")
        out[str(pr)] = {
            "inline": [{
                "path": c.get("path"),
                "line": c.get("line") or c.get("original_line"),
                "author": (c.get("user") or {}).get("login"),
                "created_at": c.get("created_at"),
                "in_reply_to": c.get("in_reply_to_id"),
                "body": c.get("body", ""),
            } for c in inline],
            "reviews": [{
                "author": (r.get("user") or {}).get("login"),
                "state": r.get("state"),
                "submitted_at": r.get("submitted_at"),
                "body": r.get("body", ""),
            } for r in reviews if r.get("state") != "COMMENTED" or r.get("body")],
        }
        if i % 20 == 0:
            print(f"comments: {i}/{len(prs)} PRs", file=sys.stderr)

    path = REPO / args.out
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    n_inline = sum(len(v["inline"]) for v in out.values())
    print(f"PRs: {len(prs)}; inline comments: {n_inline} -> {args.out}",
          file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("force-pushes")
    p1.add_argument("--out", default="data/first_push_map.json")
    p1.set_defaults(fn=cmd_force_pushes)
    p2 = sub.add_parser("comments")
    p2.add_argument("--candidates", default="data/natural_negative_candidates.jsonl")
    p2.add_argument("--out", default="data/pr_review_comments.json")
    p2.set_defaults(fn=cmd_comments)
    args = ap.parse_args()
    args.fn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
