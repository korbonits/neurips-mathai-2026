#!/usr/bin/env python3
"""Package only the standalone workshop release; never include development history."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from make_paper_tables import ARTIFACT, DISPLAY, ORDER
from verify_artifact import main as verify

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ['README.md', 'Makefile', '.gitignore', 'CITATION.cff',
              'THIRD_PARTY_NOTICES.md', 'artifact-version.json']
PAPER_FILES = ['main.tex', 'refs.bib', 'neurips_2026.sty', 'figures/collapse.pdf']
TABLES = ['negative_classes', 'model_comparison', 'class_recall', 'context_delta',
          'nocomments_delta', 'hint_compare', 'distractor', 'camera_synthetic']
SCRIPTS = ['make_camera_tables', 'make_paper_figure', 'relabel_robustness',
           'verify_pdf', 'make_arxiv_variant', 'make_paper_tables', 'verify_artifact',
           'make_camera_supplement', 'package_outputs']

def release_files():
    manifest = json.loads((ROOT / 'artifact-version.json').read_text())
    names = ROOT_FILES + ['artifact/' + p for p in manifest['files']]
    names += ['paper/' + p for p in PAPER_FILES]
    names += ['paper/tables/' + n + '.tex' for n in TABLES]
    names += ['scripts/' + n + '.py' for n in SCRIPTS]
    names += ['analysis/workshop-labels.json', 'analysis/relabel-robustness.json',
              'supplementary/README.md', 'supplementary/model_comparison.md']
    paths = [ROOT / n for n in names]
    assert all(p.is_file() for p in paths), 'Missing required release file'
    return sorted(paths)

def main():
    verify()
    out = ROOT / 'supplementary'
    out.mkdir(exist_ok=True)
    rows = ['# Camera-ready score summary', '',
            'Reference: 74 semantic / 286 non-semantic records; the rule-written synthetic arm contains 104 errors / 255 controls.', '',
            '| Model | Condition | n | P | R | F1 | kappa |',
            '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for model in ORDER:
        for condition in ['assisted','detection','detection-context','assisted-nocomments','detection-synthetic']:
            path = ARTIFACT / 'model_labels' / f'{model}_{condition}_score.json'
            if not path.exists():
                continue
            s = json.loads(path.read_text())
            metrics = f"{s['precision']:.4f} | {s['recall']:.4f} | {s['f1']:.4f} | {s['kappa']:.4f}" if s.get('n') else '-- | -- | -- | --'
            rows.append(f"| {DISPLAY[model]} | {condition} | {s['n']} | {metrics} |")
    (out / 'model_comparison.md').write_text('\n'.join(rows) + '\n')
    (out / 'README.md').write_text('''# Supplementary material

The ZIP contains the standalone workshop repository under `supplementary/`.
Extract it and follow that directory's root README to verify all saved scores,
reproduce the label-version sensitivity analysis, or build the paper. The final
PDF is distributed separately in `output/pdf/mathai-camera-ready.pdf`.
`SHA256SUMS` at the ZIP root covers every archived file. No model calls or access
to private repositories are needed for verification.
''')
    shutil.copyfile(ROOT / 'build/relabel-robustness.json', ROOT / 'analysis/relabel-robustness.json')
    data = {'supplementary/' + str(p.relative_to(ROOT)): p.read_bytes() for p in release_files()}
    data['SHA256SUMS'] = ''.join(f'{hashlib.sha256(b).hexdigest()}  {name}\n' for name,b in sorted(data.items())).encode()
    dest = ROOT / 'output/supplementary-camera-ready.zip'
    dest.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name,b in sorted(data.items()):
            info = zipfile.ZipInfo(name, date_time=(2026,9,28,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info,b)
    with zipfile.ZipFile(dest) as archive:
        assert archive.testzip() is None
        assert all(archive.read(n) == b for n,b in data.items())
    print(f'Created {dest.name}: {len(data)} files; archive contents verified')

if __name__ == '__main__':
    main()
