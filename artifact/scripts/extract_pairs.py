#!/usr/bin/env python3
"""Extract (informal docstring, Lean 4 formal statement) pairs from FormalConjectures/.

Stdlib only (ruamel.yaml permitted but not needed). See docs/methods_notes.md for parsing decisions.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent          # this artifact: data/, docs/, model_labels/
TREE = Path(os.environ.get("FC_TREE", REPO)).resolve()  # a formal-conjectures checkout (git + Lean sources)
SOURCE_ROOT = "FormalConjectures"

DECL_KEYWORDS = {
    "theorem", "lemma", "def", "abbrev", "instance",
    "structure", "inductive", "example",
}
# Kinds whose body is a proof of a Prop: replace body with `:= by sorry`.
PROOF_KINDS = {"theorem", "lemma", "example"}
MODIFIERS = {"private", "protected", "noncomputable", "unsafe", "partial", "scoped"}

OPEN_BRACKETS = "([{⟨⦃"
CLOSE_BRACKETS = ")]}⟩⦄"

URL_RE = re.compile(r"https?://[^\s\)\]>,]+")
CITE_RE = re.compile(r"\[[A-Z][A-Za-z]{0,3}\d{2,4}[a-z]?\]")

# Tokens that can begin a top-level command. A column-0 line beginning with
# anything else is a continuation of the previous item (unindented statement
# continuations exist, e.g. Wikipedia/EulerBrick.lean).
COMMAND_START_RE = re.compile(
    r"(?:@\[|/--|/-!|/-|--|#\w"
    r"|(?:import|open|namespace|end|section|variable|universe|set_option"
    r"|attribute|theorem|lemma|def|abbrev|instance|structure|inductive"
    r"|example|class|mutual|macro|macro_rules|syntax|elab|notation"
    r"|infix|infixl|infixr|prefix|postfix|alias|deriving|run_cmd|initialize"
    r"|omit|include"
    r"|private|protected|noncomputable|unsafe|partial|scoped|local)\b)"
)


def code_mask(text: str) -> list[bool]:
    """mask[i] is True iff text[i] is Lean code (not comment, not string literal)."""
    mask = [False] * len(text)
    i, n = 0, len(text)
    block_depth = 0
    in_line = False
    in_str = False
    while i < n:
        c = text[i]
        if in_line:
            if c == "\n":
                in_line = False
                mask[i] = True
            i += 1
            continue
        if block_depth > 0:
            if text.startswith("/-", i):
                block_depth += 1
                i += 2
                continue
            if text.startswith("-/", i):
                block_depth -= 1
                i += 2
                continue
            i += 1
            continue
        if in_str:
            mask[i] = True  # strings count as code for offsets, but bracket scan skips them
            if c == "\\" and i + 1 < n:
                mask[i + 1] = True
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if text.startswith("/-", i):
            block_depth = 1
            i += 2
            continue
        if text.startswith("--", i):
            in_line = True
            i += 2
            continue
        if c == '"':
            in_str = True
            mask[i] = True
            i += 1
            continue
        mask[i] = True
        i += 1
    return mask


def string_mask(text: str) -> list[bool]:
    """mask[i] is True iff text[i] is inside a string literal (delimiters included)."""
    mask = [False] * len(text)
    cm = code_mask(text)
    in_str = False
    i = 0
    while i < len(text):
        if not cm[i]:
            i += 1
            continue
        c = text[i]
        if in_str:
            mask[i] = True
            if c == "\\" and i + 1 < len(text):
                mask[i + 1] = True
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            mask[i] = True
        i += 1
    return mask


def code_only(text: str) -> str:
    cm = code_mask(text)
    return "".join(c for c, m in zip(text, cm) if m)


@dataclass
class Item:
    start_line: int  # 0-indexed
    end_line: int    # exclusive
    text: str
    offset: int      # char offset of start in file
    kind: str = ""   # docstring | moddoc | comment | attr | open_in | decl | other


@dataclass
class Unit:
    path: Path
    open_items: list[Item]
    doc_item: Item | None
    attr_items: list[Item]
    decl_item: Item
    decl_kind: str = ""
    decl_name: str | None = None
    parse_error: str | None = None
    formal: str | None = None
    stmt: str | None = None  # statement text alone: no opens/attrs/docstring/proof
    attributes: list[str] = field(default_factory=list)


def line_start_states(text: str) -> list[tuple[int, bool]]:
    """(block_comment_depth, in_string) at the start of each line."""
    states = []
    depth = 0
    in_str = False
    i, n = 0, len(text)
    at_line_start = True
    while i <= n:
        if at_line_start:
            states.append((depth, in_str))
            at_line_start = False
        if i == n:
            break
        c = text[i]
        if c == "\n":
            at_line_start = True
            i += 1
            continue
        if depth > 0:
            if text.startswith("/-", i):
                depth += 1
                i += 2
                continue
            if text.startswith("-/", i):
                depth -= 1
                i += 2
                continue
            i += 1
            continue
        if in_str:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if text.startswith("/-", i):
            depth = 1
            i += 2
            continue
        if text.startswith("--", i):
            j = text.find("\n", i)
            if j == -1:
                break
            i = j
            continue
        if c == '"':
            in_str = True
        i += 1
    return states


def split_items(text: str) -> list[Item]:
    """Split file into top-level items: maximal runs starting at a column-0
    non-space character that is not inside a block comment or string."""
    states = line_start_states(text)
    lines = text.splitlines(keepends=True)
    starts = []
    offset = 0
    for ln, line in enumerate(lines):
        if line and not line[0].isspace():
            depth, in_str = states[ln]
            if depth == 0 and not in_str and COMMAND_START_RE.match(line):
                starts.append((ln, offset))
        offset += len(line)
    items = []
    for idx, (ln, off) in enumerate(starts):
        end_ln = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        end_off = starts[idx + 1][1] if idx + 1 < len(starts) else len(text)
        items.append(Item(ln, end_ln, text[off:end_off], off))
    return items


def classify(item: Item) -> str:
    t = item.text
    if t.startswith("/--"):
        return "docstring"
    if t.startswith("/-!"):
        return "moddoc"
    if t.startswith(("/-", "--")):
        return "comment"
    code = code_only(t).strip()
    if not code:
        return "comment"
    if t.startswith("@["):
        return "attr"
    toks = code.split()
    i = 0
    while i < len(toks) and toks[i] in MODIFIERS:
        i += 1
    if i == len(toks):
        return "modifier"  # e.g. `noncomputable` alone on a column-0 line
    if toks[i] in DECL_KEYWORDS:
        return "decl"
    if re.fullmatch(r"(open|set_option|omit|include)\b.*\bin", code, re.DOTALL):
        return "open_in"
    return "other"


def find_doc_end(text: str) -> int:
    """Given text starting with '/--', return offset just past its matching '-/'."""
    assert text.startswith("/--")
    depth = 1
    i = 3
    while i < len(text):
        if text.startswith("/-", i):
            depth += 1
            i += 2
            continue
        if text.startswith("-/", i):
            depth -= 1
            i += 2
            if depth == 0:
                return i
            continue
        i += 1
    raise ValueError("unterminated doc comment")


def doc_text(item: Item) -> str:
    """Docstring text verbatim, delimiters stripped, whitespace preserved."""
    end = find_doc_end(item.text)
    return item.text[3:end - 2]


def parse_attr_strings(attr_text_code: str) -> list[str]:
    """Split the contents of one `@[...]` at top-level commas."""
    inner = attr_text_code.strip()
    assert inner.startswith("@[")
    inner = inner[2:]
    depth = 0
    out, cur = [], []
    in_str = False
    i = 0
    while i < len(inner):
        c = inner[i]
        if in_str:
            cur.append(c)
            if c == "\\" and i + 1 < len(inner):
                cur.append(inner[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            cur.append(c)
        elif c in OPEN_BRACKETS:
            depth += 1
            cur.append(c)
        elif c in CLOSE_BRACKETS:
            if c == "]" and depth == 0:
                break  # closing bracket of @[...]
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    if cur:
        out.append("".join(cur))
    return [re.sub(r"\s+", " ", s).strip() for s in out if s.strip()]


NAME_STOP = set(" \t\n({[:⦃⟨")


def extract_name(code_after_kw: str) -> str | None:
    s = code_after_kw.lstrip()
    if not s or s[0] in NAME_STOP:
        return None
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "«":
            j = s.find("»", i)
            if j == -1:
                break
            out.append(s[i:j + 1])
            i = j + 1
            continue
        if c in NAME_STOP:
            break
        out.append(c)
        i += 1
    name = "".join(out)
    return name or None


def parse_decl(unit: Unit) -> None:
    text = unit.decl_item.text.rstrip()
    cm = code_mask(text)
    sm = string_mask(text)
    code = code_only(text)

    # keyword and name
    toks = code.split()
    kw_idx = 0
    while kw_idx < len(toks) and toks[kw_idx] in MODIFIERS:
        kw_idx += 1
    if kw_idx >= len(toks) or toks[kw_idx] not in DECL_KEYWORDS:
        unit.parse_error = "unrecognized declaration keyword"
        return
    unit.decl_kind = toks[kw_idx]
    m = re.search(r"\b" + unit.decl_kind + r"\b", code)
    unit.decl_name = extract_name(code[m.end():]) if m else None
    if unit.decl_name and unit.decl_name.startswith("("):
        unit.decl_name = None

    attrs_text = "".join(a.text for a in unit.attr_items)
    opens_text = "".join(o.text for o in unit.open_items)

    if unit.decl_kind not in PROOF_KINDS:
        unit.stmt = text
        unit.formal = (opens_text + attrs_text + text).rstrip() + "\n"
        return

    # Find statement/proof boundary: first `:=` at bracket depth 0 in code,
    # outside strings/comments. Refuse if a depth-0 `let`/`have`/`suffices`
    # precedes it (the `:=` would belong to the statement, not the proof).
    depth = 0
    assigns = []  # (offset, followed_by_proof_token) for each depth-0 `:=`
    guard_positions = []
    i = 0
    n = len(text)
    while i < n:
        if not cm[i] or sm[i]:
            i += 1
            continue
        c = text[i]
        if c in OPEN_BRACKETS:
            depth += 1
        elif c in CLOSE_BRACKETS:
            depth -= 1
        elif depth == 0:
            if c == ":" and i + 1 < n and text[i + 1] == "=" and cm[i + 1] and not sm[i + 1]:
                rest = text[i + 2:].lstrip()
                assigns.append((i, bool(re.match(r"(by|sorry)\b", rest))))
                i += 2
                continue
            if c in "lhs" and re.match(r"(letI?|haveI?|suffices)\b", text[i:]):
                if i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "_'"):
                    guard_positions.append(i)
        i += 1

    if not assigns:
        unit.parse_error = "no top-level ':=' found (pattern-matching or 'where' form?)"
        return
    if guard_positions and guard_positions[0] < assigns[0][0]:
        # the statement itself contains a let/have binder, so the first `:=`
        # belongs to the statement; fall back to the first `:= by`/`:= sorry`
        proof_assigns = [a for a, is_proof in assigns if is_proof]
        if not proof_assigns:
            unit.parse_error = ("top-level let/have/suffices before ':=' and no "
                                "':= by'/':= sorry': statement/proof boundary ambiguous")
            return
        boundary = proof_assigns[0]
    else:
        boundary = assigns[0][0]
    stmt = text[:boundary].rstrip()
    unit.stmt = stmt
    unit.formal = (opens_text + attrs_text + stmt).rstrip() + " := by sorry\n"


def collect_units(path: Path) -> tuple[list[Unit], int]:
    """Return (units with docstrings, total top-level declarations in file)."""
    return collect_units_from_text(path.read_text(encoding="utf-8"), path)


def collect_all_units_from_text(text: str, path: Path) -> list[Unit]:
    """All declaration units, docstring or not (used by mine_review_diffs)."""
    return collect_units_from_text(text, path, require_doc=False)[0]


def collect_units_from_text(text: str, path: Path, require_doc: bool = True) -> tuple[list[Unit], int]:
    items = split_items(text)
    for it in items:
        it.kind = classify(it)

    units: list[Unit] = []
    total_decls = 0
    pend_open: list[Item] = []
    pend_doc: Item | None = None
    pend_attrs: list[Item] = []
    queue = list(items)
    while queue:
        it = queue.pop(0)
        if it.kind == "comment":
            continue
        if it.kind == "modifier" and queue:
            nxt = queue.pop(0)
            merged = Item(it.start_line, nxt.end_line, it.text + nxt.text, it.offset)
            merged.kind = classify(merged)
            queue.insert(0, merged)
            continue
        if it.kind == "open_in":
            pend_open.append(it)
        elif it.kind == "docstring":
            # the doc comment's item may also contain what follows it on the
            # same line (attrs, the declaration itself) — split and requeue
            end = find_doc_end(it.text)
            rest = it.text[end:]
            doc_item = Item(it.start_line, it.end_line, it.text[:end], it.offset, "docstring")
            pend_doc = doc_item
            stripped = rest.lstrip()
            if stripped and code_only(rest).strip():
                rest_item = Item(it.start_line, it.end_line,
                                 stripped, it.offset + end + (len(rest) - len(stripped)))
                rest_item.kind = classify(rest_item)
                queue.insert(0, rest_item)
        elif it.kind == "attr":
            # a decl can share the attr's item: `@[foo] theorem ...` or the
            # keyword following the multi-line attribute without a col-0 break
            code = code_only(it.text)
            after = code.split("]", 1)[-1] if "]" in code else ""
            kw = after.split(None, 1)[0] if after.split() else None
            if kw in DECL_KEYWORDS or kw in MODIFIERS:
                total_decls += 1
                if pend_doc is not None or not require_doc:
                    u = Unit(path, pend_open, pend_doc, [], it)
                    parse_decl(u)
                    u.attributes = parse_attr_strings(code)
                    units.append(u)
                pend_open, pend_doc, pend_attrs = [], None, []
            else:
                pend_attrs.append(it)
        elif it.kind == "decl":
            total_decls += 1
            if pend_doc is not None or not require_doc:
                u = Unit(path, pend_open, pend_doc, pend_attrs, it)
                parse_decl(u)
                for a in pend_attrs:
                    u.attributes.extend(parse_attr_strings(code_only(a.text)))
                units.append(u)
            pend_open, pend_doc, pend_attrs = [], None, []
        else:  # moddoc, other structural commands
            pend_open, pend_doc, pend_attrs = [], None, []
    return units, total_decls


def file_imports(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if re.match(r"^import\s+\S", line):
            out.append(line.rstrip())
    return out


def unit_record(unit: Unit, commit: str) -> dict:
    rel = str(unit.path.relative_to(TREE))
    informal = doc_text(unit.doc_item)
    name = unit.decl_name or f"{unit.decl_kind or 'decl'}@L{unit.decl_item.start_line + 1}"
    first = unit.open_items[0] if unit.open_items else unit.doc_item
    refs = []
    for match in URL_RE.finditer(informal):
        u = match.group().rstrip(".,;:")
        if u not in refs:
            refs.append(u)
    for match in CITE_RE.finditer(informal):
        if match.group() not in refs:
            refs.append(match.group())
    rec = {
        "id": f"fc:{rel}:{name}",
        "source": "formal-conjectures",
        "informal": informal,
        "formal": unit.formal,
        "decl_name": unit.decl_name,
        "decl_kind": unit.decl_kind or None,
        "attributes": unit.attributes,
        "imports": file_imports(unit.path),
        "provenance": {
            "commit": commit,
            "path": rel,
            "line_start": first.start_line + 1,
            "line_end": unit.decl_item.end_line,
        },
        "references": refs,
        "label": {
            "faithful": True,
            "classes": [],
            "direction": "equivalent",
            "basis": "post-review",
        },
        "informal_ambiguous": None,
    }
    if unit.parse_error:
        rec["parse_error"] = unit.parse_error
    return rec


# ---------------------------------------------------------------- typecheck

NAMESPACE_RE = re.compile(r"^namespace\s+(\S+)", re.MULTILINE)


def context_closers(prefix_code: str) -> list[str]:
    """Compute `end ...` lines needed to close namespaces/sections opened in prefix."""
    stack: list[tuple[str, str | None]] = []
    for line in prefix_code.splitlines():
        s = line.strip()
        m = re.match(r"^namespace\s+(\S+)$", s)
        if m:
            stack.append(("namespace", m.group(1)))
            continue
        m = re.match(r"^section(?:\s+(\S+))?$", s)
        if m:
            stack.append(("section", m.group(1)))
            continue
        m = re.match(r"^end(?:\s+(\S+))?$", s)
        if m:
            if stack:
                stack.pop()
    closers = []
    for kind, nm in reversed(stack):
        closers.append(f"end {nm}" if nm else "end")
    return closers


def typecheck_sample(units: list[Unit], sample_size: int, seed: int, scratch: Path, jobs: int) -> list[tuple[str, bool, str]]:
    ok_units = [u for u in units if u.formal is not None]
    rng = random.Random(seed)
    sample = rng.sample(ok_units, min(sample_size, len(ok_units)))
    scratch.mkdir(parents=True, exist_ok=True)

    tasks = []
    for i, u in enumerate(sample):
        text = u.path.read_text(encoding="utf-8")
        cut = (u.open_items[0] if u.open_items else u.doc_item).offset
        prefix = text[:cut]
        closers = context_closers(code_only(prefix))
        body = prefix + "\n" + u.formal + "\n" + "\n".join(closers) + "\n"
        f = scratch / f"tc_{i:02d}.lean"
        f.write_text(body, encoding="utf-8")
        rel = str(u.path.relative_to(TREE))
        tasks.append((f"fc:{rel}:{u.decl_name or u.decl_kind}", f))

    def run(task):
        rid, f = task
        p = subprocess.run(
            ["lake", "env", "lean", str(f)],
            cwd=TREE, capture_output=True, text=True, timeout=900,
        )
        return (rid, p.returncode == 0, (p.stdout + p.stderr)[-2000:])

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(run, tasks))


# ------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/positives.jsonl")
    ap.add_argument("--summary", default="docs/summary.md")
    ap.add_argument("--typecheck", type=int, default=0, metavar="N",
                    help="compile a random sample of N emitted records with lake env lean")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--scratch", default=None, help="dir for typecheck scratch files")
    args = ap.parse_args()

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=TREE, capture_output=True, text=True, check=True
    ).stdout.strip()

    files = sorted((TREE / SOURCE_ROOT).rglob("*.lean"))
    all_units: list[Unit] = []
    total_decls = 0
    for f in files:
        units, n = collect_units(f)
        all_units.extend(units)
        total_decls += n

    records = [unit_record(u, commit) for u in all_units]

    # uniquify ids (same name can legitimately repeat in a file, e.g. examples)
    seen: Counter[str] = Counter()
    for r in records:
        seen[r["id"]] += 1
        if seen[r["id"]] > 1:
            r["id"] += f"#{seen[r['id']]}"

    out_path = REPO / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_err = sum(1 for r in records if r["formal"] is None)
    by_dir = Counter(r["provenance"]["path"].split("/")[1] if "/" in r["provenance"]["path"] else "(root)"
                     for r in records)
    by_attr = Counter(a for r in records for a in r["attributes"])
    by_len = sorted(records, key=lambda r: len(r["informal"]))

    def row(r):
        informal = " ".join(r["informal"].split())
        if len(informal) > 100:
            informal = informal[:97] + "..."
        return f"| `{r['id']}` | {len(r['informal'])} | {informal.replace('|', '\\|')} |"

    lines = [
        "# Positive pair extraction summary",
        "",
        f"- Commit: `{commit}`",
        f"- Total top-level declarations found (under `{SOURCE_ROOT}/`): **{total_decls}**",
        f"- Declarations with an immediately-preceding docstring: **{len(records)}**",
        f"- Records emitted: **{len(records)}** (of which parse_error with `formal=null`: **{n_err}**)",
        "",
        "## By top-level directory",
        "",
        "| directory | records |",
        "|---|---|",
    ]
    lines += [f"| {d} | {c} |" for d, c in by_dir.most_common()]
    lines += ["", "## By attribute value", "", "| attribute | records |", "|---|---|"]
    lines += [f"| `{a}` | {c} |" for a, c in by_attr.most_common()]
    lines += ["", "## 10 shortest informal statements", "", "| id | chars | text |", "|---|---|---|"]
    lines += [row(r) for r in by_len[:10]]
    lines += ["", "## 10 longest informal statements", "", "| id | chars | text (truncated) |", "|---|---|---|"]
    lines += [row(r) for r in by_len[-10:]]

    if args.typecheck:
        scratch = Path(args.scratch) if args.scratch else REPO / "data" / ".typecheck"
        results = typecheck_sample(all_units, args.typecheck, args.seed, scratch, args.jobs)
        n_ok = sum(1 for _, ok, _ in results if ok)
        lines += ["", "## Typecheck gate", "",
                  f"Sample of {len(results)} records compiled with `lake env lean` "
                  f"(formal statement appended to its file's preceding context): "
                  f"**{n_ok}/{len(results)}** compile.", ""]
        for rid, ok, log in results:
            lines.append(f"- {'PASS' if ok else 'FAIL'} `{rid}`")
            if not ok:
                lines.append("  ```")
                lines += [f"  {l}" for l in log.splitlines()[-15:]]
                lines.append("  ```")
        print(f"typecheck: {n_ok}/{len(results)} compiled", file=sys.stderr)

    (REPO / args.summary).parent.mkdir(parents=True, exist_ok=True)
    (REPO / args.summary).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"declarations: {total_decls}; with docstring: {len(records)}; "
          f"emitted: {len(records)}; parse_error: {n_err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
