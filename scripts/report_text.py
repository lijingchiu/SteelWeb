"""Extract the actual published slide text and cached chart values for the assistant."""
from __future__ import annotations

import hashlib
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
}


def _points(element):
    if element is None:
        return {}
    return {int(p.get('idx')): p.findtext('c:v', default='', namespaces=NS)
            for p in element.findall('.//c:pt', NS) if p.get('idx') is not None}


def _chart(z, name):
    root = ET.fromstring(z.read(name))
    series = []
    for ser in root.findall('.//c:ser', NS):
        title = ser.find('c:tx', NS)
        values = _points(ser.find('c:val', NS))
        categories = _points(ser.find('c:cat', NS))
        label = next(iter(_points(title).values()), '') or (title.findtext('c:v', default='', namespaces=NS) if title is not None else '')
        if values:
            series.append({'name': label, 'points': [{'category': categories.get(i, str(i)), 'value': value} for i, value in values.items()]})
    return series


def extract_report(path: Path, date: str, file: str):
    raw = path.read_bytes()
    import io
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = sorted((n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)),
                       key=lambda n: int(re.search(r'\d+', n).group()))
        if not names:
            raise ValueError('電子報沒有投影片')
        pages = []
        for number, name in enumerate(names, 1):
            root = ET.fromstring(z.read(name))
            lines = []
            # Each paragraph belongs to a visible text box or table cell; join runs.
            for paragraph in root.findall('.//a:p', NS):
                line = ''.join(t.text or '' for t in paragraph.findall('.//a:t', NS)).strip()
                if line:
                    lines.append(line)
            charts = []
            relfile = f'ppt/slides/_rels/slide{number}.xml.rels'
            if relfile in z.namelist():
                rels = ET.fromstring(z.read(relfile))
                targets = {r.get('Id'): r.get('Target') for r in rels.findall('rel:Relationship', NS)
                           if r.get('Type', '').endswith('/chart') and r.get('TargetMode') != 'External'}
                for node in root.findall('.//c:chart', NS):
                    target = targets.get(node.get(f"{{{NS['r']}}}id"))
                    if target:
                        chartpath = posixpath.normpath(posixpath.join('ppt/slides', target))
                        if not chartpath.startswith('ppt/charts/'):
                            raise ValueError('電子報圖表位置不正確')
                        charts.extend(_chart(z, chartpath))
            pages.append({'page': number, 'text': lines, 'charts': charts})
    return {'date': date, 'file': file, 'sha256': hashlib.sha256(raw).hexdigest(), 'pages': pages}
