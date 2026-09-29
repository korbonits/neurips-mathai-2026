#!/usr/bin/env python3
"""Copy the checked PDF to the stable release location and hash deliverables."""
import hashlib
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
(root / 'output/pdf').mkdir(parents=True, exist_ok=True)
shutil.copyfile(root / 'build/main.pdf', root / 'output/pdf/mathai-camera-ready.pdf')
shutil.copyfile(root / 'build/pdf-check.json', root / 'output/pdf-check.json')
files = ['pdf/mathai-camera-ready.pdf', 'supplementary-camera-ready.zip', 'pdf-check.json']
(root / 'output/SHA256SUMS').write_text(''.join(
    f"{hashlib.sha256((root / 'output' / p).read_bytes()).hexdigest()}  {p}\n" for p in files))
print('Release PDF, supplement, checks, and checksums ready in output/')
