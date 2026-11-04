"""Convert a newsletter deck to a validated, readable PDF with CJK fonts."""
from __future__ import annotations

import html
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from pypdf import PdfReader


def convert_report_pdf(pptx: Path, pdf: Path, slides: int, title: str) -> None:
    executable = os.environ.get('SOFFICE_BINARY') or shutil.which('soffice') or shutil.which('libreoffice')
    if not executable:
        raise RuntimeError('找不到 LibreOffice，無法產生電子報 PDF。')
    pdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='steel-report-pdf-') as tmp:
        work = Path(tmp)
        # The bundled macOS converter needs explicit system font directories;
        # Linux Actions installs Noto CJK and Liberation fonts before conversion.
        if sys.platform == 'darwin':
            dirs = ['/System/Library/Fonts', '/System/Library/Fonts/Supplemental', '/Library/Fonts']
            preferred = 'STHeiti'
        else:
            dirs = ['/usr/share/fonts', '/usr/local/share/fonts']
            preferred = 'Noto Sans CJK TC'
        config = work / 'fonts.conf'
        font_dirs = ''.join(f'<dir>{html.escape(path)}</dir>' for path in dirs if Path(path).is_dir())
        config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
                          + font_dirs + f'<cachedir>{html.escape(str(work / "font-cache"))}</cachedir>'
                          + '<alias binding="strong"><family>Microsoft JhengHei</family><prefer>'
                          + f'<family>{preferred}</family></prefer></alias></fontconfig>', encoding='utf-8')
        env = os.environ.copy()
        env.update(FONTCONFIG_FILE=str(config), XDG_CACHE_HOME=str(work / 'cache'))
        proc = subprocess.run([executable, f'-env:UserInstallation={(work / "profile").as_uri()}',
                               '--headless', '--convert-to', 'pdf', '--outdir', str(work), str(pptx.resolve())],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180, env=env)
        output = work / (pptx.stem + '.pdf')
        if proc.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError(f'PDF 轉換失敗：{(proc.stderr or proc.stdout)[-500:]}')
        try:
            reader = PdfReader(str(output))
            if len(reader.pages) != slides:
                raise ValueError(f'頁數不符：PDF {len(reader.pages)} 頁，簡報 {slides} 頁')
            normalized = lambda s: ''.join(str(s or '').split())
            cover = normalized(reader.pages[0].extract_text())
            if not title or normalized(title) not in cover:
                raise ValueError('封面標題無法正確讀取，可能缺少中文字型')
        except Exception as exc:
            raise RuntimeError(f'PDF 驗證失敗：{exc}') from exc
        staged = pdf.with_name(pdf.name + '.tmp')
        try:
            shutil.copyfile(output, staged)
            os.replace(staged, pdf)
        finally:
            if staged.exists():
                staged.unlink()
