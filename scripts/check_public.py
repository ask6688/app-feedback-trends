#!/usr/bin/env python3
"""Check the explicit publication allowlist and common private-data markers."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'outputs', 'inputs', 'output', '.venv', '__pycache__', '.git', '.playwright-cli'}
PRIVATE_FILES = {'classification.json', 'classification_cs.json', 'history.json', 'preview.json'}
MARKERS = re.compile(
    r'/Users/|/home/[^/\s]+/|WorkBuddy|迅雷|\bjira\b|'
    r'https?://[^\s"<>]*(?:\.internal\b|\.local\b|\.corp\b)|'
    r'\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b|'
    r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|'
    r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})\b|'
    r'\b(?:token|cookie|api_key|password)\s*[=:]\s*["\'][^"\']{8,}["\']', re.I)


def check():
    allowed = set((ROOT/'public-files.txt').read_text().splitlines())
    errors = []
    for name in allowed:
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or path.name in PRIVATE_FILES:
            errors.append('Invalid public file: ' + name)
    actual = set()
    for path in ROOT.rglob('*'):
        relative = path.relative_to(ROOT)
        if any(part in IGNORED for part in relative.parts) or path.name == '.DS_Store':
            continue
        if path.is_symlink():
            errors.append('Symlink is not allowed: ' + str(relative)); continue
        if path.is_file(): actual.add(relative.as_posix())
    if actual != allowed:
        errors.append('Allowlist mismatch: unexpected=%s missing=%s' % (sorted(actual-allowed), sorted(allowed-actual)))
    for name in allowed & actual:
        if name == 'docs/dashboard.png': continue
        text = (ROOT/name).read_text(encoding='utf-8')
        # This checker names patterns it rejects; inspect other public content.
        if name != 'scripts/check_public.py' and MARKERS.search(text):
            errors.append('Private-data marker: ' + name)
    if (ROOT/'.git').exists():
        tracked = subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
        errors += ['Tracked file outside allowlist: ' + name for name in tracked if name and name not in allowed]
    if errors: raise SystemExit('\n'.join(errors))
    print('Public allowlist and marker scan passed: %d files' % len(allowed))


if __name__ == '__main__': check()
