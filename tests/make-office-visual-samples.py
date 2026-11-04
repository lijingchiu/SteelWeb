"""Build self-contained Office documents with independent picture and chart facts."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.shared import Inches
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.drawing.image import Image as XLImage
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches as PI

out = Path('/tmp/steel-office-visual-test'); out.mkdir(exist_ok=True)
try: font=ImageFont.truetype('DejaVuSans-Bold.ttf',48)
except OSError: font=ImageFont.load_default()
for ext, marker in [('docx','WORDPHOTO793'),('xlsx','EXCELPHOTO684'),('pptx','PPTPHOTO562')]:
    im=Image.new('RGB',(1100,300),'white'); ImageDraw.Draw(im).text((30,110),'STEEL INSPECTION '+marker,font=font,fill='black'); im.save(out/f'{ext}.png')
# Each chart contains values absent from the image and written under distinct categories.
doc=Document(); doc.add_paragraph('Steel inspection report.'); doc.add_picture(str(out/'docx.png'),width=Inches(5)); doc.save(out/'office.docx')
wb=Workbook(); ws=wb.active; ws.title='Rebar costs'; ws.append(['Year','Rebar cost']); ws.append(['2024',31247]); ws.append(['2025',58763]); ws.add_image(XLImage(str(out/'xlsx.png')),'E2')
chart=BarChart(); chart.title='Rebar cost'; chart.add_data(Reference(ws,min_col=2,min_row=1,max_row=3),titles_from_data=True); chart.set_categories(Reference(ws,min_col=1,min_row=2,max_row=3)); ws.add_chart(chart,'E20'); wb.save(out/'office.xlsx')
prs=Presentation(); slide=prs.slides.add_slide(prs.slide_layouts[5]); slide.shapes.title.text='Steel inspection'; slide.shapes.add_picture(str(out/'pptx.png'),PI(0.5),PI(1),width=PI(6))
cd=CategoryChartData(); cd.categories=['2024','2025']; cd.add_series('Rebar cost',[41638,79251]); slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED,PI(0.5),PI(3.5),PI(7),PI(3),cd); prs.save(out/'office.pptx')
# Add an actual OOXML chart object to the Word document using the cached chart
# written by python-pptx. The picture and chart are both reachable via rels.
with ZipFile(out/'office.pptx') as z: chart_xml=z.read('ppt/charts/chart1.xml')
with ZipFile(out/'office.docx') as z: entries={n:z.read(n) for n in z.namelist()}
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'; R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'; REL='http://schemas.openxmlformats.org/package/2006/relationships'; CT='http://schemas.openxmlformats.org/package/2006/content-types'
rels=ET.fromstring(entries['word/_rels/document.xml.rels']); ET.SubElement(rels,f'{{{REL}}}Relationship',{'Id':'rIdChartTest','Type':R+'/chart','Target':'charts/chart1.xml'}); entries['word/_rels/document.xml.rels']=ET.tostring(rels,encoding='utf-8',xml_declaration=True)
root=ET.fromstring(entries['word/document.xml']); body=root.find(f'{{{W}}}body'); p=ET.SubElement(body,f'{{{W}}}p'); run=ET.SubElement(p,f'{{{W}}}r')
run.append(ET.fromstring(f'''<w:drawing xmlns:w="{W}" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:r="{R}"><wp:inline><wp:extent cx="5486400" cy="2743200"/><wp:docPr id="500" name="Rebar chart"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart r:id="rIdChartTest"/></a:graphicData></a:graphic></wp:inline></w:drawing>''')); entries['word/document.xml']=ET.tostring(root,encoding='utf-8',xml_declaration=True)
types=ET.fromstring(entries['[Content_Types].xml']); ET.SubElement(types,f'{{{CT}}}Override',{'PartName':'/word/charts/chart1.xml','ContentType':'application/vnd.openxmlformats-officedocument.drawingml.chart+xml'}); entries['[Content_Types].xml']=ET.tostring(types,encoding='utf-8',xml_declaration=True); entries['word/charts/chart1.xml']=chart_xml.replace(b'41638',b'22917').replace(b'79251',b'65142')
with ZipFile(out/'office.docx','w',ZIP_DEFLATED) as z:
    for n,data in entries.items(): z.writestr(n,data)
print('Created three synthetic Office files with images and chart data.')
