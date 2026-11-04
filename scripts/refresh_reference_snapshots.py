#!/usr/bin/env python3
"""Refresh bounded snapshots of known public government data; retain old copies on failure."""
import concurrent.futures
import datetime
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1] / 'data/laws/reference-archive'
SOURCES = ROOT / 'snapshot-sources.json'
OUTPUT = ROOT / 'source-snapshots.json'
HOSTS = {'opendata.tycg.gov.tw', 'data.taipei', 'www.nusc.gov.tw', 'data.kcg.gov.tw'}
MAX_BYTES = 250000


def fetch(item):
    path, url = item
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or parsed.password:
        return path, None
    try:
        with urlopen(Request(url, headers={'User-Agent': 'SteelWeb-Reference/1.0', 'Accept': 'text/csv,application/json,*/*'}), timeout=15) as response:
            final = urlparse(response.geturl())
            if final.scheme != 'https' or final.hostname not in HOSTS:
                return path, None
            raw = response.read(MAX_BYTES + 1)
        if not raw or len(raw) > MAX_BYTES:
            return path, None
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('big5')
        if '\0' in text or text.lstrip().startswith(('<', '{')):
            return path, None
        if not text.lstrip().startswith('[') and (',' not in text or '\n' not in text):
            return path, None
        if text.lstrip().startswith('[') and not isinstance(json.loads(text), list):
            return path, None
        return path, {'source': url, 'retrieved': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'text': text}
    except (ValueError, UnicodeError, OSError):
        return path, None


def main():
    sources = json.loads(SOURCES.read_text(encoding='utf-8'))
    previous = json.loads(OUTPUT.read_text(encoding='utf-8')) if OUTPUT.exists() else {}
    records = {p: v for p, v in previous.items() if p in sources and v.get('source') == sources[p]}
    success = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        for path, data in executor.map(fetch, sources.items()):
            if data:
                records[path] = data
                success += 1
    OUTPUT.write_text(json.dumps(records, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print(f'{success}/{len(sources)} sources refreshed; {len(records)} snapshots available')
    if not records:
        raise SystemExit('No source snapshots available')

if __name__ == '__main__':
    main()
