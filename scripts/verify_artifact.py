#!/usr/bin/env python3
"""Verify the released artifact checksums and rescore every reported condition; no API calls."""
import ast
import hashlib
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
from relabel_robustness import compare

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = Path(os.environ.get('FCREPO', ROOT / 'artifact')).resolve()

def main():
    pin = json.loads((ROOT / 'artifact-version.json').read_text())['source_artifact_commit']
    manifest = json.loads((ROOT / 'artifact-version.json').read_text())
    expected = manifest['files']
    present = {str(p.relative_to(ARTIFACT)) for p in ARTIFACT.rglob('*')
               if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    assert present == set(expected), f'Artifact file set changed: {present ^ set(expected)}'
    for name, digest in expected.items():
        assert hashlib.sha256((ARTIFACT / name).read_bytes()).hexdigest() == digest, name
    def records(name):
        return [r for line in (ARTIFACT / 'data' / name).read_text().splitlines()
                if (r := json.loads(line)).get('bucket') != 'duplicate']
    natural = records('negatives_triaged.jsonl')
    final = records('negatives_final.jsonl')
    assert len(natural) == 360 and len(final) == 74
    assert sum(len(r['label']['classes']) for r in final) == 93
    # Load only the pure scoring functions, avoiding the API client's imports.
    tree = ast.parse((ARTIFACT / 'scripts/multi_model_compare.py').read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'is_semantic', 'kappa', 'score'}]
    scope = {'Counter': Counter}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'artifact-scorer', 'exec'), scope)
    score, semantic = scope['score'], scope['is_semantic']
    assert {r['id'] for r in natural if semantic(r['label']['classes'])} == {r['id'] for r in final}
    synthetic = records('negatives_synthetic.jsonl')
    supported = {c for r in synthetic for c in r['label']['classes']} - {'non-semantic'}
    matched = [r for r in natural if not semantic(r['label']['classes']) or set(r['label']['classes']) <= supported]
    assert len(matched) == 339
    conditions = ['assisted', 'detection', 'detection-context', 'assisted-nocomments',
                  'detection-synthetic', 'detection-hint', 'detection-exists', 'detection-distractor']
    count = 0
    for cond in conditions:
        data = synthetic if cond == 'detection-synthetic' else natural
        for path in sorted((ARTIFACT / 'model_labels').glob(f'*_{cond}.json')):
            saved = json.loads(path.with_name(path.stem + '_score.json').read_text())
            actual = score(data, json.loads(path.read_text()))
            assert json.loads(json.dumps(actual)) == saved, f'Stale score: {path.name}'
            count += 1
    for path in sorted((ARTIFACT / 'model_labels').glob('*_detection-matched_score.json')):
        preds = json.loads(path.with_name(path.name.replace('_detection-matched_score', '_detection')).read_text())
        actual = score(matched, preds)
        saved = json.loads(path.read_text())
        assert all(json.loads(json.dumps(value)) == saved[key] for key, value in actual.items()), path.name
        count += 1
    for path in sorted((ARTIFACT / 'model_labels').glob('*_detection-common_score.json')):
        slug = path.name.removesuffix('_detection-common_score.json')
        arms = ['detection', 'detection-exists', 'detection-hint']
        predictions = {a: json.loads((path.parent / f'{slug}_{a}.json').read_text()) for a in arms}
        ids = set.intersection(*(set(p) for p in predictions.values()))
        shared = [r for r in natural if r['id'] in ids]
        for arm in arms:
            saved = json.loads((path.parent / f'{slug}_{arm}-common_score.json').read_text())
            actual = score(shared, predictions[arm])
            assert all(json.loads(json.dumps(value)) == saved[key] for key, value in actual.items()), f'{slug}/{arm}'
            count += 1
    baseline_path = ROOT / 'analysis/workshop-labels.json'
    manifest = json.loads((ROOT / 'artifact-version.json').read_text())
    assert hashlib.sha256(baseline_path.read_bytes()).hexdigest() == manifest['workshop_labels_sha256']
    baseline = json.loads(baseline_path.read_text())
    assert {r['id'] for r in baseline} == {r['id'] for r in natural}
    assert sum(semantic(r['label']['classes']) for r in baseline) == 105
    robustness = compare(ARTIFACT, baseline)
    assert all(r[version]['delta_f1'] > 0 for r in robustness for version in ['workshop','final'])
    assert len(robustness) == 11
    report = {'protocol': 'Fixed current predictions; within-model intersection of answered records; both reference versions.',
              'workshop_commit': manifest['workshop_baseline_commit'], 'source_artifact_commit': pin, 'repository': manifest['repository'],
              'models': robustness}
    (ROOT / 'build').mkdir(exist_ok=True)
    (ROOT / 'build/relabel-robustness.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Fixed-prediction robustness: assisted F1 exceeds detection F1 for all 11 models under both label versions')
    print(f'Workshop artifact checksums verified: 74/360 semantic records; {count} score files checked against predictions')

if __name__ == '__main__':
    main()
