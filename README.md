# The Errors Reviewers Catch

**Statement-Level Autoformalization Errors and What Frontier Models Miss**

Alexander Korbonits, Independent Researcher

MATH-AI 2026 workshop at NeurIPS, accepted poster

This repository contains the camera-ready paper and the data, predictions,
prompts, and code supporting its reported experiments.

- [Camera-ready PDF](output/pdf/mathai-camera-ready.pdf) (5 main pages; 9 total).
- [Self-contained supplementary ZIP](output/supplementary-camera-ready.zip).
- [Manuscript source](paper/main.tex).
- [Artifact methods and labeling notes](artifact/docs/methods_notes.md).
- [Per-model score summary](supplementary/model_comparison.md).
- [Label-version sensitivity report](analysis/relabel-robustness.json).

The final reference contains **74 semantic errors among 360 candidates**.
Twelve models were attempted; eleven produced scoreable natural outputs.
The highest assisted F1 is 0.79 and the highest detection F1 is 0.56.
With fixed predictions and each model's shared answered records, assisted F1
exceeds detection F1 for all eleven models under both reference versions:
0.18-0.44 under the submitted labels and 0.11-0.35 under the final labels.
The labels come from one annotator; the paper discusses the resulting limits.

## Reproduce without model calls

From the repository root (or the extracted ZIP's `supplementary/` directory):

```sh
python3 scripts/verify_artifact.py
python3 scripts/relabel_robustness.py --artifact artifact --baseline analysis/workshop-labels.json
```

Python 3.10+ suffices for these checks. The first command verifies artifact
checksums, recomputes 104 saved score files from raw predictions, and writes
the label-version sensitivity report under `build/`.
No credentials, private repositories, or model calls are needed.

To rebuild the PDF and supplementary archive, install Tectonic and use Python
with matplotlib and pypdf, for example:

```sh
uv run --no-project --with matplotlib --with pypdf -- make release
```

The manuscript currently uses the Menlo font for Lean examples (available on
macOS); other systems need that font or an explicit source font substitution.
Tectonic may download its TeX bundle on first use. `make release` checks page
limits, metadata, citations, fonts, and overflow, then updates `output/`.
`make arxiv` creates an optional preprint variant; the workshop upload uses
`output/pdf/mathai-camera-ready.pdf`.

## Release scope and provenance

This is a standalone workshop release with fresh Git history. It contains the
natural assisted/detection comparisons, context and correction-only conditions,
rule-written synthetic experiment, oracle-hint and incorrect-hint conditions,
and the label-version sensitivity check used in this paper.

[`artifact-version.json`](artifact-version.json) records the source snapshot
identifier, preliminary-label fingerprint, and SHA-256 of every released
artifact file. Source commit identifiers are provenance only; reproduction
uses the included files and does not require those commits to be accessible.
Saved datasets and predictions are copied unchanged. The evaluation harness
retains the reported conditions and their original prompts and payload builders;
unreported condition variants are omitted. Table generation is limited to the
workshop manuscript. No new model calls were made for this release.

The 105-error submitted labels are preserved in `analysis/workshop-labels.json`.
The final 74-error labels supersede that reference. Historical generation notes
are explicitly identified and must not be read as current scores.

## Artifact contents

- `artifact/data/`: mined pairs, review-derived candidates, final labels, context,
  blind-label records, post-merge changes, and rule-written synthetic records.
- `artifact/model_labels/`: raw predictions and scores for the reported conditions.
- `artifact/scripts/`: extraction, mining, labeling, context, generation, and
  evaluation code. Run these from `artifact/`; extraction and typechecking also
  need a formal-conjectures checkout specified by `FC_TREE`.
- `artifact/docs/`: exact prompts for the included conditions, taxonomy,
  current methods, extraction notes, and historical synthetic construction notes.
- `analysis/`: preliminary labels and reproducible sensitivity results.
- `paper/`, `scripts/`: manuscript and local build/verification tools.

Repeating model calls requires provider credentials and can incur charges;
none are needed to rescore the included predictions. Raw mining caches with
GitHub usernames are not distributed. Review-comment authors in the released
corpus use `reviewer-N` aliases; public upstream attribution links are retained.

## Attribution and licensing

The artifact retains its [Apache-2.0 license](artifact/LICENSE). Statement and
docstring text derives from [formal-conjectures](https://github.com/google-deepmind/formal-conjectures),
Copyright The Formal Conjectures Authors. See [third-party notices](THIRD_PARTY_NOTICES.md).
The included workshop style retains its original notices. No additional blanket
license is assigned here to the manuscript or other material outside `artifact/`.

See [CITATION.cff](CITATION.cff) for citation metadata.
Repository: https://github.com/korbonits/neurips-mathai-2026
