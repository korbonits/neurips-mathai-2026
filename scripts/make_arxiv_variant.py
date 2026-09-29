#!/usr/bin/env python3
"""Derive the preprint from the deanonymized workshop final source."""
from pathlib import Path
p = Path(__file__).resolve().parents[1] / 'paper'
text = (p / 'main.tex').read_text()
anchor = r'\usepackage[dblblindworkshop, final]{neurips_2026}'
if text.count(anchor) != 1:
    raise SystemExit('Expected exactly one workshop final style declaration')
(p / 'main-arxiv.tex').write_text(text.replace(anchor, r'\usepackage[preprint]{neurips_2026}'))
