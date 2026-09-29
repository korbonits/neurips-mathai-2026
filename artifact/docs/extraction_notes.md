> **Path note.** These notes were written against the working layout inside a
> formal-conjectures checkout. In this artifact: `data/pairs/*.jsonl` → `data/`,
> `data/pairs/*.md` → `docs/`, `data/pairs/model_labels/` → `model_labels/`.
> `first_push_map.json`, `pr_review_comments.json`, `adjudication.jsonl`, and
> `model_labels_stability/` are raw working files (GitHub usernames, scratch
> runs) and are not distributed.

# Corpus extraction notes

Decisions and ambiguities for `scripts/extract_pairs.py` and
`scripts/mine_review_diffs.py`. These notes record the extraction procedure used to construct the corpus.

## Task 1: `extract_pairs.py`

### Discovery findings

- Declaration keywords actually used under `FormalConjectures/`: `theorem`,
  `def`, `lemma`, `example`, `abbrev`, `structure`, `instance`, `inductive`.
  No project-specific *declaration* keywords exist. Apparent `conjecture` /
  `problem` keywords were docstring prose, not syntax.
- The project-specific syntax is the term-level `answer(...)` elaborator
  (`FormalConjecturesUtil/Answer/Syntax.lean`). It appears *inside* statements
  (`answer(True) ↔ ...`, `answer(sorry)`) and is left verbatim.
- Attributes: a single combined list per declaration,
  `@[category <test|research open|research solved|API|textbook>, AMS <nums>[,
  formal_proof using <formal_conjectures|lean4|other_system> at "<url>"]]`.
  183 files contain attribute lists spanning multiple lines. A handful of
  declarations use plain Lean attributes (`@[reducible]`, `@[simp]`, ...);
  these are captured in `attributes` too.

### Scope

- Only `FormalConjectures/**/*.lean` is walked. `FormalConjecturesUtil/`,
  `FormalConjecturesForMathlib/`, and `FormalConjecturesTest/` are library
  infrastructure, not (informal, formal) statement pairs.
- Docstringed `notation`/`macro`/`syntax` commands are *not* declarations and
  are excluded (e.g. `Wikipedia/SteinerSystem.lean`'s `S(t, k, n)` notation).

### Parsing decisions

- **Proof stripping applies to `theorem`/`lemma`/`example` only.** For `def`,
  `abbrev`, `instance`, `structure`, `inductive` the body *is* the semantic
  content described by the docstring, so `formal` keeps the full text
  verbatim. Sorrying a def's body would destroy the pair.
- **Statement/proof boundary** = first `:=` at bracket depth 0 (brackets
  `()[]{}⟨⟩⦃⦄`, strings and comments skipped). If a depth-0 `let`/`have`/
  `suffices` occurs *before* that `:=` (the statement binds values, e.g.
  `ErdosProblems/779.lean`), the boundary falls back to the first depth-0
  `:= by` / `:= sorry`. If neither rule applies, the record gets
  `formal: null` + `parse_error`. After the fallback was added the current
  tree has **0** parse errors. Known residual risk: a statement whose `let`
  binds a `by`-term would fool the fallback; none observed.
- **`open ... in` lines** (e.g. `open scoped Classical in`) precede the
  docstring in this codebase and are part of the declaration command in
  Lean's grammar. They are *included* at the top of `formal` (the spec said
  "from the first attribute or keyword", but without them the statement can
  fail to elaborate).
- **Anonymous declarations** (`example`, unnamed `instance`; 110 records)
  get `decl_name: null` and a synthetic id suffix `<kind>@L<line>`
  (1-indexed line of the keyword).
- **Modifiers on their own line** (`noncomputable\ndef ...`) and **column-0
  continuation lines** (`Wikipedia/EulerBrick.lean` has an unindented
  statement line) are handled; the item splitter only breaks at column-0
  lines that begin with a plausible command token.
- Line comments between docstring and declaration are skipped (they occur,
  e.g. `OEIS/100434.lean`).
- `provenance.line_start` = first line of the unit (the `open ... in` line if
  present, else the docstring); `line_end` = last line of the declaration.
  1-indexed, inclusive.
- `informal` is the docstring body with only the `/--` and `-/` delimiters
  removed — leading/trailing newlines and all internal whitespace preserved,
  no normalization.
- `references` = URLs (`https?://...`) plus citation tags of the shape
  `[Ab12]`/`[La10]` found in the docstring, in order of first appearance.
  The summary tables squash whitespace for display only; the JSONL is
  verbatim.

### Typecheck gate

The spec said to compile each sampled `formal` with only its `imports`. That
cannot work here: statements reference sibling declarations from the same
file (defs, `variable` binders, `namespace`/`open` context) — e.g.
`erdos_351` references `HasCompleteImage` defined 20 lines above. So the
gate writes: *the file's own text up to the sampled unit* + the extracted
`formal` + auto-generated `end` closers, and compiles that with
`lake env lean`. This still validates what the gate is for (the parser found
the right statement boundary and produced syntactically/semantically intact
text); it does not validate context-free compilability, which no extraction
scheme could achieve for this corpus.

## Task 2: `mine_review_diffs.py`

- `git log --merges` on `main` returns **0 commits**: the repo squash-merges
  every PR (all 502 first-parent commits are single-parent, titled
  `... (#NNNN)`). The merge's "second parent chain" does not exist locally.
- **Fallback used** (still git-only, no GitHub API): GitHub serves each PR's
  branch head as `refs/pull/N/head` over the plain git protocol
  (`git ls-remote origin 'refs/pull/*/head'` lists 3,380 of them). The script
  fetches those refs for the merged PRs, computes the merge-base of the PR
  head with the squash commit's parent, and takes the earliest branch commit
  after the base as the PR's first pushed commit.
- **Limitation**: if the author force-pushed during review, the original
  first push is gone from git; the PR contributes its *rewritten* earliest
  commit, which may already incorporate review fixes (undercounts
  candidates, never fabricates them). Recovering true first pushes for
  force-pushed PRs needs the GitHub API (`head_ref_forced_pushed` timeline
  events + fetching the `before` SHAs).
- Declarations are matched by name; comparison is restricted to files the
  squash commit itself touched (the squash tree also contains every other PR
  merged in between, which must not be attributed to this PR).
- "Statement differs" is judged on whitespace-normalized statement text
  (docstring, attributes, and proof excluded; for `def`-like declarations
  the whole body counts as the statement). `formal_before`/`formal_after`
  in the JSONL are raw, un-normalized. `edit_distance` is Levenshtein on
  the normalized text (capped at 4,000 chars).
- Records include `pr` and `provenance.pr_head`/`merge_base` beyond the
  spec'd fields, since they're needed to audit a candidate.
- **Id format deviates from the spec**: `fcpr:<sha>:<path>:<decl_name>`
  (path-qualified). The spec'd `fcpr:<sha>:<decl_name>` collides when one PR
  touches several files declaring the same name (13 ids / 52 records in
  practice — OEIS files all naming their sequence `a`, `conjecture`, …).
- Parser fixes found during labeling (affect both tasks; 35 positive records
  corrected, counts unchanged, typecheck still 20/20): `omit`/`include ... in`
  are now recognized as declaration prefixes rather than glued continuations,
  and the statement/proof-boundary guard now catches `letI`/`haveI` (the
  bare-`let` regex missed them, truncating one statement mid-`letI`).
- `make pairs` re-fetches the PR refs (into `refs/remotes/prmine/*`);
  `--no-fetch` reuses previously fetched refs.

## Enrichment, triage, pre-fill (post-mining pipeline)

- `scripts/enrich_github.py force-pushes` (needs `gh` auth): GraphQL
  `HeadRefForcePushedEvent.beforeCommit` per merged PR, then fetches the
  dangling SHAs over git (GitHub serves them) and computes the true first
  push. Result on 2026-08-31: 124/502 PRs were force-pushed; GitHub had
  GC'd the pre-push commit for 101 of them; **18 first pushes recovered**
  (`data/pairs/first_push_map.json`). The remaining 101 are unrecoverable
  even via the API. The other 5 (124 = 101 + 18 + 5) had a surviving
  pre-force-push head that contributed no commits beyond the merge-base
  (the script's `rev-list base..oid` was empty), so there was no earlier
  first push to recover; they fall back to branch history. Re-run
  2026-09-17 reproduces 124/101/0 unfetchable/18 exactly. Re-mining with the map: 347 → **374 candidates**
  (88 PRs). Candidates carry `provenance.first_push_source`
  (`branch_history` | `force_push_recovery`).
- `scripts/enrich_github.py comments`: inline review comments + review
  summaries for candidate PRs → `data/pairs/pr_review_comments.json`
  (528 inline comments across 88 PRs). Attached to triaged records where
  the comment's `path` matches the candidate's file (line-level matching
  is unreliable across force-pushes, so it's file-level; expect some
  unrelated comments in the list).
- `scripts/triage_negatives.py` → `data/pairs/negatives_triaged.jsonl`:
  - `bucket: duplicate` — identical (informal, before, after) mined from a
    superseded/reopened PR; lowest PR number kept, `dup_of` points at it.
  - `bucket: refactor-rename` — machine-detected: applying the PR's own
    declaration renames to `formal_before` reproduces `formal_after`.
    Suggested, not dropped.
  - `bucket: semantic-suspect` — everything else.
  - `group` = `pr:path` — one review change often edits several sibling
    declarations; label the group once and propagate.
- **Pre-filled labels** (`label_suggested`: classes / direction /
  confidence / one-sentence rationale) were produced by Claude (Fable 5)
  against `data/pairs/taxonomy.md`, judging `formal_before` vs the
  docstring with `formal_after` + reviewer comments as the answer key.
  This step is model work, not reproducible via `make`; rerunning it is a
  conversation with Claude, not a script. `label` remains `null` until a
  human confirms — copy `label_suggested` in or overwrite it.
- Pre-fill results (2026-08-31, 360 records): classes non-semantic 258,
  wrong-answer-marker 27, definitional-mismatch 23, wrong-type-or-domain 22,
  junk-value-trap 20, missing-hypothesis 18, extraneous-hypothesis 10,
  wrong-quantifier 8, other 8, wrong-referent 5, vacuous-or-trivial 3,
  wrong-connective 2, wrong-constant-or-bound 2 (multi-label). Direction:
  equivalent 260, incomparable 33, unclear 27, before-stronger 26,
  before-weaker 14. Confidence: high 230, medium 98, low 32. The model
  agreed with all 33 `refactor-rename` bucket calls. The ~100 records whose
  suggested classes are not just `non-semantic` are the real negative set;
  much of the non-semantic bulk is API-migration churn (a `WeierstrassCurve`
  → `Affine` cascade, `open scoped Classical` insertions, `answer(True) ↔`
  convention rewrites) — consider dropping them from the paper's corpus
  after review rather than labeling them all.
