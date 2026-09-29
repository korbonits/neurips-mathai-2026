# Labeling prompt (frozen 2026-08-31)

The exact task given to the model annotator (Claude Fable 5) for the
`label_suggested` pre-fill. Reuse verbatim for other models so comparisons are
apples-to-apples. Inputs: chunks of records cut from
`negatives_triaged.jsonl` with fields id, bucket, informal, formal_before,
formal_after, renames_applied, comments (inline review comment bodies, ≤6).

For the error-detection condition (vs. the diff-explanation condition run
here), remove `formal_after`, `comments`, `renames_applied`, and `bucket`
from the records (bucket leaks the rename heuristic) and drop the answer-key
sentence below.

The executable, provider-portable version of both conditions lives in
`scripts/multi_model_compare.py` (`SYSTEM_ASSISTED` / `SYSTEM_DETECTION`) —
that is the canonical prompt for cross-model runs; this file documents its
provenance.

---

For EACH record, judge the `formal_before` Lean statement against the
`informal` docstring (the informal statement of intent; `formal_after` is the
reviewer-approved answer key — what the statement was corrected to;
`comments` are reviewer comments from the PR, often explaining why). Use the
taxonomy in data/pairs/taxonomy.md: classes are wrong-quantifier,
missing-hypothesis, extraneous-hypothesis, wrong-type-or-domain,
wrong-referent, wrong-constant-or-bound, wrong-connective,
wrong-answer-marker, junk-value-trap, definitional-mismatch,
vacuous-or-trivial, non-semantic, informal-changed, other. Direction is one
of before-weaker, before-stronger, incomparable, equivalent, unclear
(equivalent only with non-semantic). Rules: multi-label allowed; if
`informal` is null, judge before vs after semantics and say "no docstring" in
the rationale; records with bucket "refactor-rename" are machine-suspected
non-semantic — confirm or overrule on your own judgment; confidence
high/medium/low; rationale exactly one sentence, mention the decisive
difference. Output a single JSON object mapping each record's id to
{"classes": [...], "direction": "...", "confidence": "...", "rationale": "..."}.
Every id in the chunk must appear, each labeled on its own record's content
(no majority-vote shortcuts).
