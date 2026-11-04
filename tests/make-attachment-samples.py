"""Create harmless synthetic engineering samples for the live attachment test."""
from pathlib import Path
from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from reportlab.pdfgen import canvas
from PIL import Image, ImageDraw

out = Path('/tmp/steel-attachment-test')
out.mkdir(exist_ok=True)
doc = Document(); doc.add_paragraph('Steel rebar inspection marker DOC271'); doc.save(out / 'sample.docx')
book = Workbook(); book.active['A1'] = 'Steel rebar inspection marker XLS272'; book.save(out / 'sample.xlsx')
ppt = Presentation(); slide = ppt.slides.add_slide(ppt.slide_layouts[1]); slide.shapes.title.text = 'Steel rebar inspection marker PPT273'; ppt.save(out / 'sample.pptx')
pdf = canvas.Canvas(str(out / 'sample.pdf')); pdf.drawString(40, 750, 'Steel rebar inspection marker PDF274'); pdf.save()
im = Image.new('RGB', (1000, 300), 'white'); ImageDraw.Draw(im).text((30, 80), 'STEEL REBAR PHOTO MARKER IMG275', fill='black', stroke_width=1); im.save(out / 'sample.png')
