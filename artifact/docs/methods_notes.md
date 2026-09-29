# Camera-ready methods and version summary

This release contains the workshop artifact subset, checked by the root
`artifact-version.json` manifest. The original 105-error labels are included in
`analysis/workshop-labels.json`; final candidates retain `label_assisted` and
`label_blind` fields. Final `label` is the scoring reference.

The September 20–21 full blind pass supersedes the model-assisted first pass:
45 old negatives became controls and 14 controls became negatives. One annotator
performed both passes; suggestions and old labels were hidden in the final pass,
with greater Lean experience and elaboration where needed. This is not independent
expert annotation or an identical-protocol test–retest study.

All natural conditions use 360 candidates, including eight controls without a
docstring. Assisted inputs include the corrected statement, up to six comments,
triage bucket, and rename metadata. Detection inputs are identifier, informal
statement, and formal_before. Context adds before-commit file-local definitions
and hazard guidance. See the exact payload builders and frozen prompts in
`artifact/scripts/multi_model_compare.py` and `artifact/docs/prompts.md`.

The original batching uses 12 records; missing-output and changed-hint patches
may use smaller batches or single records. Score n is the number of answered
records, not always the requested population. Missing outputs are omitted.
Scores measure label agreement, not rationale correctness.

The rule-written synthetic population has 104 perturbations and 255 controls.
The natural rule-supported subset has 53 errors and 286 controls. These match
class support, not frequency, prevalence, or difficulty. Use the score JSONs and regenerated summary for final results.
The historical synthetic-generation note records the earlier construction labels.
Only experiments reported in the workshop paper are included in this release.

No new model calls were made for this camera-ready preparation. The paper build
checks the artifact checksums and rescores 104 cited/derived score files from saved
predictions, including common-record hint comparisons. A separate label-version
sensitivity check fixes current predictions and uses each model's intersection
of answered assisted/detection records. All eleven retain a positive assisted
minus detection F1 under both references. Baseline labels were extracted from
workshop commit 478ffcc and are included with a SHA-256 recorded in the manifest.
The F1 gaps are 0.18-0.44 under the submitted labels and 0.11-0.35 under
the final labels. This is a sensitivity check, not annotation validation.
