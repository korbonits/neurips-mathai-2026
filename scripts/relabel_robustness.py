#!/usr/bin/env python3
"""Reproduce label-version sensitivity from an unpacked supplement; no API calls.

python relabel_robustness.py --artifact ../artifact --baseline workshop-labels.json
"""
import argparse
import ast
from collections import Counter
import json
from pathlib import Path


def compare(artifact: Path, baseline: list[dict]) -> list[dict]:
    tree = ast.parse((artifact / 'scripts/multi_model_compare.py').read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'is_semantic','kappa','score'}]
    scope = {'Counter': Counter}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'artifact-scorer','exec'),scope)
    score = scope['score']
    final = [r for line in (artifact/'data/negatives_triaged.jsonl').read_text().splitlines()
             if (r := json.loads(line)).get('bucket') != 'duplicate']
    assert {r['id'] for r in baseline} == {r['id'] for r in final}
    assert sum(scope['is_semantic'](r['label']['classes']) for r in baseline) == 105
    rows = []
    for path in sorted((artifact/'model_labels').glob('*_assisted.json')):
        model = path.name.removesuffix('_assisted.json')
        pa, pd = json.loads(path.read_text()), json.loads(path.with_name(model+'_detection.json').read_text())
        common = set(pa) & set(pd)
        if not common:
            continue
        row = {'model': model, 'n': sum(r['id'] in common for r in final)}
        for label, records in [('workshop',baseline),('final',final)]:
            shared = [r for r in records if r['id'] in common]
            a, d = score(shared,pa), score(shared,pd)
            row[label] = {'assisted_f1': a['f1'], 'detection_f1': d['f1'], 'delta_f1': a['f1']-d['f1']}
        rows.append(row)
    return rows


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--artifact', required=True, type=Path)
    ap.add_argument('--baseline', required=True, type=Path)
    args=ap.parse_args()
    print(json.dumps(compare(args.artifact,json.loads(args.baseline.read_text())),indent=2))
