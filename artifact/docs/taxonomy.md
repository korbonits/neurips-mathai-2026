# Reference-label taxonomy

Applies to negative candidates: the *before* statement is judged against the
*informal* docstring (at merge). The reviewer-driven *after* statement is the
answer key, but the label describes what was wrong with *before*, not what the
diff did.

## `label.classes` (multi-label, pick all that apply)

| class | meaning | canonical example |
|---|---|---|
| `wrong-quantifier` | ∃/∀ swapped, wrong scope/order, quantifier over the wrong variable | `∃ B, ∀ S` vs `∀ B, ∃ c` (erdos_2, #4313) |
| `missing-hypothesis` | side condition in the informal statement absent from the formal one (positivity, nonemptiness, distinctness, `n ≥ 1`, …) | missing `0 < D` (#5023) |
| `extraneous-hypothesis` | formal statement assumes more than the informal one | — |
| `wrong-type-or-domain` | wrong carrier: ℕ vs ℤ vs ℚ vs ℝ, `Fin n` vs ℕ, wrong codomain, meaning-changing coercion | `def b : … : ℕ` vs `ℚ` (#5016) |
| `wrong-referent` | statement points at the wrong declaration/constant (name confusion) | sequence `a n` vs predicate `A n` (#4383) |
| `wrong-constant-or-bound` | off-by-one, wrong numeric constant/exponent, strict vs non-strict inequality | — |
| `wrong-connective` | ∧/∨/→/↔ misuse, misplaced negation | — |
| `wrong-answer-marker` | project-specific: `answer(True/False/sorry)` has wrong polarity or wraps the wrong proposition | — |
| `junk-value-trap` | statement diverges from informal via Lean junk values (`/ 0`, ℕ subtraction, `sInf ∅`, `tsum` junk, …) | ERH note in `Millenium/RiemannHypothesis.lean` |
| `definitional-mismatch` | an auxiliary def used by the statement doesn't capture the informal notion | — |
| `vacuous-or-trivial` | formal statement trivially true/false (empty range, wrong index set) contrary to informal intent | — |
| `non-semantic` | rename, namespace, style, whitespace; statement meaning unchanged (excluded from negatives) | `JacobianConjectureFor` → reuse of `JacobianConjectureProp` (#5213) |
| `informal-changed` | the docstring changed too between first push and merge; pair basis shifted — handle with care | — |
| `other` | anything else; explain in note | — |

## `label.direction` (single value; before relative to informal intent)

- `before-weaker` — before proves less than the informal claim
- `before-stronger` — before claims more
- `incomparable` — neither implies the other
- `equivalent` — semantically equal (only valid with `non-semantic`)
- `unclear` — needs discussion

## Historical pre-fill format

Machine-suggested labels live in `label_suggested`:
`{classes, direction, confidence: high|medium|low, rationale}` — one-sentence
rationale, written against this taxonomy. Confirm by copying into `label`,
or overwrite. `label` stays `null` until a human sets it.

## Final-reference convention

An omitted answer wrapper or swapping equivalent sides of an iff is non-semantic.
The final reference contains 74 semantic records with 93 assignments across 12
semantic classes. The informal-changed option is unoccupied; non-semantic denotes
controls. Historical model prompts are preserved rather than retroactively edited.
