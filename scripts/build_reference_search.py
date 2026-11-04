#!/usr/bin/env python3
"""Build an offline, document-level bigram index for the reference archive."""
import json, re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'data/laws/reference-archive'
CATALOG = ARCHIVE / 'index.json'
OUTPUT = ARCHIVE / 'search-index.json'

def terms(text):
    text = text.lower()
    grams = set()
    for s in re.findall(r'[\u3400-\u9fff]+', text):
        grams.update(s[i:i+2] for i in range(len(s)-1))
    grams.update(re.findall(r'[a-z0-9]{2,}', text))
    return grams

def build():
    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    docs = []
    postings = defaultdict(list)
    for category in catalog['categories']:
        for doc in category['files']:
            p = ROOT / doc['path']
            if not p.is_file():
                raise FileNotFoundError(p)
            text = p.read_text(encoding='utf-8')
            identifier = len(docs)
            docs.append({'name': doc['name'], 'path': doc['path'], 'category': category['category'], 'bytes': p.stat().st_size})
            for term in terms(doc['name'] + '\n' + text):
                postings[term].append(identifier)
    result = {'version': 1, 'docs': docs, 'terms': dict(postings)}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'Indexed {len(docs)} documents, {len(postings)} terms, {OUTPUT.stat().st_size} bytes')

if __name__ == '__main__':
    build()
