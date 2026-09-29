#!/usr/bin/env python3
"""Multi-model labeling comparison on the negative-candidate corpus.

Runs each model over the 360 non-duplicate candidates in the conditions
registered in CONDITIONS, scoring predictions against the human gold labels
(`label`):

  assisted           reviewer-approved after-statement + comments (the
                     condition the original pre-fill ran in)
  detection          informal + formal_before only: genuine error detection
  detection-context  detection plus the file's imports and the auxiliary
                     declarations the statement depends on, taken from the
                     record's own before-commit (scripts/build_context.py)
  detection-synthetic  the detection prompt unchanged, over a synthetic
                     perturbation set supplied with --dataset

Adding a prompt variant means adding one line to CONDITIONS.

Repeated sampling: --run N writes {model}_{cond}_run{N}.json so runs do not
collide, and the paper's table generator averages whatever runs it finds.

Providers: Anthropic models natively (needs ANTHROPIC_API_KEY). Other
providers plug in later via the same chunk files — the frozen prompt is
docs/labeling_prompt.md.

Run:  uv run --with anthropic python3 scripts/multi_model_compare.py
      uv run --with anthropic python3 scripts/multi_model_compare.py \
          --conditions detection-context --models claude-fable-5 --run 1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_pairs import REPO  # noqa: E402

DEFAULT_MODELS = ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5",
                  "claude-fable-5"]
OPENROUTER_MODELS = ["openai/gpt-5.6-terra-pro", "google/gemini-3.1-pro-preview",
                     "moonshotai/kimi-k3", "meta/muse-spark-1.2",
                     "deepseek/deepseek-v4-pro", "qwen/qwen3.8-max",
                     "x-ai/grok-4.6", "z-ai/glm-5.3"]
PRICES = {  # $ per MTok (input, output)
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-fable-5": (10.00, 50.00),
    "openai/gpt-5.6-terra-pro": (2.00, 12.00),
    "google/gemini-3.1-pro-preview": (2.00, 12.00),
    "moonshotai/kimi-k3": (3.00, 15.00),
    "meta/muse-spark-1.2": (1.25, 4.25),
    "deepseek/deepseek-v4-pro": (1.60, 3.20),
    "qwen/qwen3.8-max": (2.00, 6.00),
    "x-ai/grok-4.6": (2.00, 6.00),
    "z-ai/glm-5.3": (1.40, 4.40),
}

CLASSES = ["wrong-quantifier", "missing-hypothesis", "extraneous-hypothesis",
           "wrong-type-or-domain", "wrong-referent", "wrong-constant-or-bound",
           "wrong-connective", "wrong-answer-marker", "junk-value-trap",
           "definitional-mismatch", "vacuous-or-trivial", "non-semantic",
           "informal-changed", "other"]

SYSTEM_COMMON = f"""You label candidate Lean 4 formalization errors for a research corpus.
Each record pairs an informal mathematical statement (a docstring) with a formal
Lean 4 statement `formal_before`. Judge whether `formal_before` faithfully
formalizes the informal statement.

Error classes (multi-label): {", ".join(CLASSES)}.
- wrong-quantifier: exists/forall swapped, wrong scope or order
- missing-hypothesis: a side condition in the informal statement is absent
- extraneous-hypothesis: the formal statement assumes more than the informal one
- wrong-type-or-domain: wrong carrier (N vs Z vs Q vs R, Fin n vs N, codomain)
- wrong-referent: references the wrong declaration or constant
- wrong-constant-or-bound: off-by-one, wrong constant, strict vs non-strict
- wrong-connective: and/or/implies/iff misuse, misplaced negation
- wrong-answer-marker: the project's answer(...) marker wrong or misplaced
- junk-value-trap: meaning diverges via Lean junk values (x/0, N-subtraction, sInf of empty)
- definitional-mismatch: an auxiliary def used by the statement does not capture the informal notion
- vacuous-or-trivial: trivially true/false contrary to informal intent
- non-semantic: rename/style only, meaning unchanged (i.e. no error)
- informal-changed / other: as named.

Direction of `formal_before` relative to the informal intent: one of
before-weaker, before-stronger, incomparable, equivalent, unclear
(equivalent only together with non-semantic).

Output: a single JSON object, no prose, no code fences, mapping every input
record id to {{"classes": [...], "direction": "...", "confidence": "high"|"medium"|"low",
"rationale": "<exactly one sentence naming the decisive difference>"}}.
Every id in the input must appear. If `informal` is null, judge on the other
fields and say "no docstring" in the rationale."""

SYSTEM_ASSISTED = SYSTEM_COMMON + """

`formal_after` is the reviewer-approved corrected statement (answer key) and
`comments` are the PR reviewers' remarks; use both. A record with bucket
"refactor-rename" was machine-suspected non-semantic — confirm or overrule."""

# Ablation: the answer key without the reviewers' prose, so the assisted
# score can be split into reading the formal diff and reading the comments.
SYSTEM_ASSISTED_NOCOMMENTS = SYSTEM_COMMON + """

`formal_after` is the reviewer-approved corrected statement (answer key); use
it. You are not shown the reviewers' comments. A record with bucket
"refactor-rename" was machine-suspected non-semantic — confirm or overrule."""

SYSTEM_DETECTION = SYSTEM_COMMON + """

You see ONLY the informal statement and `formal_before` — no answer key.
If `formal_before` is a faithful formalization, output "classes": ["non-semantic"]
with direction "equivalent"."""

SYSTEM_CONTEXT = SYSTEM_COMMON + """

You see the informal statement, `formal_before`, and `context`: the imports,
`open`s, and the auxiliary declarations from the same file (at the same commit)
that `formal_before` depends on. There is no answer key. Use the context to
reason about how the statement elaborates rather than how it reads: what an
auxiliary definition actually unfolds to, which carrier a coercion lands in,
and whether an operation can reach a Lean junk value on some input.
If `formal_before` is a faithful formalization, output "classes": ["non-semantic"]
with direction "equivalent"."""

SYSTEM_HINT = SYSTEM_COMMON + """

You see the informal statement, `formal_before`, and `hint`: the error class
or classes a human reviewer assigned to this record, or "non-semantic" when
the reviewer found no error. There is no answer key beyond that. The hint
tells you what kind of problem to look for, not where it is or whether the
hint is right; verify it against the statement and output the classes you can
actually substantiate. If you cannot substantiate any error, output
"classes": ["non-semantic"] with direction "equivalent"."""

SYSTEM_EXISTS = SYSTEM_COMMON + """

You see the informal statement, `formal_before`, and `hint`: either
"error-present", meaning a human reviewer found a semantic error in this
record (of some class you are not told), or "non-semantic", meaning the
reviewer found no error. There is no answer key beyond that. Find and classify
the error if the hint says one is present; verify rather than assume. If you
cannot substantiate any error, output "classes": ["non-semantic"] with
direction "equivalent"."""


ASSISTED_FIELDS = ("id", "bucket", "informal", "formal_before", "formal_after",
                   "renames_applied")
DETECTION_FIELDS = ("id", "informal", "formal_before")


def _assisted(r: dict, aux: dict) -> dict:
    slim = {k: r.get(k) for k in ASSISTED_FIELDS}
    slim["comments"] = [c["body"] for c in r.get("review_comments", [])][:6]
    return slim


def _assisted_nocomments(r: dict, aux: dict) -> dict:
    return {k: r.get(k) for k in ASSISTED_FIELDS}


def _detection(r: dict, aux: dict) -> dict:
    return {k: r.get(k) for k in DETECTION_FIELDS}


def _detection_context(r: dict, aux: dict) -> dict:
    slim = {k: r.get(k) for k in DETECTION_FIELDS}
    slim["context"] = (aux.get(r["id"]) or {}).get("context") or ""
    return slim


def _detection_hint(r: dict, aux: dict) -> dict:
    """Oracle class hint: an upper bound separating failing to look from
    failing to verify. Leaks the gold class set, by design."""
    slim = {k: r.get(k) for k in DETECTION_FIELDS}
    slim["hint"] = sorted(set(r["label"]["classes"]))
    return slim


DISTRACTOR_POOL = ["wrong-quantifier", "missing-hypothesis", "extraneous-hypothesis",
                   "wrong-type-or-domain", "wrong-referent", "wrong-constant-or-bound",
                   "wrong-connective", "wrong-answer-marker", "junk-value-trap",
                   "definitional-mismatch", "vacuous-or-trivial"]


def _detection_distractor(r: dict, aux: dict) -> dict:
    """Distractor control for the class hint: same prompt as detection-hint,
    but the hint is wrong on every record. Errors get a class the reviewer did
    not assign; controls get an asserted error class. Deterministic per id, so
    the run is reproducible. Measures how often models reject a misleading
    hint rather than echo it."""
    import hashlib
    slim = {k: r.get(k) for k in DETECTION_FIELDS}
    gold = set(r["label"]["classes"])
    pool = [c for c in DISTRACTOR_POOL if c not in gold]
    h = int(hashlib.sha256(r["id"].encode()).hexdigest(), 16)
    slim["hint"] = [pool[h % len(pool)]]
    return slim


def _detection_exists(r: dict, aux: dict) -> dict:
    """Existence-only hint: the control for the class hint. Same leak on the
    non-semantic side, no class information on the semantic side, so the
    recall difference between the two isolates what naming the class adds."""
    slim = {k: r.get(k) for k in DETECTION_FIELDS}
    sem = any(c != "non-semantic" for c in r["label"]["classes"])
    slim["hint"] = "error-present" if sem else "non-semantic"
    return slim


# Condition registry. Each entry is (system prompt, record builder). Adding a
# prompt variant means adding a line here; --conditions takes any of these keys
# and output files are named {model}_{condition}[_run{N}].json.
CONDITIONS = {
    "assisted": (SYSTEM_ASSISTED, _assisted),
    "assisted-nocomments": (SYSTEM_ASSISTED_NOCOMMENTS, _assisted_nocomments),
    "detection": (SYSTEM_DETECTION, _detection),
    "detection-context": (SYSTEM_CONTEXT, _detection_context),
    "detection-synthetic": (SYSTEM_DETECTION, _detection),
    "detection-hint": (SYSTEM_HINT, _detection_hint),
    "detection-exists": (SYSTEM_EXISTS, _detection_exists),
    "detection-distractor": (SYSTEM_HINT, _detection_distractor)
}

# Conditions that need data/negatives_context.jsonl loaded.
NEEDS_CONTEXT = {"detection-context"}


def build_chunks(records: list[dict], cond: str, size: int,
                 aux: dict | None = None) -> list[list[dict]]:
    _, builder = CONDITIONS[cond]
    aux = aux or {}
    out = [builder(r, aux) for r in records]
    return [out[i:i + size] for i in range(0, len(out), size)]


def parse_json_object(text: str) -> dict:
    """Parse one or more concatenated JSON objects, merged in order."""
    text = re.sub(r"```(?:json)?", "", text)
    dec = json.JSONDecoder()
    out: dict = {}
    i = text.find("{")
    if i == -1:
        raise ValueError("no JSON object in response")
    found = False
    while i != -1 and i < len(text):
        try:
            obj, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict):
            out.update(obj)
            found = True
        i = text.find("{", end)
    if not found:
        raise ValueError("no parseable JSON object in response")
    return out


class Runner:
    def __init__(self):
        self.anthropic_client = None
        self.openrouter_client = None
        self.usage = defaultdict(lambda: [0, 0])
        self.lock = threading.Lock()

    def _call_once(self, model: str, system: str, payload: str,
                   max_tokens: int = 16000) -> tuple[str, str]:
        """Returns (text, stop_or_finish_reason)."""
        if model.startswith("claude-"):
            if self.anthropic_client is None:
                self.anthropic_client = anthropic.Anthropic()
            if max_tokens > 16000:
                with self.anthropic_client.messages.stream(
                        model=model, max_tokens=max_tokens, system=system,
                        messages=[{"role": "user", "content": payload}]) as st:
                    resp = st.get_final_message()
            else:
                resp = self.anthropic_client.messages.create(
                    model=model, max_tokens=max_tokens, system=system,
                    messages=[{"role": "user", "content": payload}],
                )
            with self.lock:
                self.usage[model][0] += resp.usage.input_tokens
                self.usage[model][1] += resp.usage.output_tokens
            text = "".join(b.text for b in resp.content if b.type == "text")
            ok = resp.stop_reason in ("end_turn", "stop_sequence")
            return text, ("ok" if ok else f"stop_reason={resp.stop_reason}")
        # OpenAI-compatible via OpenRouter
        if self.openrouter_client is None:
            import os
            import openai
            key = os.environ.get("OPENROUTER_API_KEY")
            if not key:
                raise RuntimeError("OPENROUTER_API_KEY not set")
            # A hung request otherwise sits for the client's 10-minute default
            # times its retries, times call()'s own attempts: over an hour per
            # record, with the workers all blocked on the same model.
            self.openrouter_client = openai.OpenAI(
                base_url="https://openrouter.ai/api/v1", api_key=key,
                timeout=420.0, max_retries=0)
        kwargs = {}
        if model not in getattr(self, "_no_json_mode", set()):
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = self.openrouter_client.chat.completions.create(
                model=model, max_tokens=max_tokens,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": payload}],
                **kwargs,
            )
        except Exception:
            if not kwargs:
                raise
            # model rejects response_format: remember and retry without
            self._no_json_mode = getattr(self, "_no_json_mode", set()) | {model}
            resp = self.openrouter_client.chat.completions.create(
                model=model, max_tokens=max_tokens,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": payload}],
            )
        if resp.usage:
            with self.lock:
                self.usage[model][0] += resp.usage.prompt_tokens or 0
                self.usage[model][1] += resp.usage.completion_tokens or 0
        choice = resp.choices[0]
        ok = choice.finish_reason in ("stop", None)
        return (choice.message.content or "",
                "ok" if ok else f"finish_reason={choice.finish_reason}")

    def call(self, model: str, system: str, chunk: list[dict],
             max_tokens: int = 16000) -> dict:
        payload = json.dumps(chunk, ensure_ascii=False)
        last_err = None
        for attempt in range(3):
            text, status = self._call_once(model, system, payload, max_tokens)
            if status != "ok":
                last_err = status
                # An output-cap overrun is deterministic for the same prompt
                # and cap; retrying it only burns the cap again. Fail fast.
                if "length" in status or "max_tokens" in status:
                    break
                continue
            try:
                return normalize_preds(parse_json_object(text), chunk)
            except (ValueError, json.JSONDecodeError) as e:
                last_err = f"parse: {e}"
        raise RuntimeError(f"{model}: chunk failed after retries ({last_err})")


def normalize_preds(obj: dict, chunk: list[dict]) -> dict:
    """Coerce a response to {record id: judgment}. Some models answer a
    one-record request with the judgment itself, flat, with or without an
    `id` field; merging that verbatim stores it under the wrong keys."""
    if "classes" in obj and not any(isinstance(v, dict) for v in obj.values()):
        rid = obj.pop("id", None) or (chunk[0]["id"] if len(chunk) == 1 else None)
        if rid is None:
            raise ValueError("flat judgment without a record id")
        return {rid: obj}
    ids = {r["id"] for r in chunk}
    return {k: v for k, v in obj.items() if k in ids or isinstance(v, dict)}


def is_semantic(classes: list[str]) -> bool:
    s = set(classes or [])
    return bool(s) and s != {"non-semantic"}


def kappa(tp: int, fp: int, fn: int, tn: int) -> float:
    n = tp + fp + fn + tn
    if n == 0:
        return 0.0
    po = (tp + tn) / n
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / n / n
    return (po - pe) / (1 - pe) if pe < 1 else 0.0


def score(records: list[dict], preds: dict[str, dict]) -> dict:
    tp = fp = fn = tn = 0
    cls_agree = 0
    per_class = Counter()
    per_class_hit = Counter()
    missing = 0
    for r in records:
        gold = r["label"]
        p = preds.get(r["id"])
        if p is None:
            missing += 1
            continue
        g_sem, p_sem = is_semantic(gold["classes"]), is_semantic(p.get("classes"))
        tp += g_sem and p_sem
        fp += (not g_sem) and p_sem
        fn += g_sem and not p_sem
        tn += (not g_sem) and not p_sem
        if set(gold["classes"]) == set(p.get("classes") or []):
            cls_agree += 1
        if g_sem:
            for c in gold["classes"]:
                if c == "non-semantic":
                    continue
                per_class[c] += 1
                if c in (p.get("classes") or []):
                    per_class_hit[c] += 1
    n = len(records) - missing
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {
        "n": n, "missing": missing, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": prec, "recall": rec, "f1": f1,
        "kappa": kappa(tp, fp, fn, tn),
        "class_set_agreement": cls_agree / n if n else 0.0,
        "per_class_recall": {c: (per_class_hit[c], per_class[c])
                             for c in sorted(per_class)},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--conditions", default="assisted,detection")
    ap.add_argument("--chunk-size", type=int, default=12)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="first N records only (smoke test)")
    ap.add_argument("--triaged", default="data/negatives_triaged.jsonl")
    ap.add_argument("--dataset", default=None,
                    help="override the record file (e.g. the synthetic "
                         "negatives); defaults to --triaged")
    ap.add_argument("--context", default="data/negatives_context.jsonl",
                    help="auxiliary file-context records, from build_context.py")
    ap.add_argument("--run", type=int, default=0,
                    help="run number for repeated sampling; N>=1 writes "
                         "{model}_{cond}_run{N}.json so runs do not collide")
    ap.add_argument("--outdir", default="model_labels")
    ap.add_argument("--report", default=None,
                    help="markdown report path; defaults to "
                         "docs/model_comparison[-<conds>][-run<N>].md")
    ap.add_argument("--patch-chunk", type=int, default=6,
                    help="chunk size for --patch-missing (models that drop "
                         "records from long JSON answers need 1-2)")
    ap.add_argument("--patch-missing", action="store_true",
                    help="rerun only records missing from saved prediction files "
                         "(smaller chunks, 32k output cap), then re-score")
    ap.add_argument("--only-ids", default=None,
                    help="with --patch-missing: restrict to record ids listed one "
                         "per line in this file")
    ap.add_argument("--redo", action="store_true",
                    help="with --only-ids: delete the listed ids from the "
                         "prediction files first, so they are re-queried even if "
                         "present (e.g. after a relabel changed embedded hints)")
    args = ap.parse_args()

    models = args.models.split(",")
    conditions = args.conditions.split(",")
    unknown = [c for c in conditions if c not in CONDITIONS]
    if unknown:
        print(f"unknown condition(s): {', '.join(unknown)}; "
              f"known: {', '.join(CONDITIONS)}", file=sys.stderr)
        return 2

    records = [json.loads(l) for l in open(REPO / (args.dataset or args.triaged))
               if json.loads(l).get("bucket") != "duplicate"]
    if args.limit:
        records = records[:args.limit]

    aux: dict[str, dict] = {}
    if any(c in NEEDS_CONTEXT for c in conditions):
        cpath = REPO / args.context
        if not cpath.exists():
            print(f"{cpath} missing; run scripts/build_context.py first",
                  file=sys.stderr)
            return 2
        aux = {json.loads(l)["id"]: json.loads(l) for l in open(cpath)}
        have = sum(1 for r in records if (aux.get(r["id"]) or {}).get("context"))
        print(f"context: {have}/{len(records)} records have file context",
              file=sys.stderr)

    suffix = f"_run{args.run}" if args.run else ""

    def stem(model: str, cond: str) -> str:
        return f"{model.replace('/', '_')}_{cond}{suffix}"

    outdir = REPO / args.outdir
    outdir.mkdir(parents=True, exist_ok=True)

    runner = Runner()

    if args.patch_missing:
        for model in models:
            for cond in conditions:
                f = outdir / f"{stem(model, cond)}.json"
                if not f.exists():
                    print(f"skip {model}/{cond}: no prediction file", file=sys.stderr)
                    continue
                preds = json.loads(f.read_text())
                only = None
                if args.only_ids:
                    only = {l.strip() for l in open(REPO / args.only_ids) if l.strip()}
                    if args.redo:
                        for i in only:
                            preds.pop(i, None)
                missing = [r for r in records if r["id"] not in preds
                           and (only is None or r["id"] in only)]
                if not missing:
                    print(f"{model}/{cond}: complete", file=sys.stderr)
                    continue
                system = CONDITIONS[cond][0]
                chunks = build_chunks(missing, cond, args.patch_chunk, aux)
                with ThreadPoolExecutor(max_workers=args.workers) as ex:
                    futs = [ex.submit(runner.call, model, system, ch,
                                      32000) for ch in chunks]
                    for fut in as_completed(futs):
                        try:
                            preds.update(fut.result())
                        except Exception as e:
                            print(f"{model}/{cond}: patch chunk failed: {e}",
                                  file=sys.stderr)
                f.write_text(json.dumps(preds, ensure_ascii=False, indent=1))
                s = score(records, preds)
                (outdir / f"{stem(model, cond)}_score.json"
                 ).write_text(json.dumps(s, indent=1))
                print(f"{model}/{cond}: patched {len(missing)} -> n={s['n']}, "
                      f"F1={s['f1']:.2f}, kappa={s['kappa']:.3f}", file=sys.stderr)
        return 0

    # Resume: predictions already on disk for a (model, condition) are loaded
    # and their chunks skipped, so a killed run costs nothing to restart.
    results: dict[tuple[str, str], dict] = defaultdict(dict)
    tasks = []
    skipped = 0
    for model in models:
        for cond in conditions:
            f = outdir / f"{stem(model, cond)}.json"
            if f.exists():
                results[(model, cond)] = json.loads(f.read_text())
            system = CONDITIONS[cond][0]
            for ci, chunk in enumerate(build_chunks(records, cond,
                                                    args.chunk_size, aux)):
                if all(r["id"] in results[(model, cond)] for r in chunk):
                    skipped += 1
                    continue
                tasks.append((model, cond, ci, system, chunk))
    if skipped:
        print(f"resume: {skipped} chunks already on disk, {len(tasks)} to run",
              file=sys.stderr)

    errors = []
    done = 0
    expected = Counter((m, c) for m, c, _, _, _ in tasks)
    finished: Counter = Counter()
    write_lock = threading.Lock()

    def save(m: str, c: str) -> None:
        with write_lock:
            (outdir / f"{stem(m, c)}.json").write_text(
                json.dumps(results.get((m, c), {}), ensure_ascii=False, indent=1))

    def checkpoint(m: str, c: str) -> None:
        """Score as soon as a (model, condition) pair completes."""
        save(m, c)
        s = score(records, results.get((m, c), {}))
        (outdir / f"{stem(m, c)}_score.json").write_text(json.dumps(s, indent=1))
        print(f"{m}/{c}: done, n={s['n']}, F1={s['f1']:.2f}", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(runner.call, m, s, ch): (m, c, ci)
                for m, c, ci, s, ch in tasks}
        for fut in as_completed(futs):
            m, c, ci = futs[fut]
            done += 1
            try:
                results[(m, c)].update(fut.result())
                save(m, c)  # every chunk hits disk the moment it lands
            except Exception as e:
                errors.append(f"{m}/{c}/chunk{ci}: {e}")
            finished[(m, c)] += 1
            if finished[(m, c)] == expected[(m, c)]:
                checkpoint(m, c)
            if done % 20 == 0:
                print(f"{done}/{len(tasks)} chunks", file=sys.stderr)

    lines = ["# Multi-model labeling comparison", "",
             f"Gold: human labels on {len(records)} records "
             f"({sum(1 for r in records if is_semantic(r['label']['classes']))} semantic). "
             f"Conditions: {', '.join(conditions)}. "
             f"Dataset: {args.dataset or args.triaged}"
             + (f", run {args.run}" if args.run else "") + ". "
             "Prompt: docs/labeling_prompt.md.", "",
             "| model | condition | n | prec | recall | F1 | kappa | class-set agree |",
             "|---|---|---|---|---|---|---|---|"]
    for model in models:
        for cond in conditions:
            # Merge with disk: a patch pass may have filled records for a
            # model that finished earlier in this same run.
            f = outdir / f"{stem(model, cond)}.json"
            preds = json.loads(f.read_text()) if f.exists() else {}
            preds.update(results.get((model, cond), {}))
            f.write_text(json.dumps(preds, ensure_ascii=False, indent=1))
            s = score(records, preds)
            lines.append(
                f"| {model} | {cond} | {s['n']} | {s['precision']:.2f} "
                f"| {s['recall']:.2f} | {s['f1']:.2f} | {s['kappa']:.3f} "
                f"| {s['class_set_agreement']:.2f} |")
            (outdir / f"{stem(model, cond)}_score.json").write_text(
                json.dumps(s, indent=1))
    det_cond = next((c for c in conditions if c.startswith("detection")),
                    conditions[0])
    lines += ["", f"## Per-class recall (gold semantic records, {det_cond})", ""]
    header = ["class"] + models
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    all_classes = sorted({c for r in records if is_semantic(r["label"]["classes"])
                          for c in r["label"]["classes"] if c != "non-semantic"})
    scores_det = {m: score(records, results.get((m, det_cond), {})) for m in models}
    for c in all_classes:
        row = [c]
        for m in models:
            hit, tot = scores_det[m]["per_class_recall"].get(c, (0, 0))
            row.append(f"{hit}/{tot}")
        lines.append("| " + " | ".join(row) + " |")
    cost_lines = ["", "## Token usage / cost", "",
                  "| model | input tok | output tok | est. cost |", "|---|---|---|---|"]
    for m, (ti, to) in runner.usage.items():
        pi, po = PRICES.get(m, (0, 0))
        cost_lines.append(f"| {m} | {ti:,} | {to:,} "
                          f"| ${ti / 1e6 * pi + to / 1e6 * po:.2f} |")
    lines += cost_lines
    if errors:
        lines += ["", "## Errors", ""] + [f"- {e}" for e in errors]
    report = args.report
    if report is None:
        tag = "" if set(conditions) == {"assisted", "detection"} \
            else "-" + "+".join(conditions)
        report = f"docs/model_comparison{tag}{suffix.replace('_', '-')}.md"
    (REPO / report).write_text("\n".join(lines) + "\n")
    print("\n".join(lines[4:6 + len(models) * len(conditions)]), file=sys.stderr)
    if errors:
        print(f"{len(errors)} chunk errors", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
