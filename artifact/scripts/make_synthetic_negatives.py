#!/usr/bin/env python3
"""Synthetic negatives: evaluator-injected perturbations of reviewed positives.

Builds the comparison set for the natural-vs-synthetic experiment. Each record
takes a post-review (informal, formal) pair, applies one rule-based
perturbation drawn from the error taxonomy, and keeps the result only if the
perturbed declaration still typechecks in its own file context. This mirrors
how alignment scorers and LLM judges are usually validated, and lets the same
detection prompt run over both natural and synthetic errors.

Design constraints, so the comparison is not confounded:
  * class mix matches the gold negatives (data/negatives_final.jsonl), scaled
    by --scale, for every class an operator exists for;
  * the semantic : non-semantic ratio matches the natural detection task, with
    unperturbed positives as the non-semantic controls;
  * source declarations exclude anything that appears among the natural
    candidates, so no statement is judged in both arms;
  * perturbations are text rules, not model output, so the synthetic arm is
    evaluator-injected in the same sense as prior work.

Classes with no operator (wrong-referent, definitional-mismatch, other) are
reported as unsynthesizable; that gap is itself a finding.

Output schema matches data/negatives_triaged.jsonl closely enough for
multi_model_compare.py --dataset: id, informal, formal_before, formal_after,
bucket, label, provenance, plus a `perturbation` block.

Needs a formal-conjectures checkout at the freeze commit (FC_TREE) with a lake
build for the typecheck gate.

Run:  FC_TREE=../formal-conjectures uv run --no-project python3 \\
          scripts/make_synthetic_negatives.py --jobs 6
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_pairs import (REPO, code_only, collect_all_units_from_text,  # noqa: E402
                           context_closers)

FC_TREE = Path(os.environ.get("FC_TREE", REPO)).resolve()

DECL_RE = re.compile(r"^(?:(?:private|protected|nonrec|noncomputable)\s+)*"
                     r"(theorem|lemma)\s+(\S+)", re.M)
PROOF_RE = re.compile(r"\s*:=\s*(by\s+)?sorry\s*$", re.S)
NUM_TYPES = ["ℕ", "ℤ", "ℚ", "ℝ"]
TYPE_SWAP = {"ℕ": ["ℤ", "ℝ"], "ℤ": ["ℕ", "ℚ"], "ℚ": ["ℝ", "ℤ"], "ℝ": ["ℚ", "ℕ"]}


# --------------------------------------------------------------- signature

def split_signature(stmt: str) -> tuple[str, str, str] | None:
    """(head, binders, type) at the first depth-0 ` : ` after the name."""
    m = DECL_RE.match(stmt)
    if not m:
        return None
    i = m.end()
    depth = 0
    pairs = {"(": ")", "[": "]", "{": "}", "⦃": "⦄", "⟨": "⟩"}
    closers = set(pairs.values())
    j = i
    while j < len(stmt):
        ch = stmt[j]
        if ch in pairs:
            depth += 1
        elif ch in closers:
            depth -= 1
        elif ch == ":" and depth == 0 and stmt[j + 1:j + 2] != "=" \
                and stmt[j - 1:j] in (" ", "\n"):
            return stmt[:i], stmt[i:j], stmt[j:]
        j += 1
    return None


def binder_groups(binders: str) -> list[tuple[int, int, str]]:
    """Top-level (start, end, text) spans of `(...)`, `{...}`, `⦃...⦄` groups."""
    out, depth, start = [], 0, None
    opens, closes = "({⦃[", ")}⦄]"
    for k, ch in enumerate(binders):
        if ch in opens:
            if depth == 0:
                start = k
            depth += 1
        elif ch in closes:
            depth -= 1
            if depth == 0 and start is not None:
                out.append((start, k + 1, binders[start:k + 1]))
                start = None
    return out


def group_parts(g: str) -> tuple[str, str, str] | None:
    """`(names : type)` -> (names, type, bracket) or None."""
    if g[0] not in "({⦃":
        return None
    inner = g[1:-1]
    depth = 0
    for k, ch in enumerate(inner):
        if ch in "({[⦃⟨":
            depth += 1
        elif ch in ")}]⦄⟩":
            depth -= 1
        elif ch == ":" and depth == 0:
            return inner[:k].strip(), inner[k + 1:].strip(), g[0]
    return None


def fresh(name: str, stmt: str) -> str:
    n = name
    k = 0
    while re.search(rf"\b{re.escape(n)}\b", stmt):
        k += 1
        n = f"{name}{k}"
    return n


def ident_used(name: str, text: str) -> bool:
    return re.search(rf"(?<![\w'.]){re.escape(name)}(?![\w'])", text) is not None


# --------------------------------------------------------------- operators
# Each takes (stmt, rng) and returns (new_stmt, direction, detail) or None.

def op_wrong_quantifier(stmt, rng):
    hits = [m.start() for m in re.finditer(r"∀|∃", stmt)]
    if not hits:
        return None
    k = rng.choice(hits)
    q = stmt[k]
    new = stmt[:k] + ("∃" if q == "∀" else "∀") + stmt[k + 1:]
    return new, "incomparable", f"swapped {q} at offset {k}"


def _hyp_groups(sig):
    head, binders, typ = sig
    out = []
    for s, e, g in binder_groups(binders):
        parts = group_parts(g)
        if not parts:
            continue
        names, ty, br = parts
        # A hypothesis: single name, Prop-looking type (has a relation or ∀/∃/¬)
        if len(names.split()) == 1 and re.search(r"[=<>≤≥≠∈∉∣∀∃¬↔→∧∨]|Prime|Irrational", ty) \
                and not re.match(r"^(Type|Prop|Sort)", ty):
            out.append((s, e, names, ty, br))
    return out


def op_missing_hypothesis(stmt, rng):
    sig = split_signature(stmt)
    if not sig:
        return None
    head, binders, typ = sig
    cands = [(s, e, n) for s, e, n, ty, br in _hyp_groups(sig)
             if not ident_used(n, typ) and not ident_used(n, binders[e:])]
    if not cands:
        return None
    s, e, n = rng.choice(cands)
    nb = (binders[:s] + binders[e:]).replace("\n    \n", "\n")
    nb = re.sub(r"[ \t]+\n", "\n", nb)
    return head + nb + typ, "before-stronger", f"dropped hypothesis {n}"


def _var_groups(sig, types=NUM_TYPES):
    head, binders, typ = sig
    out = []
    for s, e, g in binder_groups(binders):
        parts = group_parts(g)
        if not parts:
            continue
        names, ty, br = parts
        if ty in types:
            for v in names.split():
                out.append((s, e, v, ty, br))
    return out


def op_extraneous_hypothesis(stmt, rng):
    sig = split_signature(stmt)
    if not sig:
        return None
    head, binders, typ = sig
    vs = _var_groups(sig)
    if not vs:
        return None
    s, e, v, ty, br = rng.choice(vs)
    hyp = f"(h{fresh('_' + v, stmt)} : 0 < {v})" if ty == "ℕ" \
        else f"(h{fresh('_' + v, stmt)} : {v} ≠ 0)"
    nb = binders[:e] + " " + hyp + binders[e:]
    return head + nb + typ, "before-weaker", f"added {hyp}"


def op_wrong_type(stmt, rng):
    sig = split_signature(stmt)
    if not sig:
        return None
    head, binders, typ = sig
    vs = _var_groups(sig)
    if not vs:
        return None
    s, e, v, ty, br = rng.choice(vs)
    g = binders[s:e]
    new_ty = rng.choice(TYPE_SWAP[ty])
    ng = re.sub(rf":\s*{ty}\)$|:\s*{ty}\}}$|:\s*{ty}⦄$",
                lambda m: m.group(0).replace(ty, new_ty), g)
    if ng == g:
        return None
    return head + binders[:s] + ng + binders[e:] + typ, "incomparable", \
        f"{v} : {ty} -> {new_ty}"


def op_wrong_bound(stmt, rng):
    sig = split_signature(stmt)
    if not sig:
        return None
    head, binders, typ = sig
    rel = [(m.start(), m.group(0)) for m in re.finditer(r"≤|<(?!-)|≥|>", typ)]
    nums = [(m.start(), m.group(0)) for m in re.finditer(r"(?<![\w_.'])\d+(?![\w_.'])", typ)]
    choices = [("rel", *r) for r in rel] + [("num", *n) for n in nums]
    if not choices:
        return None
    kind, k, tok = rng.choice(choices)
    if kind == "rel":
        rep = {"≤": "<", "<": "≤", "≥": ">", ">": "≥"}[tok]
    else:
        rep = str(int(tok) + rng.choice([1, -1]) if int(tok) > 0 else int(tok) + 1)
    nt = typ[:k] + rep + typ[k + len(tok):]
    return head + binders + nt, "incomparable", f"{tok} -> {rep} in type"


def op_wrong_connective(stmt, rng):
    sig = split_signature(stmt)
    if not sig:
        return None
    head, binders, typ = sig
    hits = [(m.start(), m.group(0)) for m in re.finditer(r"∧|∨|↔|→", typ)]
    if not hits:
        return None
    k, tok = rng.choice(hits)
    rep = {"∧": "∨", "∨": "∧", "↔": "→", "→": "↔"}[tok]
    return head + binders + typ[:k] + rep + typ[k + 1:], "incomparable", \
        f"{tok} -> {rep} in type"


def op_wrong_answer_marker(stmt, rng):
    hits = [(m.start(), m.group(1)) for m in re.finditer(r"answer\((True|False)\)", stmt)]
    if not hits:
        return None
    k, val = rng.choice(hits)
    rep = "False" if val == "True" else "True"
    new = stmt[:k] + f"answer({rep})" + stmt[k + len(f"answer({val})"):]
    return new, "incomparable", f"answer({val}) -> answer({rep})"


def op_junk_value(stmt, rng):
    sig = split_signature(stmt)
    if not sig:
        return None
    head, binders, typ = sig
    # (a) a nonzero/positivity guard on a variable that appears next to `/`
    for s, e, n, ty, br in _hyp_groups(sig):
        m = re.match(r"^(?:0\s*<\s*(\S+)|(\S+)\s*≠\s*0|1\s*≤\s*(\S+))$", ty.strip())
        if not m:
            continue
        v = next(g for g in m.groups() if g)
        if re.search(rf"/\s*\(?{re.escape(v)}\b|\b{re.escape(v)}\s*⁻¹", typ) \
                and not ident_used(n, typ):
            nb = binders[:s] + binders[e:]
            return head + nb + typ, "incomparable", \
                f"dropped guard {n} : {ty} with {v} in a denominator"
    # (b) a subtracted ℤ/ℝ/ℚ variable moved to ℕ: truncated subtraction
    # (c) a ℝ/ℚ variable in a denominator moved to ℕ: floor division
    for s, e, v, ty, br in _var_groups(sig, ["ℤ", "ℚ", "ℝ"]):
        vv = re.escape(v)
        why = None
        if re.search(rf"\b{vv}\s*-|-\s*{vv}\b", typ):
            why = "under subtraction"
        elif ty != "ℤ" and re.search(rf"/\s*\(?{vv}\b|\b{vv}\s*⁻¹", typ):
            why = "in a denominator"
        if why:
            g = binders[s:e]
            ng = re.sub(rf":\s*{ty}([)}}⦄])$", r": ℕ\1", g)
            if ng != g:
                return head + binders[:s] + ng + binders[e:] + typ, "incomparable", \
                    f"{v} : {ty} -> ℕ {why}"
    return None


def op_vacuous(stmt, rng):
    sig = split_signature(stmt)
    if not sig:
        return None
    head, binders, typ = sig
    vs = [x for x in _var_groups(sig) if x[3] == "ℕ"]
    if not vs:
        return None
    s, e, v, ty, br = rng.choice(vs)
    hyp = f"(h{fresh('_' + v, stmt)} : {v} < 0)"
    return head + binders[:e] + " " + hyp + binders[e:] + typ, "before-weaker", \
        f"added unsatisfiable {hyp}"


OPERATORS = {
    "wrong-quantifier": op_wrong_quantifier,
    "missing-hypothesis": op_missing_hypothesis,
    "extraneous-hypothesis": op_extraneous_hypothesis,
    "wrong-type-or-domain": op_wrong_type,
    "wrong-constant-or-bound": op_wrong_bound,
    "wrong-connective": op_wrong_connective,
    "wrong-answer-marker": op_wrong_answer_marker,
    "junk-value-trap": op_junk_value,
    "vacuous-or-trivial": op_vacuous,
}
UNSYNTHESIZABLE = ["wrong-referent", "definitional-mismatch", "other"]


# --------------------------------------------------------------- typecheck

def split_formal(formal: str) -> tuple[str, str, str]:
    """positives `formal` -> (attr prefix, statement, proof tail)."""
    m = DECL_RE.search(formal)
    if not m:
        raise ValueError("no theorem/lemma in formal")
    attrs, rest = formal[:m.start()], formal[m.start():]
    pm = PROOF_RE.search(rest)
    if pm:
        return attrs, rest[:pm.start()], rest[pm.start():]
    return attrs, rest.rstrip(), ""


class Prefixes:
    """File prefix (text before the declaration's unit) per positive id."""

    def __init__(self):
        self.cache: dict[str, list] = {}

    def get(self, rec: dict) -> str | None:
        path = FC_TREE / rec["provenance"]["path"]
        if str(path) not in self.cache:
            text = path.read_text(encoding="utf-8")
            self.cache[str(path)] = (text, collect_all_units_from_text(text, path))
        text, units = self.cache[str(path)]
        for u in units:
            if u.decl_name == rec["decl_name"]:
                first = (u.open_items[0] if u.open_items else
                         u.doc_item if u.doc_item else
                         u.attr_items[0] if u.attr_items else u.decl_item)
                return text[:first.offset]
        return None


def typecheck(body: str, scratch: Path, tag: str) -> tuple[bool, str]:
    f = scratch / f"synth_{tag}.lean"
    f.write_text(body, encoding="utf-8")
    p = subprocess.run(["lake", "env", "lean", str(f)], cwd=FC_TREE,
                       capture_output=True, text=True, timeout=900)
    return p.returncode == 0, (p.stdout + p.stderr)[-1500:]


# --------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--positives", default="data/positives.jsonl")
    ap.add_argument("--gold", default="data/negatives_final.jsonl")
    ap.add_argument("--triaged", default="data/negatives_triaged.jsonl")
    ap.add_argument("--out", default="data/negatives_synthetic.jsonl")
    ap.add_argument("--report", default="docs/synthetic_negatives.md")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--scale", type=float, default=1.0,
                    help="multiply every per-class target and the control count")
    ap.add_argument("--oversample", type=int, default=3,
                    help="candidates generated per kept record, before the typecheck gate")
    ap.add_argument("--oversample-class", action="append", default=[],
                    metavar="CLASS=N", help="per-class override, e.g. wrong-type-or-domain=12")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--skip-typecheck", action="store_true")
    ap.add_argument("--limit-per-class", type=int, default=0, help="smoke test")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    gold = [json.loads(l) for l in open(REPO / args.gold)]
    triaged = [json.loads(l) for l in open(REPO / args.triaged)
               if json.loads(l)["bucket"] != "duplicate"]
    positives = [json.loads(l) for l in open(REPO / args.positives)]

    # Target class mix from gold (multi-label counted once per record: the
    # synthetic record carries a single class, so we assign each gold record
    # to its first class for the count).
    gold_mix = Counter(c for r in gold for c in r["label"]["classes"]
                       if c != "non-semantic")
    n_controls = sum(1 for r in triaged
                     if not any(c != "non-semantic" for c in r["label"]["classes"]))
    # Class proportions follow the paper's class table (multi-label counts);
    # the semantic total follows the gold record count, so the
    # semantic : control ratio matches the natural task.
    synth_mix = {c: n for c, n in gold_mix.items() if c in OPERATORS}
    total = round(len(gold) * args.scale)
    share = {c: n / sum(synth_mix.values()) * total for c, n in synth_mix.items()}
    targets = {c: int(v) for c, v in share.items()}
    for c, _ in sorted(share.items(), key=lambda kv: kv[1] - int(kv[1]),
                       reverse=True)[:total - sum(targets.values())]:
        targets[c] += 1
    targets = {c: max(1, n) for c, n in targets.items()}
    if args.limit_per_class:
        targets = {c: min(n, args.limit_per_class) for c, n in targets.items()}
    n_controls = round(n_controls * args.scale)

    natural_names = {r["id"].split(":")[-1] for r in triaged}
    natural_paths = {r["provenance"]["before"]["path"] for r in triaged}
    pool = [p for p in positives
            if p["decl_kind"] in ("theorem", "lemma")
            and (p["informal"] or "").strip()
            and p["decl_name"] not in natural_names]
    rng.shuffle(pool)
    print(f"pool: {len(pool)} theorem/lemma positives outside the natural set "
          f"({len(natural_paths)} natural files)", file=sys.stderr)

    # Generate candidates per class.
    cands: dict[str, list[dict]] = defaultdict(list)
    used_sources: set[str] = set()
    over = {c: args.oversample for c in targets}
    for kv in args.oversample_class:
        c, n = kv.split("=")
        over[c] = int(n)
    # Scarce operators draw first so plentiful ones cannot starve them of
    # source statements (each positive is perturbed at most once).
    priority = ["junk-value-trap", "wrong-constant-or-bound", "wrong-connective",
                "vacuous-or-trivial", "wrong-quantifier", "extraneous-hypothesis",
                "wrong-type-or-domain", "missing-hypothesis", "wrong-answer-marker"]
    targets = {c: targets[c] for c in priority if c in targets} | \
        {c: n for c, n in targets.items() if c not in priority}
    for cls, target in targets.items():
        want = target * over[cls]
        for p in pool:
            if len(cands[cls]) >= want:
                break
            if p["id"] in used_sources:
                continue
            try:
                attrs, stmt, tail = split_formal(p["formal"])
            except ValueError:
                continue
            res = OPERATORS[cls](stmt, rng)
            if not res or res[0] == stmt:
                continue
            new_stmt, direction, detail = res
            used_sources.add(p["id"])
            cands[cls].append({"src": p, "attrs": attrs, "stmt": stmt,
                               "tail": tail or " := by sorry",
                               "new_stmt": new_stmt, "direction": direction,
                               "detail": detail, "cls": cls})
    for cls in targets:
        print(f"  {cls}: {len(cands[cls])} candidates for target {targets[cls]}",
              file=sys.stderr)

    # Typecheck gate.
    prefixes = Prefixes()
    scratch = REPO / "scratch" / "synthetic"
    scratch.mkdir(parents=True, exist_ok=True)
    flat = [c for cls in targets for c in cands[cls]]
    for i, c in enumerate(flat):
        c["prefix"] = prefixes.get(c["src"])
        c["tag"] = f"{i:04d}"
    flat = [c for c in flat if c["prefix"] is not None]

    cache_f = scratch / "typecheck_cache.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}

    def check(c):
        if args.skip_typecheck:
            return True, "skipped"
        closers = context_closers(code_only(c["prefix"]))
        body = (c["prefix"] + "\n" + c["attrs"] + c["new_stmt"] + c["tail"]
                + "\n" + "\n".join(closers) + "\n")
        key = hashlib.sha256(body.encode()).hexdigest()
        if key in cache:
            return cache[key], "cached"
        ok, log = typecheck(body, scratch, c["tag"])
        cache[key] = ok
        return ok, log

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        for c, (ok, log) in zip(flat, ex.map(check, flat)):
            c["ok"], c["log"] = ok, log
    cache_f.write_text(json.dumps(cache))
    print(f"typecheck: {sum(1 for c in flat if c['log'] == 'cached')} cached, "
          f"{sum(1 for c in flat if c['log'] != 'cached')} run", file=sys.stderr)
    for f in scratch.glob("synth_*.lean"):
        f.unlink()

    # Keep up to target per class, in generation order.
    kept: list[dict] = []
    stats = {}
    for cls, target in targets.items():
        ok = [c for c in cands[cls] if c.get("ok")]
        stats[cls] = (target, len(cands[cls]), len(ok), min(target, len(ok)))
        kept += ok[:target]
    kept_sources = {c["src"]["id"] for c in kept}

    # Controls: unperturbed positives, disjoint from every perturbed source.
    controls = [p for p in pool if p["id"] not in used_sources
                and DECL_RE.search(p["formal"])][:n_controls]

    freeze = positives[0]["provenance"]["commit"]
    out = []
    for c in kept:
        p = c["src"]
        out.append({
            "id": f"synth:{c['cls']}:{p['decl_name']}",
            "pr": None,
            "informal": p["informal"],
            "formal_before": c["new_stmt"],
            "formal_after": c["stmt"],
            "bucket": "synthetic",
            "label": {"classes": [c["cls"]], "direction": c["direction"],
                      "confidence": "high", "rationale": c["detail"]},
            "provenance": {"commit": freeze, "path": p["provenance"]["path"],
                           "decl_name": p["decl_name"], "positive_id": p["id"]},
            "perturbation": {"operator": c["cls"], "detail": c["detail"],
                             "typechecked": not args.skip_typecheck},
        })
    for p in controls:
        try:
            _, stmt, _ = split_formal(p["formal"])
        except ValueError:
            continue
        out.append({
            "id": f"synth:control:{p['decl_name']}",
            "pr": None,
            "informal": p["informal"],
            "formal_before": stmt,
            "formal_after": stmt,
            "bucket": "synthetic-control",
            "label": {"classes": ["non-semantic"], "direction": "equivalent",
                      "confidence": "high", "rationale": "unperturbed post-review statement"},
            "provenance": {"commit": freeze, "path": p["provenance"]["path"],
                           "decl_name": p["decl_name"], "positive_id": p["id"]},
            "perturbation": None,
        })
    rng.shuffle(out)
    with open(REPO / args.out, "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_sem = len(kept)
    lines = ["# Synthetic negatives", "",
             f"Generated by `scripts/make_synthetic_negatives.py --seed {args.seed} "
             f"--scale {args.scale} --oversample {args.oversample}"
             + "".join(f" --oversample-class {kv}" for kv in args.oversample_class)
             + (" --skip-typecheck" if args.skip_typecheck else "") + "`.", "",
             f"Records: **{len(out)}** = {n_sem} perturbed + {len(controls)} unperturbed "
             f"controls (natural task: {len(gold)} semantic of {len(triaged)}).", "",
             "| class | gold | target | candidates | typechecked | kept |",
             "|---|---|---|---|---|---|"]
    for cls, (t, nc, nok, nk) in stats.items():
        lines.append(f"| {cls} | {gold_mix[cls]} | {t} | {nc} | {nok} | {nk} |")
    for cls in UNSYNTHESIZABLE:
        lines.append(f"| {cls} | {gold_mix.get(cls, 0)} | -- | -- | -- | 0 (no operator) |")
    short = [cls for cls, (t, nc, nok, nk) in stats.items() if nk < t]
    lines += ["", f"Classes short of target: {', '.join(short) if short else 'none'}.",
              f"Unsynthesizable classes cover {sum(gold_mix.get(c, 0) for c in UNSYNTHESIZABLE)} "
              f"of {len(gold)} gold records; compare natural F1 on the matched "
              "class subset as well as on the full set."]
    (REPO / args.report).write_text("\n".join(lines) + "\n")
    print("\n".join(lines[4:]), file=sys.stderr)
    print(f"wrote {len(out)} records -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
