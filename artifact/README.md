# Workshop research artifact

See the [repository README](../README.md) for results, scope, and reproduction.
The final reference is 74 semantic records out of 360 candidates; historical
105-error labels are in `../analysis/workshop-labels.json`.

Run the root `scripts/verify_artifact.py` to verify and rescore this directory.
The root manifest lists every artifact file and its SHA-256. Included datasets
and saved model outputs are unchanged from the recorded source snapshot.
The evaluation harness is restricted to the eight conditions reported in the
paper; the retained prompts, payload builders, and scoring functions are unchanged.

For extraction/mining/generation, run scripts from this directory with `FC_TREE`
pointing to the appropriate formal-conjectures checkout. See `docs/extraction_notes.md`
and `docs/methods_notes.md`. Reconstruction of inaccessible historical Git objects
or unavailable raw GitHub caches may be impossible; saved records are included
so verification does not depend on re-mining. Repeating the synthetic generator
with current labels is not expected to reconstruct a set originally generated
using the preliminary labels; use the frozen dataset for the reported comparison.
