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
    excluded = set(json.loads((ARCHIVE / 'excluded-from-search.json').read_text(encoding='utf-8')))
    live_sources = json.loads((ARCHIVE / 'live-sources.json').read_text(encoding='utf-8'))
    snapshot_sources = json.loads((ARCHIVE / 'snapshot-sources.json').read_text(encoding='utf-8'))
    docs = []
    postings = defaultdict(list)
    for category in catalog['categories']:
        for doc in category['files']:
            p = ROOT / doc['path']
            if not p.is_file():
                raise FileNotFoundError(p)
            if p.relative_to(ARCHIVE).as_posix() in excluded:
                continue
            text = p.read_text(encoding='utf-8')
            identifier = len(docs)
            entry = {'name': doc['name'], 'path': doc['path'], 'category': category['category'], 'bytes': p.stat().st_size}
            source = live_sources.get(p.relative_to(ARCHIVE).as_posix())
            if source:
                entry['tableSource'] = source
            if p.relative_to(ARCHIVE).as_posix() in snapshot_sources:
                entry['hasSnapshot'] = True
            docs.append(entry)
            for term in terms(doc['name'] + '\n' + text):
                postings[term].append(identifier)
    knowledge = json.loads((ROOT / 'data/engineering-knowledge/index.json').read_text(encoding='utf-8'))
    cards_by_id = {card['id']: card for card in knowledge['cards']}
    for card in knowledge['cards']:
        identifier = len(docs)
        related = [edge['relationship'] for edge in knowledge['connections'] if card['id'] in (edge['from'], edge['to'])]
        docs.append({'name': card['title'], 'path': '', 'category': card['field'], 'bytes': 0,
                     'knowledge': {'id': card['id'], 'url': card['url'], 'summary': card['summary'], 'related': related, 'checkpoints': card['checkpoints'],
                                   'organization': card['organization'], 'kind': card['kind'],
                                   'reviewed': card['reviewed']}})
        related_titles = [cards_by_id[edge['to'] if edge['from'] == card['id'] else edge['from']]['title']
                          for edge in knowledge['connections'] if card['id'] in (edge['from'], edge['to'])]
        for term in terms(card['title'] + '\n' + card['field'] + '\n' + ' '.join(card['keywords']) + '\n' + card['summary'] + '\n' + ' '.join(related_titles) + '\n' + ' '.join(card['checkpoints'])):
            postings[term].append(identifier)
    result = {'version': 1, 'docs': docs, 'terms': dict(postings)}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'Indexed {len(docs)} documents, {len(postings)} terms, {OUTPUT.stat().st_size} bytes')

if __name__ == '__main__':
    build()
