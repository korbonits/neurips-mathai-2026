#!/usr/bin/env python3
"""Build file context for the context-augmented detection condition.

For each negative candidate, reconstruct what a reviewer looking at the pull
request would have had on screen: the file's imports and `open`s, plus the
auxiliary declarations the candidate statement actually depends on.

Context is read from the file *at the record's own before-commit*, so nothing
downstream of the error can leak in — in particular not the reviewer's fix.
The target declaration itself is excluded; the harness already supplies it as
`formal_before`.

Dependencies are resolved by name: identifiers appearing in the statement are
matched against the file's top-level declaration names (fully qualified and by
final segment, since a statement inside `namespace Foo` refers to `Foo.bar` as
`bar`), then expanded transitively up to --hops.

Needs a formal-conjectures checkout for `git show`; point FC_TREE at it.

Run:  FC_TREE=../formal-conjectures uv run --no-project python3 scripts/build_context.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_pairs import REPO, collect_all_units_from_text  # noqa: E402

FC_TREE = Path(os.environ.get("FC_TREE", REPO)).resolve()

IMPORT_RE = re.compile(r"^import\s+\S")
OPEN_RE = re.compile(r"^open\s+\S")
NAMESPACE_RE = re.compile(r"^(namespace|section)\s+(\S+)")
# Lean identifiers: letters (incl. greek/subscripts), digits, _ ' ! ? and dots.
IDENT_RE = re.compile(r"[A-Za-z_Ͱ-Ͽᴀ-ᶿ][\w'!?Ͱ-Ͽ₀-ₜ]*"
                      r"(?:\.[A-Za-z_Ͱ-Ͽ][\w'!?Ͱ-Ͽ₀-ₜ]*)*")


def git_show(commit: str, path: str) -> str | None:
    p = subprocess.run(["git", "-C", str(FC_TREE), "show", f"{commit}:{path}"],
                       capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def idents(text: str) -> set[str]:
    out = set()
    for m in IDENT_RE.finditer(text):
        tok = m.group(0)
        out.add(tok)
        out.update(tok.split("."))  # `Foo.bar` also refers to `bar`
    return out


def decl_text(unit) -> str:
    """The declaration as it appears, attributes and docstring stripped."""
    return (unit.stmt or unit.decl_item.text).strip()


def build(record: dict, hops: int, budget: int) -> dict | None:
    prov = record.get("provenance", {}).get("before") or {}
    commit, path = prov.get("commit"), prov.get("path")
    if not commit or not path:
        return None
    text = git_show(commit, path)
    if text is None:
        return None

    units = collect_all_units_from_text(text, Path(path))
    by_name: dict[str, object] = {}
    for u in units:
        if u.decl_name:
            by_name.setdefault(u.decl_name, u)
            by_name.setdefault(u.decl_name.split(".")[-1], u)

    target = record.get("formal_before") or ""
    # Never offer the record's own declaration back as context.
    target_names = {u.decl_name for u in units
                    if u.decl_name and decl_text(u).strip() == target.strip()}
    tgt_line = prov.get("line_start")
    if tgt_line is not None:
        for u in units:
            if u.decl_item.start_line <= tgt_line - 1 < u.decl_item.end_line:
                target_names.add(u.decl_name)

    wanted, frontier = [], idents(target)
    seen: set[str] = set()
    for _ in range(max(1, hops)):
        nxt: set[str] = set()
        for name in sorted(frontier):
            u = by_name.get(name)
            if u is None or u.decl_name in target_names or u.decl_name in seen:
                continue
            seen.add(u.decl_name)
            wanted.append(u)
            nxt |= idents(decl_text(u))
        frontier = nxt - seen
        if not frontier:
            break

    wanted.sort(key=lambda u: u.decl_item.start_line)
    lines = text.splitlines()
    header = [l.rstrip() for l in lines if IMPORT_RE.match(l) or OPEN_RE.match(l)]
    header += [l.rstrip() for l in lines if NAMESPACE_RE.match(l)]

    parts, used, truncated = [], 0, False
    for u in wanted:
        block = decl_text(u)
        if used + len(block) > budget:
            truncated = True
            break
        parts.append(block)
        used += len(block)

    ctx = "\n".join(header)
    if parts:
        ctx += "\n\n" + "\n\n".join(parts)
    if truncated:
        ctx += "\n\n-- (context truncated)"
    return {
        "id": record["id"],
        "context": ctx.strip(),
        "context_decls": [u.decl_name for u in wanted[:len(parts)]],
        "context_chars": len(ctx),
        "truncated": truncated,
        "source_commit": commit,
        "source_path": path,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--triaged", default="data/negatives_triaged.jsonl")
    ap.add_argument("--out", default="data/negatives_context.jsonl")
    ap.add_argument("--hops", type=int, default=2)
    ap.add_argument("--budget", type=int, default=6000,
                    help="max characters of declaration context per record")
    args = ap.parse_args()

    records = [json.loads(l) for l in open(REPO / args.triaged)
               if json.loads(l)["bucket"] != "duplicate"]
    out, failed = [], 0
    for r in records:
        c = build(r, args.hops, args.budget)
        if c is None:
            failed += 1
            continue
        out.append(c)
    with open(REPO / args.out, "w") as f:
        for c in out:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    n_ctx = sum(1 for c in out if c["context_decls"])
    chars = sorted(c["context_chars"] for c in out)
    print(f"wrote {len(out)} context records -> {args.out} "
          f"({failed} unresolvable)", file=sys.stderr)
    print(f"  with >=1 auxiliary decl: {n_ctx}/{len(out)}; "
          f"truncated: {sum(c['truncated'] for c in out)}", file=sys.stderr)
    if chars:
        print(f"  context chars: median {chars[len(chars)//2]}, "
              f"max {chars[-1]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
