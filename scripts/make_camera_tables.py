#!/usr/bin/env python3
"""Compact workshop comparison derived from pinned synthetic/natural scores."""
import json
from make_paper_tables import ARTIFACT, DISPLAY, ORDER, OUT, signed_delta

complete, partial = [], []
for model in ORDER:
    def get(condition):
        p = ARTIFACT / 'model_labels' / f'{model}_{condition}_score.json'
        return json.loads(p.read_text()) if p.exists() else {}
    s, n = get('detection-synthetic'), get('detection-matched')
    if not s.get('n'):
        continue
    is_partial = s['n'] != 359 or n['n'] != 339
    mark = r'$^{\dagger}$' if is_partial else ''
    row = f"{DISPLAY[model]}{mark} & {n['n']} & {n['f1']:.2f} & {s['n']} & {s['f1']:.2f} & {signed_delta(s['f1']-n['f1'])} " + r'\\'
    (partial if is_partial else complete).append(row)
text = r'''\begin{table}[t]\centering\small
\begin{tabular}{lrrrrr}
\toprule
 & \multicolumn{2}{c}{Natural, supported classes} & \multicolumn{2}{c}{Rule-written} & \\
\cmidrule(lr){2-3}\cmidrule(lr){4-5}
Model & $n$ & $F_1$ & $n$ & $F_1$ & $\Delta F_1$ \\
\midrule
''' + '\n'.join(complete) + r'''
\midrule
\multicolumn{6}{l}{\emph{Incomplete coverage: descriptive scores only}} \\
''' + '\n'.join(partial) + r'''
\bottomrule
\end{tabular}
\caption{Detection on natural errors of rule-supported classes and rule-written
synthetic errors. Complete populations contain 339 and 359 records.
$\dagger$ marks incomplete coverage; GLM answered only 37 synthetic records.
Main-text ranges use complete rows. Qwen and Muse are omitted because neither
produced a scoreable synthetic response.}
\label{tab:synthetic}
\end{table}
'''
OUT.mkdir(exist_ok=True, parents=True)
(OUT / 'camera_synthetic.tex').write_text(text)
