"""Build the English project guide from maintained Markdown (ReportLab)."""
import html
import re
import textwrap
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image, Preformatted, KeepTogether

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/pdf/CameraDrone-Guide.pdf';OUT.parent.mkdir(parents=True,exist_ok=True)
FONTS=Path('/usr/share/fonts/truetype/dejavu')
for name,file in [('Body','DejaVuSans.ttf'),('Bold','DejaVuSans-Bold.ttf'),('Mono','DejaVuSansMono.ttf')]:
    pdfmetrics.registerFont(TTFont(name,str(FONTS/file)))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='Bold',italic='Body',boldItalic='Bold')
INK=colors.HexColor('#172c38');ACCENT=colors.HexColor('#3a714b');PALE=colors.HexColor('#edf3ee')
styles={
 'body':ParagraphStyle('body',fontName='Body',fontSize=9,leading=12,textColor=INK,spaceAfter=6),
 'h1':ParagraphStyle('h1',fontName='Bold',fontSize=23,leading=29,textColor=INK,spaceAfter=16),
 'h2':ParagraphStyle('h2',fontName='Bold',fontSize=14,leading=19,textColor=ACCENT,spaceBefore=10,spaceAfter=6,keepWithNext=True),
 'h3':ParagraphStyle('h3',fontName='Bold',fontSize=11,leading=16,textColor=INK,spaceBefore=9,spaceAfter=6,keepWithNext=True),
 'cell':ParagraphStyle('cell',fontName='Body',fontSize=8,leading=11,textColor=INK,spaceAfter=0,splitLongWords=True),
 'code':ParagraphStyle('code',fontName='Mono',fontSize=7,leading=10,textColor=INK,backColor=PALE,borderPadding=8,spaceBefore=4,spaceAfter=10),
}
WIDTH=475

def inline(s):
    s=html.escape(s).replace('–','-').replace('—','-').replace('‑','-').replace('→','-&gt;').replace('↔','&lt;-&gt;')
    s=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',lambda m: '<link href="'+m[2]+'" color="#3a714b">'+m[1]+'</link>' if m[2].startswith('http') else m[1],s)
    s=re.sub(r'`([^`]+)`',r'<font name="Mono" size="8">\1</font>',s)
    return re.sub(r'\*\*([^*]+)\*\*',r'<b>\1</b>',s)

def para(s,style='body'):return Paragraph(inline(s),styles[style])

def table(rows):
    n=len(rows[0]);proportions={2:[.32,.68],3:[.24,.34,.42],4:[.2,.22,.27,.31]}.get(n,[1/n]*n)
    content=[[para(v,'cell') for v in row] for row in rows]
    t=Table(content,colWidths=[WIDTH*x for x in proportions],repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),PALE),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('LINEBELOW',(0,0),(-1,0),1,ACCENT),('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#d9e1df'))]))
    return [t,Spacer(1,10)]

def parse(path):
    lines=path.read_text().splitlines();result=[];i=0
    while i<len(lines):
        line=lines[i];i+=1
        if not line.strip():continue
        if line.startswith('!['):continue
        if line.startswith('```'):
            language=line[3:].strip();code=[]
            while i<len(lines) and not lines[i].startswith('```'):code.append(lines[i]);i+=1
            i+=1
            if language=='mermaid':
                text=('Browser / localhost host UI  ->  explicit source manager\n'
                      '  ->  Local simulator or replay / Ubuntu vision\n'
                      '  ->  Pi API / Picamera2 / ISP / Pi vision\n\n'
                      'Air link target: one camera -> H.264 -> RTP -> WFB\n'
                      '  ->  ground RTP decoder -> native display\n'
                      'Radio + camera encoder fanout: hardware integration pending')
            else:text='\n'.join(code)
            wrapped=[]
            for row in text.splitlines():wrapped.extend(textwrap.wrap(row,88,replace_whitespace=False,drop_whitespace=False) or [''])
            result.append(Preformatted('\n'.join(wrapped),styles['code']))
            continue
        if line.startswith('|'):
            rows=[ [c.strip() for c in line.strip('|').split('|')] ]
            while i<len(lines) and lines[i].startswith('|'):
                row=[c.strip() for c in lines[i].strip('|').split('|')];i+=1
                if all(re.fullmatch(r':?-+:?',c.replace(' ','')) for c in row):continue
                rows.append(row)
            result.extend(table(rows));continue
        if line.startswith('# '):result.append(para(line[2:],'h1'));continue
        if line.startswith('## '):result.append(para(line[3:],'h2'));continue
        if line.startswith('### '):result.append(para(line[4:],'h3'));continue
        if line.startswith('- '):result.append(para('• '+line[2:]));continue
        if re.match(r'^\d+\. ',line):result.append(para(line));continue
        paragraph=[line]
        while i<len(lines) and lines[i].strip() and not lines[i].startswith(('#','|','```','- ','![')) and not re.match(r'^\d+\. ',lines[i]):
            paragraph.append(lines[i]);i+=1
        result.append(para(' '.join(paragraph)))
    return result

def footer(canvas,doc):
    canvas.setStrokeColor(ACCENT);canvas.setLineWidth(.5);canvas.line(60,47,535,47)
    canvas.setFillColor(INK);canvas.setFont('Body',8)
    canvas.drawString(60,33,'CAMERADRONE  /  ENGINEERING GUIDE  /  2026-11-03')
    canvas.drawRightString(535,33,str(doc.page))

story=[Spacer(1,32),para('CAMERADRONE','h1'),para('Camera Studio engineering guide','h2'),
       para('Ubuntu host application - Raspberry Pi camera - offline development - airborne video preparation'),
       Spacer(1,12),para('Release 0.2 / 3 November 2026'),
       para('Ubuntu offline validation and current Pi 5 hardware regression are documented separately, including startup-rate observations and a recording shutdown fix. Radio integration and Pi 3 A+ performance remain unverified.'),Spacer(1,12)]
shot=ROOT/'docs/images/offline-studio.png'
if shot.exists():
    w,h=ImageReader(str(shot)).getSize();story.append(Image(str(shot),width=WIDTH,height=WIDTH*h/w))
story+=[Spacer(1,8),para('Synthetic preview only. No real camera imagery or credentials are included.','cell'),PageBreak()]
chapters=[('Quick start','README.md'),('Setup and deployment','docs/SETUP.md'),('Application workflow','docs/USER_GUIDE.md'),
          ('Architecture and API','docs/ARCHITECTURE.md'),('Airborne transport','docs/AIRLINK.md'),('Validation and limits','VALIDATION.md'),
          ('Current Pi 5 regression','docs/HARDWARE_REGRESSION_2026-11-03.md'),('Hardware roadmap','docs/ROADMAP.md'),('Third-party components','THIRD_PARTY.md'),('Public release workflow','docs/PUBLISHING.md')]
story += [para('Guide contents','h1')]
for number,(title,path) in enumerate(chapters,1):story.append(para(f'{number:02d}  {title}'))
story += [Spacer(1,20),para('Source of truth','h2'),para('This guide is generated from the Markdown documents in the repository. Shell examples use the repository working directory. Use your virtualenv Python where appropriate. Local addresses shown in examples are placeholders; private runtime files and test recordings are intentionally absent.'),
          para('Rebuild','h2'),para('Install ReportLab and system DejaVu fonts, then run python3 tools/build_pdf.py. The Markdown documents retain clickable relative links and Mermaid diagrams; the PDF includes simplified text schematics.'),PageBreak()]
for idx,(_,path) in enumerate(chapters):
    story.extend(parse(ROOT/path))
    if idx<len(chapters)-1:story.append(PageBreak())
doc=SimpleDocTemplate(str(OUT),pagesize=(595.28,841.89),leftMargin=60,rightMargin=60,topMargin=54,bottomMargin=65,
                      title='CameraDrone - Camera Studio Engineering Guide',author='Maksim Nuzhdin')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
print(OUT)
