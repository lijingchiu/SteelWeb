"""Wait until both exact newsletter files are reachable on the public site."""
from __future__ import annotations
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from notify import local_report_ready, report_paths


def public_files_match(base: str, expected: list[tuple[str, str]], getter=requests.get) -> bool:
    for path, digest in expected:
        response = getter(base + path, params={'verify': digest[:16]}, timeout=15)
        if not response.ok or hashlib.sha256(response.content).hexdigest() != digest:
            return False
    return True


def main() -> int:
    today = os.environ.get('RESEARCH_DATE') or datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
    state = json.loads(Path('data/notify-state.json').read_text(encoding='utf-8')) if Path('data/notify-state.json').exists() else {}
    if (state.get('email') or {}).get('date') == today:
        print('Email was already sent; no publication wait needed.')
        return 0
    report = json.loads(Path('data/report.json').read_text(encoding='utf-8'))
    if not local_report_ready(report, today):
        print('Today’s two report files are missing or do not match the manifest.')
        return 1
    cfg = json.loads(Path('notify-config.json').read_text(encoding='utf-8'))
    base = cfg.get('site_url', 'https://lijingchiu.github.io/SteelWeb/').rstrip('/') + '/'
    paths = report_paths(report, today)
    expected = [(path, hashlib.sha256(Path(path).read_bytes()).hexdigest()) for path in paths]
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            published = public_files_match(base, expected)
            if published:
                print('Both exact newsletter files are publicly reachable.')
                return 0
        except requests.RequestException as e:
            print(f'Waiting for site publication: {type(e).__name__}', flush=True)
        time.sleep(8)
    print('Timed out waiting for both newsletter files to become publicly available.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
