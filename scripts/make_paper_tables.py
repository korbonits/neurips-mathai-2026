#!/usr/bin/env python3
"""Generate only the seven tables used by the MATH-AI manuscript."""
from __future__ import annotations

import json

import os

import re

from collections import Counter

from pathlib import Path

HERE = Path(__file__).resolve().parent.parent

ARTIFACT = Path(os.environ.get("FCREPO", HERE / "artifact")).resolve()

OUT = HERE / "paper" / "tables"

LABELS = ARTIFACT / "model_labels"

DISPLAY = {
    "claude-haiku-4-5": "Claude Haiku 4.5",
    "claude-sonnet-5": "Claude Sonnet 5",
    "claude-opus-5": "Claude Opus 5",
    "claude-fable-5": "Claude Fable 5",
    "openai_gpt-5.6-terra-pro": "GPT-5.6 Terra Pro",
    "google_gemini-3.1-pro-preview": "Gemini 3.1 Pro",
    "moonshotai_kimi-k3": "Kimi K3",
    "meta_muse-spark-1.2": "Muse Spark 1.2",
    "deepseek_deepseek-v4-pro": "DeepSeek V4 Pro",
    "qwen_qwen3.8-max": "Qwen 3.8 Max",
    "x-ai_grok-4.6": "Grok 4.6",
    "z-ai_glm-5.3": "GLM 5.3",
}

ORDER = list(DISPLAY)

SEMANTICS_CLASSES = ["wrong-type-or-domain", "junk-value-trap",
                     "wrong-answer-marker", "definitional-mismatch"]

GLOSS = {
    "wrong-answer-marker": r"\texttt{answer(True/False)} has incorrect polarity or wraps the wrong proposition",
    "missing-hypothesis": r"informal side condition absent (positivity, distinctness, $n \ge 1$)",
    "wrong-type-or-domain": r"wrong carrier: $\mathbb{N}$ vs $\mathbb{Z}$ vs $\mathbb{Q}$ vs $\mathbb{R}$, meaning-changing coercion",
    "junk-value-trap": r"meaning shifts through Lean junk values: $x/0$, $\mathbb{N}$ subtraction, $\inf\emptyset$",
    "definitional-mismatch": r"auxiliary definition does not capture the informal notion",
    "other": r"none of the above; explained in the record's note",
    "extraneous-hypothesis": r"formal statement assumes more than the informal one",
    "wrong-quantifier": r"$\exists/\forall$ swapped, wrong scope or order",
    "wrong-referent": r"points at the wrong declaration or constant",
    "vacuous-or-trivial": r"trivially true or false (empty range, wrong index set)",
    "wrong-connective": r"$\wedge/\vee/\to/\leftrightarrow$ misuse, misplaced negation",
    "wrong-constant-or-bound": r"off-by-one, wrong constant, strict vs non-strict inequality",
}

def esc(s: str) -> str:
    return s.replace("&", "\\&").replace("%", "\\%").replace("_", "\\_")

_RUN_RE = re.compile(r"_run(\d+)_score\.json$")

def load_runs(slug: str, cond: str) -> list[dict]:
    """Every score file for (model, condition), bare file first then _runN."""
    files = [f for f in [LABELS / f"{slug}_{cond}_score.json"] if f.exists()]
    files += sorted(LABELS.glob(f"{slug}_{cond}_run*_score.json"),
                    key=lambda f: int(_RUN_RE.search(f.name).group(1)))
    return [json.loads(f.read_text()) for f in files]

def scored(runs: list[dict]) -> list[dict]:
    """Runs that actually produced judgements."""
    return [r for r in runs if r.get("n")]

def cell(runs: list[dict], key: str) -> str:
    """Mean over runs, with a half-range spread when there is more than one."""
    vals = [r[key] for r in scored(runs)]
    if not vals:
        return "--"
    mean = sum(vals) / len(vals)
    if len(vals) == 1:
        return f"{mean:.2f}"
    spread = (max(vals) - min(vals)) / 2
    return f"{mean:.2f}\\,{{\\scriptsize$\\pm${spread:.2f}}}"

def mean_of(runs: list[dict], key: str) -> float | None:
    vals = [r[key] for r in scored(runs)]
    return sum(vals) / len(vals) if vals else None

def class_recall(runs: list[dict]) -> dict[str, tuple[float, int]]:
    """Per-class (mean hits, gold total) across runs."""
    rs = scored(runs)
    if not rs:
        return {}
    out: dict[str, tuple[float, int]] = {}
    for c in {c for r in rs for c in r["per_class_recall"]}:
        pairs = [r["per_class_recall"].get(c, (0, 0)) for r in rs]
        out[c] = (sum(p[0] for p in pairs) / len(pairs),
                  max(p[1] for p in pairs))
    return out

def class_label(name: str) -> str:
    label = esc(name)
    return r"\textbf{" + label + "}" if name in SEMANTICS_CLASSES else label

def signed_delta(value: float) -> str:
    rounded = f"{value:+.2f}"
    return "0.00" if float(rounded) == 0 else rounded

def coverage(runs: list[dict]) -> str:
    ns = sorted({r["n"] for r in runs})
    return "--" if not ns else str(ns[0]) if len(ns) == 1 else f"{ns[0]}--{ns[-1]}"

def placeholder(note: str, cols: int = 1) -> str:
    return ("\\begin{tabular}{@{}l@{}}\n\\toprule\n"
            f"\\textcolor{{red}}{{\\textbf{{[TODO: {note}]}}}} \\\\\n"
            "\\bottomrule\n\\end{tabular}\n")

def models_with(cond: str) -> list[str]:
    return [m for m in ORDER if scored(load_runs(m, cond))]

def table_negatives_classes() -> str:
    recs = [json.loads(l) for l in open(ARTIFACT / "data/negatives_final.jsonl")]
    counts = Counter(c for r in recs for c in r["label"]["classes"]
                     if c != "non-semantic")
    missing = [c for c in counts if c not in GLOSS]
    assert not missing, f"no gloss for {missing}"
    rows = "\n".join(f"    {class_label(c)} & {GLOSS[c]} & {n} \\\\"
                     for c, n in counts.most_common())
    return (
        "\\begin{tabular}{@{}lp{0.66\\textwidth}r@{}}\n\\toprule\n"
        "error class & meaning & records \\\\\n"
        f"\\midrule\n{rows}\n\\bottomrule\n\\end{{tabular}}\n")

def table_model_comparison() -> str:
    rows = []
    for name in ORDER:
        a, d = load_runs(name, "assisted"), load_runs(name, "detection")
        if not a and not d:
            continue
        partial = any(0 < r["n"] < 360 for r in a + d)
        mark = r"$^{\dagger}$" if partial else ""
        cells = []
        for runs in (a, d):
            cells.extend([coverage(runs)] + [cell(runs, k) for k in ("precision", "recall", "f1", "kappa")])
        rows.append(f"    {esc(DISPLAY[name])}{mark} & " + " & ".join(cells) + r" \\")
    return (
        r"\begin{tabular}{lrrrrrrrrrr}" + "\n" + r"\toprule" + "\n"
        r" & \multicolumn{5}{c}{assisted} & \multicolumn{5}{c}{detection} \\" + "\n"
        r"\cmidrule(lr){2-6}\cmidrule(lr){7-11}" + "\n"
        r"model & $n$ & P & R & F1 & $\kappa$ & $n$ & P & R & F1 & $\kappa$ \\" + "\n"
        + r"\midrule" + "\n" + "\n".join(rows) + "\n" + r"\bottomrule" + "\n" + r"\end{tabular}" + "\n")

def table_class_recall(cond: str = "detection") -> str:
    per = {m: class_recall(load_runs(m, cond)) for m in models_with(cond)}
    if not per:
        return placeholder(f"{cond} condition not yet run")
    classes = sorted({c for p in per.values() for c in p},
                     key=lambda c: (-max(p.get(c, (0, 0))[1] for p in per.values()), c))
    # Models that answered fewer than 360 records carry a dagger, as in the
    # main table and figure, and a cell whose answered gold count falls short
    # of the row total is printed as found/answered.
    partial = {m for m in per if {r["n"] for r in scored(load_runs(m, cond))} - {360}}
    header = " & ".join("\\rot{" + esc(DISPLAY[n]) + (r"$^{\dagger}$" if n in partial else "") + "}" for n in per)
    rows = []
    for c in classes:
        tot = max(p.get(c, (0, 0))[1] for p in per.values())
        cells = []
        for p in per.values():
            hit, n = p.get(c, (0, 0))
            cells.append("--" if n == 0 else f"{hit:.0f}/{n}" if n < tot else f"{hit:.0f}")
        rows.append(f"    {class_label(c)} ({tot}) & {' & '.join(cells)} \\\\")
    body = "\n".join(rows)
    return (
        f"\\begin{{tabular}}{{l{'r' * len(per)}}}\n\\toprule\n"
        f"error class (n) & {header} \\\\\n\\midrule\n{body}\n"
        "\\bottomrule\n\\end{tabular}\n")

def table_condition_delta(cond: str, label: str, note: str,
                          base: str = "detection") -> str:
    """A base condition vs. a variant, per model, with the F1 delta and
    recall on the Lean-semantics classes that motivate the experiment."""
    names = [m for m in ORDER if scored(load_runs(m, cond))]
    if not names:
        return placeholder(note)
    rows = []
    for name in names:
        d, x = load_runs(name, base), load_runs(name, cond)
        fd, fx = mean_of(d, "f1"), mean_of(x, "f1")
        delta = "--" if fd is None or fx is None else f"${signed_delta(fx - fd)}$"
        rd, rx = class_recall(d), class_recall(x)

        def sem(rec):
            hit = sum(rec.get(c, (0, 0))[0] for c in SEMANTICS_CLASSES)
            tot = sum(rec.get(c, (0, 0))[1] for c in SEMANTICS_CLASSES)
            return f"{hit:.0f}/{tot}" if tot else "--"
        ns = {r["n"] for r in scored(x)} - {360}
        mark = r"$^{\dagger}$" if ns else ""
        rows.append(
            f"    {esc(DISPLAY[name])}{mark} & {coverage(x)} & "
            f"{cell(d,'f1')} & {cell(x,'precision')} & {cell(x,'recall')} & "
            f"{cell(x,'f1')} & {delta} & {sem(rd)} & {sem(rx)} \\\\")
    body = "\n".join(rows)
    return (
        "\\begin{tabular}{lrrrrrrrr}\n\\toprule\n"
        f" & & {base} & \\multicolumn{{3}}{{c}}{{{label}}} & & "
        "\\multicolumn{2}{c}{Lean-semantics recall} \\\\\n"
        "\\cmidrule(lr){3-3}\\cmidrule(lr){4-6}\\cmidrule(lr){8-9}\n"
        f"model & $n$ & F1 & P & R & F1 & $\\Delta$F1 & {base} & {label} \\\\\n"
        f"\\midrule\n{body}\n\\bottomrule\n\\end{{tabular}}\n")

def _is_semantic(classes) -> bool:
    s = set(classes or [])
    return bool(s) and s != {"non-semantic"}

def table_hint_compare() -> str:
    """Blind vs existence-only hint vs class hint: recall and pooled
    Lean-semantics recall per model. Isolates what naming the class adds."""
    arms = [("detection", "blind"), ("detection-exists", "error-present"), ("detection-hint", "class named")]
    names = [m for m in ORDER if scored(load_runs(m, "detection-hint"))]
    if not names:
        return placeholder("hint conditions not yet run")
    def sem(rec):
        hit = sum(rec.get(c, (0, 0))[0] for c in SEMANTICS_CLASSES)
        tot = sum(rec.get(c, (0, 0))[1] for c in SEMANTICS_CLASSES)
        return f"{hit:.0f}/{tot}" if tot else "--"
    rows = []
    for m in names:
        cells = []
        # Prefer the paired rescoring on records every arm answered
        # (rescore_intersection.py), so partial coverage in one arm does not
        # give the arms different denominators.
        paired = all(scored(load_runs(m, f"{c}-common")) for c, _ in arms)
        # A shared set with almost no semantic records says nothing about
        # class recall (Kimi K3's existence-hint run hangs at the provider).
        if paired:
            s0 = scored(load_runs(m, f"{arms[0][0]}-common"))[0]
            if s0["tp"] + s0["fn"] < 10:
                continue
        for cond, _ in arms:
            runs = load_runs(m, f"{cond}-common") if paired else load_runs(m, cond)
            # Binary recall is by construction under either hint (the hint
            # states the binary label), so report what the hint cannot hand
            # over: exact class-set agreement and per-class recall.
            cells.append(f"{cell(runs, 'class_set_agreement')} & {sem(class_recall(runs))}")
        if paired:
            n = scored(load_runs(m, f"{arms[0][0]}-common"))[0]["n"]
            mark = r"$^{\dagger}$" if n < 360 else ""
        else:
            ns = {r["n"] for c, _ in arms[1:] for r in scored(load_runs(m, c))} - {359, 360}
            n = min(ns) if ns else 360
            mark = r"$^{\dagger}$" if ns else ""
        rows.append(f"    {esc(DISPLAY[m])}{mark} & {n} & " + " & ".join(cells) + " \\\\")
    body = "\n".join(rows)
    head = " & ".join(f"\\multicolumn{{2}}{{c}}{{{lab}}}" for _, lab in arms)
    return (
        "\\begin{tabular}{lrrrrrrr}\n\\toprule\n"
        f" & & {head} \\\\\n\\cmidrule(lr){{3-4}}\\cmidrule(lr){{5-6}}\\cmidrule(lr){{7-8}}\n"
        "model & $n$ & class set & Lean-sem. & class set & Lean-sem. & class set & Lean-sem. \\\\\n"
        f"\\midrule\n{body}\n\\bottomrule\n\\end{{tabular}}\n")

ASCII = {"∀ᶠ": "ALL^f", "𝓡": "R", "𝓘": "I", "⊤": "top", "τ": "tau", "ő": "o", "ω": "omega",
         "²": "^2", "×": "x", "ᶠ": "^f",
         "∀": "ALL", "∃": "EX", "→": "->", "↔": "<->", "∧": "/\\", "∨": "\\/", "¬": "~",
         "≤": "<=", "≥": ">=", "≠": "!=", "ℕ": "Nat", "ℤ": "Int", "ℚ": "Rat", "ℝ": "Real",
         "∈": "in", "∉": "notin", "⁻¹": "^-1", "·": "*", "∑": "SUM", "∏": "PROD", "∞": "oo",
         "₀": "0", "₁": "1", "₂": "2", "ε": "eps", "δ": "delta", "α": "alpha", "σ": "sigma",
         "π": "pi", "λ": "fun", "↦": "=>", "⊆": "subseteq", "∅": "empty", "√": "sqrt",
         "—": "--", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
         "…": "...", "\u00a0": " "}

def table_distractor() -> str:
    """Distractor control for the class hint: every record gets a class the
    reviewer did not assign. On controls the hint asserts an error; on errors
    it names the wrong class. Reports how often models reject the hint on
    controls, echo it on errors, and still find a gold class on errors, next
    to the same quantities under the true class hint."""
    import hashlib
    cond = "detection-distractor"
    names = [m for m in ORDER if (LABELS / f"{m}_{cond}.json").exists()]
    if not names:
        return placeholder("distractor condition not yet run")
    recs = [json.loads(l) for l in open(ARTIFACT / "data/negatives_triaged.jsonl")
            if json.loads(l)["bucket"] != "duplicate"]
    pool = ["wrong-quantifier", "missing-hypothesis", "extraneous-hypothesis",
            "wrong-type-or-domain", "wrong-referent", "wrong-constant-or-bound",
            "wrong-connective", "wrong-answer-marker", "junk-value-trap",
            "definitional-mismatch", "vacuous-or-trivial"]

    def distractor(r):
        gold = set(r["label"]["classes"])
        cands = [c for c in pool if c not in gold]
        h = int(hashlib.sha256(r["id"].encode()).hexdigest(), 16)
        return cands[h % len(cands)]

    rows = []
    for m in names:
        pd = json.loads((LABELS / f"{m}_{cond}.json").read_text())
        ph_f = LABELS / f"{m}_detection-hint.json"
        ph = json.loads(ph_f.read_text()) if ph_f.exists() else {}
        c_n = c_rej = e_n = e_echo = e_found = h_n = h_found = 0
        for r in recs:
            sem = _is_semantic(r["label"]["classes"])
            q = pd.get(r["id"])
            if q is not None:
                cls = set(q.get("classes") or [])
                if not sem:
                    c_n += 1; c_rej += not _is_semantic(list(cls))
                else:
                    e_n += 1; e_echo += distractor(r) in cls
                    e_found += bool(cls & (set(r["label"]["classes"]) - {"non-semantic"}))
            qh = ph.get(r["id"])
            if qh is not None and sem:
                h_n += 1
                h_found += bool(set(qh.get("classes") or []) & (set(r["label"]["classes"]) - {"non-semantic"}))
        rows.append(f"    {esc(DISPLAY[m])} & {c_rej}/{c_n} & {e_echo}/{e_n} & {e_found}/{e_n} & {h_found}/{h_n} \\\\")
    body = "\n".join(rows)
    return (
        "\\begin{tabular}{lrrrr}\n\\toprule\n"
        " & controls & \\multicolumn{2}{c}{errors, wrong class hinted} & errors, gold class hinted \\\\\n"
        "\\cmidrule(lr){2-2}\\cmidrule(lr){3-4}\\cmidrule(lr){5-5}\n"
        "model & hint rejected & wrong class echoed & a gold class found & a gold class found \\\\\n"
        f"\\midrule\n{body}\n\\bottomrule\n\\end{{tabular}}\n")

TABLES = {
    'negative_classes': table_negatives_classes,
    'model_comparison': table_model_comparison,
    'class_recall': table_class_recall,
    'context_delta': lambda: table_condition_delta('detection-context', 'context-augmented', 'context-augmented condition not yet run'),
    'nocomments_delta': lambda: table_condition_delta('assisted-nocomments', 'correction only', 'correction only condition not yet run', base='assisted'),
    'hint_compare': table_hint_compare,
    'distractor': table_distractor,
}

if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    for name, generate in TABLES.items():
        text = generate()
        assert 'TODO' not in text, name
        (OUT / (name + '.tex')).write_text(text)
    print(f'Generated {len(TABLES)} workshop tables')
