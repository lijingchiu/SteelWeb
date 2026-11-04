#!/usr/bin/env python3
"""Read-only checks for today's Taiwan research and delivery state."""
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TW = timezone(timedelta(hours=8))


def read(root, name):
    try:
        return json.loads((root / name).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def status(root, today):
    latest = read(root, 'data/latest.json')
    history = read(root, f'data/history/{today}.json')
    analysis = latest.get('date') == today and history.get('date') == today
    materials = read(root, 'data/materials.json')
    outlooks = read(root, 'data/material-outlooks.json')
    try:
        generated = datetime.fromisoformat(outlooks.get('generated_at', ''))
        current = (generated.tzinfo is not None and (outlooks.get('research_date') or generated.astimezone(TW).date().isoformat()) == today)
    except (TypeError, ValueError):
        current = False
    research = bool(current and outlooks.get('failed_batches') == 0
                    and outlooks.get('total_items') == len(materials.get('items', []))
                    and outlooks.get('total_items', 0) > 0 and outlooks.get('covered_items', 0) > 0)
    report = read(root, 'data/report.json')
    stem = f'reports/steel-daily-{today}'
    paths = (stem + '.pptx', stem + '.pdf')
    hashes = ((report.get('content') or {}).get('sha256'), report.get('pdf_sha256'))
    ready = report.get('date') == today and (report.get('file'), report.get('pdf_file')) == paths
    if ready:
        try:
            ready = all(h and hashlib.sha256((root / p).read_bytes()).hexdigest() == h for p, h in zip(paths, hashes))
        except OSError:
            ready = False
    sent = read(root, 'data/notify-state.json')
    notifications = all((sent.get(channel) or {}).get('date') == today for channel in ('push', 'email'))
    return {'analysis': analysis, 'research': research, 'report': bool(ready), 'notifications': notifications}


def target_date(now, scheduled=True):
    local = now.astimezone(TW)
    day = local.date()
    if scheduled and local.hour == 23 and local.minute >= 50:
        day += timedelta(days=1)
    return day


def allow_scheduled(now, state):
    local = now.astimezone(TW)
    target = target_date(local)
    in_window = local.hour < 8 or (local.hour == 23 and local.minute >= 50)
    return target.weekday() < 5 and in_window and not all(state.values())


if __name__ == '__main__':
    now = datetime.now(TW)
    command = sys.argv[1]
    scheduled = os.environ.get('EVENT_NAME') == 'schedule'
    target = os.environ.get('RESEARCH_DATE') or target_date(now, scheduled).isoformat()
    if command == 'target':
        print(target)
    else:
        state = status(Path('.'), target)
        if command == 'gate':
            print('true' if allow_scheduled(now, state) else 'false')
        elif command == 'ready':
            print('true' if state['analysis'] and state['research'] and state['report'] else 'false')
        else:
            print('true' if state[command] else 'false')
