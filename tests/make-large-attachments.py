"""Build synthetic boundary-size files without writing private user data."""
from pathlib import Path
import os, re, shutil, struct, subprocess
out=Path('/tmp/steel-attachment-test');out.mkdir(exist_ok=True)
source=(out/'sample.pdf').read_bytes()
# PDF comments and an EOF marker preserve the original page and cross-reference.
target=49_000_000
xref=re.search(rb'startxref\s+(\d+)\s+%%EOF',source)
if not xref: raise RuntimeError('source PDF lacks cross-reference')
tail=b'\nstartxref\n'+xref.group(1)+b'\n%%EOF\n'
with (out/'large.pdf').open('wb') as f:
    f.write(source);f.write(b'\n%');f.seek(target-len(tail));f.write(tail)
ffmpeg=os.environ.get('FFMPEG_BIN') or shutil.which('ffmpeg')
if not ffmpeg: raise RuntimeError('ffmpeg is needed to generate the video fixture')
video=out/'large.mp4'
subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-loop','1','-i',str(out/'sample.png'),'-t','3','-r','3','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(video)],check=True)
# A valid MP4 free atom keeps the same 3-second footage while padding the file.
target=300*1024*1024
size=video.stat().st_size
with video.open('ab') as f:
    f.write(struct.pack('>I4s',target-size,b'free'))
with video.open('r+b') as f:
    f.seek(target-1);f.write(b'\0')
print(f'Created PDF { (out/"large.pdf").stat().st_size } bytes and video {video.stat().st_size} bytes.')

# Two independent documents exceed the aggregate request limit but remain
# individually valid; their distinct facts must survive batching and synthesis.
from reportlab.pdfgen import canvas
for label, price in [('a',12500), ('b',22700)]:
    small=out/f'batch-{label}-source.pdf'
    pdf=canvas.Canvas(str(small));pdf.drawString(40,750,f'Steel rebar quote {label.upper()}: {price} TWD per metric ton.');pdf.save()
    raw=small.read_bytes(); match=re.search(rb'startxref\s+(\d+)\s+%%EOF',raw)
    if not match: raise RuntimeError('batch PDF lacks cross-reference')
    tail=b'\nstartxref\n'+match.group(1)+b'\n%%EOF\n'
    with (out/f'batch-{label}.pdf').open('wb') as f:
        f.write(raw);f.write(b'\n%');f.seek(26_000_000-len(tail));f.write(tail)
print('Created two distinct 26 MB PDFs for multi-batch comparison.')
