#!/usr/bin/env python3
"""Check final PDF identity, content limit, citations, and build diagnostics."""
from pathlib import Path
import json
import re
from pypdf import PdfReader

root=Path(__file__).resolve().parents[1]
r=PdfReader(root/'build/main.pdf')
texts=[p.extract_text() or '' for p in r.pages]
reference_page=next(i for i,t in enumerate(texts) if t.lstrip().startswith('References'))
assert reference_page<=5, f'Main content exceeds five pages: {reference_page}'
assert r.metadata.author=='Alexander Korbonits'
assert 'Statement-Level Autoformalization Errors' in r.metadata.title
all_text='\n'.join(texts)
assert not any(x in all_text for x in ['Anonymous Author','withheld for','TODO','??','−0.00','0/0','four highlighted classes'])
assert '74 semantic errors' in all_text
log=(root/'build/main.log').read_text()
for pattern in ['Overfull', r'Citation .* undefined', r'Reference .* undefined', 'Missing character:', 'undefined references']:
    assert not re.search(pattern,log), pattern
for p in r.pages:
    assert tuple(float(x) for x in p.mediabox)==(0.,0.,612.,792.)
fonts=set()
for p in r.pages:
    for ref in p['/Resources'].get('/Font',{}).values():
        f=ref.get_object();fonts.add(str(f.get('/BaseFont')))
assert any('TeXGyreTermes' in f for f in fonts), fonts
report={'main_pages':reference_page,'references_start_page':reference_page+1,
        'total_pages':len(r.pages),'author':r.metadata.author,'title':r.metadata.title,
        'fonts':sorted(fonts),'checks':'Page limit, metadata, missing citations/glyphs, and overflow passed. Visual review recorded separately.'}
(root/'build/pdf-check.json').write_text(json.dumps(report,indent=2)+'\n')
print(f'PDF checks passed: {reference_page} main pages, {len(r.pages)} total; final author metadata and Times-compatible font verified')
