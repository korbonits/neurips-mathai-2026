#!/usr/bin/env python3
"""Per-model assisted, detection, and rule-written synthetic F1 from pinned scores."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from make_paper_tables import ARTIFACT, DISPLAY, ORDER

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'paper/figures/collapse.pdf'
SYNTH_MIN = 340

def main():
    rows = []
    plotted = []
    for model in ORDER:
        scores = {}
        for cond in ['assisted', 'detection', 'detection-synthetic']:
            path = ARTIFACT / 'model_labels' / f'{model}_{cond}_score.json'
            scores[cond] = json.loads(path.read_text()) if path.exists() else {}
        a, d, s = (scores[c] for c in ['assisted','detection','detection-synthetic'])
        if not (a.get('n') and d.get('n')):
            continue
        label = DISPLAY[model] + (' †' if a['n'] < 360 or d['n'] < 360 else '')
        # Near-complete synthetic runs are shown hollow, matching the dagger
        # treatment of incomplete natural runs; GLM's 37/359 is too sparse to plot.
        shown = s.get('n', 0) >= SYNTH_MIN
        synth = (s['f1'], s['n'] == 359) if shown else None
        rows.append((model, label, a['f1'], d['f1'], synth))
        plotted.append({'model': model, 'assisted': a, 'detection': d,
                        'synthetic_shown': shown})
    rows.sort(key=lambda x: x[2], reverse=True)
    plt.rcParams.update({'font.family':'DejaVu Serif','font.size':9,'pdf.fonttype':42})
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    for y, (_, label, a, d, s) in enumerate(rows):
        ax.plot([d,a], [y,y], color='#b9b9b9', linewidth=1.1, zorder=1)
        ax.plot(a,y,'o',color='#0072B2',ms=5.5,zorder=3)
        ax.plot(d,y,'o',mfc='white',mec='#D55E00',mew=1.4,ms=5.5,zorder=3)
        if s is not None:
            f1, complete = s
            if complete:
                ax.plot(f1,y,'D',color='#009E73',ms=5,zorder=3)
            else:
                ax.plot(f1,y,'D',mfc='white',mec='#009E73',mew=1.3,ms=5,zorder=3)
    ax.set_yticks(range(len(rows)),[r[1] for r in rows],fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlim(0,1.035)
    ax.set_xticks([0,.2,.4,.6,.8,1])
    ax.set_xlabel('$F_1$ against reference labels',fontsize=9)
    ax.spines[['top','right','left']].set_visible(False)
    ax.tick_params(axis='y',length=0)
    ax.grid(axis='x',color='#e4e4e4',linewidth=.6)
    ax.set_axisbelow(True)
    handles=[Line2D([],[],marker='o',color='#0072B2',ls='',label='Assisted (natural)'),
             Line2D([],[],marker='o',mfc='white',mec='#D55E00',mew=1.4,ls='',label='Detection (natural)'),
             Line2D([],[],marker='D',color='#009E73',ls='',label='Detection (synthetic)')]
    ax.legend(handles=handles,loc='upper center',bbox_to_anchor=(.44,-.19),
              ncol=3,frameon=False,fontsize=8,handletextpad=.3,columnspacing=1)
    fig.tight_layout(pad=.45)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(OUT,metadata={'CreationDate':None,'ModDate':None})
    fig.savefig(OUT.with_suffix('.png'),dpi=180)
    plt.close(fig)
    (ROOT/'build').mkdir(exist_ok=True)
    (ROOT/'build/figure-data.json').write_text(json.dumps(plotted,indent=2)+'\n')
    print(f'Figure: {len(rows)} natural comparisons; {sum(r[4] is not None for r in rows)} complete synthetic runs')

if __name__=='__main__':
    main()
