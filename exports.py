"""Exports for the local receipt workbench. The caller owns filtering/selection."""

import csv
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from collections import defaultdict
from decimal import Decimal
from html import escape
from receipt_engine import normalise_category, UNKNOWN_MERCHANTS, summarize


ROOT = Path(__file__).resolve().parent
RUNTIME = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"
PURPOSE = {"unknown": "Not set", "personal": "Personal", "work": "Work"}
STATUS = {"review": "Needs review", "auto_confirmed": "Auto-confirmed", "confirmed": "Human confirmed"}
METHODS = {"ai_suggestion": "AI suggestion", "ai_grounded": "AI with source evidence", "merchant_rule": "Merchant category suggestion", "user_review": "User correction", "ocr_match": "OCR source match", "source_metadata": "Source information", "default_assumption": "Default assumption"}
LEGACY_SYSTEM_TEXT = {"根据有票面依据的商家类型建议；混合购买可手动调整": "Suggestion based on the merchant shown on the receipt; mixed purchases can be recategorised."}
HEADERS = ["Receipt ID", "Merchant", "Date", "Amount", "Currency", "Category", "Purpose", "Status", "Tags", "Notes", "Source page", "Original image", "Licence", "Category method", "Category evidence", "Attribution", "Confidence index", "Review reasons"]


def _number(value):
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _safe_text(value):
    """Prevent spreadsheet formula injection while preserving source text."""
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def _source(record):
    source = record.get("source") or {}
    return source if isinstance(source, dict) else {}


def _category_evidence(record):
    evidence = (record.get("field_evidence") or {}).get("category") or {}
    method = evidence.get("method") or "Not recorded"
    explanation=evidence.get("text") or ""
    return METHODS.get(method, method), LEGACY_SYSTEM_TEXT.get(explanation,explanation)


def _csv_row(record):
    source = _source(record)
    values = [record.get("id"), record.get("merchant"), record.get("date"),
              _number(record.get("total")), record.get("currency") or "Unknown",
              normalise_category(record.get("category")), PURPOSE.get(record.get("purpose"), record.get("purpose") or "Not set"),
              STATUS.get(record.get("status"), record.get("status") or "Needs review"),
              ", ".join(record.get("tags") or []), record.get("notes"),
              source.get("page_url") or source.get("source_page_url"), source.get("image_url"), source.get("license"),
              *_category_evidence(record), source.get("attribution"),_number((record.get('confidence') or {}).get('score')),
              '; '.join(str(reason) for reason in (record.get('confidence') or {}).get('reasons',[]))]
    return [v if isinstance(v, (int, float)) else _safe_text(v) for v in values]


def _totals(records):
    totals = defaultdict(Decimal)
    for record in records:
        value = _number(record.get("total"))
        if value is not None:
            totals[record.get("currency") or "Unknown currency"] += Decimal(str(value))
    return dict(totals)


def _create_pdf(records, path, include_originals=False):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

    # Embed a Unicode font so PDF viewers do not need a separate CJK language pack.
    font = "ReceiptCJK"
    try:
        pdfmetrics.getFont(font)
    except KeyError:
        candidates = [os.environ.get("RECEIPT_CJK_FONT", ""), "/System/Library/Fonts/STHeiti Light.ttc", "/System/Library/Fonts/Supplemental/Songti.ttc"]
        font_path = next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)
        if not font_path:
            raise RuntimeError("A Chinese TrueType font is required. Set RECEIPT_CJK_FONT to its path.")
        pdfmetrics.registerFont(TTFont(font, font_path, subfontIndex=0))
    style = ParagraphStyle("body", fontName=font, fontSize=9, leading=13, textColor=colors.HexColor("#243b49"))
    small = ParagraphStyle("small", parent=style, fontSize=8, leading=11)
    heading = ParagraphStyle("title", parent=style, fontSize=20, leading=27, spaceAfter=10)
    section = ParagraphStyle("section", parent=style, fontSize=13, leading=18, spaceBefore=10, spaceAfter=8, keepWithNext=True)
    right = ParagraphStyle("amount", parent=small, alignment=TA_RIGHT)
    header_style = ParagraphStyle("tableheader", parent=small, textColor=colors.white)

    def p(text, st=small):
        return Paragraph(escape(str(text if text is not None else "")), st)

    width, height = A4
    doc = SimpleDocTemplate(str(path), pagesize=(width, height), leftMargin=34, rightMargin=34, topMargin=30, bottomMargin=32,
                            title="Receipt export", author="Receipt Desk")
    missing = sum(_number(r.get("total")) is None for r in records)
    review = sum(r.get("status") not in ('confirmed','auto_confirmed') for r in records)
    automatic=sum(r.get('status')=='auto_confirmed' for r in records)
    human=sum(r.get('status')=='confirmed' for r in records)
    story = [p("Receipt export", heading), p(f"{len(records)} selected receipts | {automatic} auto-confirmed | {human} human confirmed | {review} need review | {missing} missing amounts", style), Spacer(1, 10)]
    totals = _totals(records)
    if totals:
        story.append(p("Recorded net total: " + "; ".join(f"{currency} {value:,.2f}" for currency, value in sorted(totals.items())), style))
    else:
        story.append(p("No recorded amounts are available to total.", style))
    story.append(p("Totals are separate by currency and include receipts requiring review. Missing amounts stay blank; refunds and zeros retain their values. Purpose is not inferred from the merchant.", small))
    story.append(p("Automatic confirmation follows the evidence policy. The confidence index is not an accuracy probability; any field can be corrected.",small))
    story.append(p("This export contains statistics and receipt information for the selected scope.",small))
    story.append(Spacer(1, 12))
    summary = summarize(records)
    story.append(p("Date range: " + str(summary['date_range']['start'] or 'Not recorded') + " to " + str(summary['date_range']['end'] or 'Not recorded'), small))
    for title, key, field in [('By category','category_breakdown','category'),('By month','monthly_breakdown','month'),('By merchant','merchant_breakdown','merchant')]:
        story.append(p(title, section))
        grouped = [[p(field.title(),header_style),p('Receipts',header_style),p('Recorded total',header_style)]]
        grouped += [[p(row[field]),p(row['count']),p(_report_currency_totals(row['currencies']))] for row in summary[key]]
        grouped_table = Table(grouped,colWidths=[230,65,232],repeatRows=1,hAlign='LEFT')
        grouped_table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#243f50')),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
        story.append(grouped_table)
    story.extend([PageBreak(),p('Receipt information',heading)])
    headings = ["Receipt ID", "Date", "Merchant", "Category", "Purpose", "Amount", "Status"]
    rows = [[p(s, header_style) for s in headings]]
    for r in records:
        amount = _number(r.get("total"))
        rows.append([p(r.get("id")), p(r.get("date") or "Not recorded"), p(r.get("merchant") or "Unknown merchant"),
                     p(normalise_category(r.get("category"))), p(PURPOSE.get(r.get("purpose"), r.get("purpose") or "Not set")),
                     p(f"{r.get('currency') or '?'} {amount:,.2f}" if amount is not None else "Not recorded", right),
                     p(STATUS.get(r.get("status"), r.get("status") or "Needs review"))])
    table = Table(rows, colWidths=[85, 55, 92, 90, 50, 65, 90], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#243f50")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6f7")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#243f50")),
    ]))
    story.append(table)
    if records and include_originals:
        story.extend([PageBreak(), p("Tags, evidence and sources", heading)])
        for r in records:
            source = _source(r)
            story.append(p(f"{r.get('id', '')}  {r.get('merchant') or 'Unknown merchant'}", section))
            tags = r.get("tags") or []
            if tags:
                story.append(p("Tags: " + ", ".join(tags)))
            if r.get("notes"):
                story.append(p("Notes: " + str(r["notes"])))
            method, explanation = _category_evidence(r)
            story.append(p("Category method: " + method))
            if explanation:
                story.append(p("Category evidence: " + str(explanation)))
            confidence=r.get('confidence') or {}
            if confidence.get('score') is not None:story.append(p(f"Confidence index: {confidence['score']} / 100 (evidence index, not accuracy)"))
            if confidence.get('reasons'):story.append(p('Review reasons: '+'; '.join(map(str,confidence['reasons']))))
            url = source.get("page_url") or source.get("source_page_url") or source.get("image_url")
            if url:
                # Display exact URL so a printed report remains traceable.
                safe = escape(str(url), quote=True)
                if str(url).startswith(("https://", "http://")):
                    story.append(Paragraph(f'Source: <link href="{safe}" color="#245c80">{safe}</link>', small))
                else:
                    story.append(p("Source: " + str(url)))
            if source.get("license"):
                story.append(p("Licence: " + str(source["license"])))
            if source.get("attribution"):
                story.append(p("Attribution: " + str(source["attribution"])))
            story.append(Spacer(1, 3))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#647680"))
        canvas.drawString(34, 18, "Receipt Desk / Selected scope")
        canvas.drawRightString(width - 34, 18, str(document.page))
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    if records and include_originals:
        _append_original_images(records, path, font)


def _append_original_images(records, path, font):
    """Append only selected local originals/previews without changing receipt pixels."""
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader, simpleSplit
    from reportlab.pdfgen import canvas

    writer = PdfWriter()
    register = PdfReader(str(path))
    writer.append(register)
    register_pages = len(register.pages)
    stream = BytesIO()
    page = canvas.Canvas(stream, pagesize=A4)
    width, height = A4
    for index, record in enumerate(records):
        page.setFillColor(colors.HexColor('#243f50'))
        page.setFont(font, 16)
        page.drawString(36, height-40, f'Original receipt {index+1} of {len(records)}')
        page.setFont(font, 9)
        merchant = str(record.get('merchant') or 'Unknown merchant')
        lines = simpleSplit(merchant, font, 11, width-72)[:2]
        y = height-61
        for line in lines:
            page.setFont(font, 11); page.drawString(36, y, line); y -= 15
        total = _number(record.get('total'))
        amount = f"{record.get('currency') or 'UNKNOWN'} {total:,.2f}" if total is not None else 'Amount not recorded'
        page.setFont(font, 9)
        page.drawString(36, y, f"{record.get('date') or 'Date not recorded'} | {amount} | {STATUS.get(record.get('status'), 'Needs review')}")
        y -= 15
        page.setFont(font, 7)
        page.drawString(36, y, 'Receipt ID: '+str(record.get('id') or ''))
        y -= 12
        page.drawString(36, y, 'Original SHA-256: '+str(record.get('sha256') or 'Not recorded'))
        available_height = y-62
        available_width = width-72
        source = _source(record)
        image = None
        for value in (source.get('preview_path'), source.get('local_path')):
            if not isinstance(value,str) or not value: continue
            candidate = (ROOT/value).resolve()
            if not candidate.is_relative_to(ROOT/'data') or not candidate.is_file(): continue
            try:
                image = ImageReader(str(candidate))
                image.getSize()
                break
            except Exception:
                image = None
        if image is not None:
            image_width, image_height = image.getSize()
            scale = min(available_width/image_width, available_height/image_height)
            draw_width, draw_height = image_width*scale, image_height*scale
            page.drawImage(image, (width-draw_width)/2, 50+(available_height-draw_height)/2,
                           width=draw_width, height=draw_height, preserveAspectRatio=True, mask='auto')
        else:
            page.setFont(font, 11)
            page.drawString(36, height/2, 'Original image is not available in this workspace.')
        page.setFont(font, 8)
        page.setFillColor(colors.HexColor('#647680'))
        page.drawString(36, 22, 'Receipt Desk / Original image attachment')
        page.drawRightString(width-36, 22, str(register_pages+index+1))
        page.showPage()
    page.save()
    stream.seek(0)
    writer.append(PdfReader(stream))
    writer.add_metadata({'/Title':'Receipt export with original images','/Author':'Receipt Desk'})
    temp = Path(path).with_suffix('.images.tmp.pdf')
    with temp.open('wb') as output: writer.write(output)
    temp.replace(path)


def create_export(records, format, output_path, *, include_originals=False, include_evidence=False):
    """Export exactly the provided records, preserving order and missing values.

    Returns a pathlib.Path. XLSX needs the bundled Node runtime; PDF needs reportlab.
    Uploaded source files are not transmitted anywhere by this module.
    """
    records = list(records)
    fmt = str(format).lower().lstrip(".")
    if fmt not in {"xlsx", "pdf", "csv", "json"}:
        raise ValueError("Unsupported export format: " + fmt)
    if fmt != "json":
        records = [{**record, "merchant": "Unknown merchant"}
                   if record.get("merchant") in UNKNOWN_MERCHANTS else record
                   for record in records]
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        payload = records if include_evidence else {"summary":summarize(records), "receipts":[{key:r.get(key) for key in ("id","merchant","date","total","currency","category","purpose","tags","notes","status")} for r in records]}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    elif fmt == "csv":
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(HEADERS)
            writer.writerows(_csv_row(record) for record in records)
    elif fmt == "pdf":
        _create_pdf(records, path, include_originals=include_originals)
    else:
        node = Path(os.environ.get("RECEIPT_NODE", RUNTIME / "node/bin/node"))
        if not node.is_file():
            raise RuntimeError("Bundled Node runtime not found; set RECEIPT_NODE to its executable.")
        with tempfile.TemporaryDirectory(prefix="receipt-export-") as tmp:
            input_file = Path(tmp) / "records.json"
            input_file.write_text(json.dumps(records, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            result = subprocess.run([str(node), str(ROOT / "scripts/export_workbook.mjs"), str(input_file), str(path)],
                                    cwd=str(ROOT), capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise RuntimeError("Workbook export failed: " + result.stderr[-2000:])
    return path


def _report_currency_totals(currencies):
    return '; '.join(f"{currency} {values['total_cents']/100:,.2f}" if values.get('known_count') else f'{currency}: no recorded amounts'
                     for currency, values in sorted(currencies.items())) or 'No recorded amounts'


def _report_html(report):
    """Render stored facts only. This path does not call an AI model."""
    def e(value): return escape(str(value if value is not None else ''),quote=True)
    def paragraphs(text): return ''.join('<p>'+e(part)+'</p>' for part in str(text or '').split('\n\n') if part)
    summary=report.get('summary') or {}
    ai=paragraphs(report.get('ai_text')) if report.get('ai_text') else '<p>'+e(report.get('ai_unavailable_reason') or 'AI commentary was not requested. The statistics below are available without AI.')+'</p>'
    distributions=[]
    for title,key,field in [('Categories','category_breakdown','category'),('Merchants','merchant_breakdown','merchant'),('Months','monthly_breakdown','month')]:
        rows=report.get(key,summary.get(key,[]))
        body=''.join('<tr><td>'+e(row[field])+'</td><td>'+e(row['count'])+'</td><td>'+e(_report_currency_totals(row['currencies']))+'</td></tr>' for row in rows)
        distributions.append('<section><h2>'+title+'</h2><table><thead><tr><th>'+field.title()+'</th><th>Receipts</th><th>Recorded net total</th></tr></thead><tbody>'+body+'</tbody></table></section>' if rows else '<section><h2>'+title+'</h2><p>No data in this scope.</p></section>')
    cards=''.join('<div class="metric"><strong>'+e(summary.get(key,0))+'</strong><span>'+label+'</span></div>' for key,label in [('count','Selected receipts'),('auto_confirmed','Auto-confirmed'),('human_confirmed','Human confirmed'),('review_count','Needs review')])
    actions=''.join('<li><strong>'+e(item.get('title'))+'</strong> '+e(item.get('description'))+'</li>' for item in report.get('action_items',[]))
    return '<!doctype html><html lang="en-AU"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Receipt insights</title><style>' + '''
body{margin:0;background:#f2f5f6;color:#233d49;font:16px/1.55 Arial,sans-serif}main{max-width:1040px;margin:32px auto;padding:36px;background:white;border-radius:12px}h1{margin:0 0 8px;font-size:32px}h2{margin:32px 0 12px;font-size:22px}p{overflow-wrap:anywhere}.meta{font-size:13px;color:#566e79}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}.metric{background:#edf4f4;padding:16px;border-radius:8px}.metric strong{display:block;font-size:28px}.metric span{font-size:13px}table{width:100%;border-collapse:collapse;font-size:14px}th{text-align:left;background:#243f50;color:white}td,th{padding:10px;border-bottom:1px solid #dde5e8}tr:nth-child(even){background:#f5f8f9}td:nth-child(2){text-align:right}td:last-child{font-variant-numeric:tabular-nums}li{margin:8px 0}.ai{background:#f1f6fa;padding:4px 20px 16px;border-radius:8px}.ids{font-size:12px;word-break:break-word}@media(max-width:650px){main{margin:0;padding:20px}.metrics{grid-template-columns:repeat(2,1fr)}}@media print{body{background:white}main{margin:0;padding:0}section,.ai{break-inside:avoid}table{font-size:11px}thead{display:table-header-group}}
'''+'</style></head><body><main><h1>Receipt insights</h1><p class="meta">Created '+e(report.get('created_at'))+' | Selected scope: '+e(summary.get('count',0))+' receipts</p><div class="metrics">'+cards+'</div>'+paragraphs(report.get('narrative'))+'<h2>Computed statistics</h2><ul>'+''.join('<li>'+e(fact)+'</li>' for fact in report.get('facts',[]))+'</ul><div class="ai"><h2>AI commentary</h2><p class="meta">Status: '+e(report.get('ai_status','not_requested'))+(' | Engine: '+e(report.get('ai_engine')) if report.get('ai_engine') else '')+'</p>'+ai+'</div>'+''.join(distributions)+'<h2>Suggested next actions</h2><ol>'+actions+'</ol><h2>Scope and limitations</h2><ul>'+''.join('<li>'+e(item)+'</li>' for item in report.get('limitations',[]))+'</ul><p class="meta">Source snapshot: '+e(report.get('fingerprint'))+'</p><details><summary>Included receipt IDs</summary><p class="ids">'+e(', '.join(map(str,report.get('record_ids',[]))))+'</p></details></main></body></html>'


def _create_report_pdf(report,path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    font='ReceiptCJK'
    try: pdfmetrics.getFont(font)
    except KeyError:
        candidates=[os.environ.get('RECEIPT_CJK_FONT',''),'/System/Library/Fonts/STHeiti Light.ttc','/System/Library/Fonts/Supplemental/Songti.ttc']
        font_path=next((candidate for candidate in candidates if candidate and Path(candidate).is_file()),None)
        if not font_path:raise RuntimeError('A Unicode TrueType font is required. Set RECEIPT_CJK_FONT to its path.')
        pdfmetrics.registerFont(TTFont(font,font_path,subfontIndex=0))
    body=ParagraphStyle('report-body',fontName=font,fontSize=10,leading=15,spaceAfter=7,textColor=colors.HexColor('#243b49'))
    small=ParagraphStyle('report-small',parent=body,fontSize=8,leading=11,wordWrap='CJK')
    heading=ParagraphStyle('report-heading',parent=body,fontSize=15,leading=20,spaceBefore=16,spaceAfter=9,keepWithNext=True)
    title=ParagraphStyle('report-title',parent=heading,fontSize=25,leading=31,spaceBefore=0)
    header=ParagraphStyle('report-header',parent=small,textColor=colors.white)
    def p(value,style=body):return Paragraph(escape(str(value if value is not None else '')),style)
    summary=report.get('summary') or {}
    story=[p('Receipt insights',title),p(f"Created {report.get('created_at','')} | {summary.get('count',0)} selected receipts",small),p(report.get('narrative'))]
    story.extend([p('Computed statistics',heading),*[p('• '+str(fact)) for fact in report.get('facts',[])]])
    story.append(p('AI commentary',heading))
    story.append(p('Status: '+str(report.get('ai_status','not_requested'))+(' | Engine: '+str(report['ai_engine']) if report.get('ai_engine') else ''),small))
    commentary=report.get('ai_text') or report.get('ai_unavailable_reason') or 'AI commentary was not requested. The statistics remain available without AI.'
    story.extend(p(paragraph) for paragraph in str(commentary).split('\n\n') if paragraph)
    for label,key,field in [('Categories','category_breakdown','category'),('Merchants','merchant_breakdown','merchant'),('Months','monthly_breakdown','month')]:
        story.append(p(label,heading));rows=report.get(key,summary.get(key,[]))
        if not rows:story.append(p('No data in this scope.'));continue
        table_rows=[[p(field.title(),header),p('Receipts',header),p('Recorded net total',header)]]
        table_rows.extend([[p(row[field],small),p(row['count'],small),p(_report_currency_totals(row['currencies']),small)] for row in rows])
        table=Table(table_rows,colWidths=[210,55,A4[0]-345],repeatRows=1,hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#243f50')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f3f6f7')]),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
        story.extend([table,Spacer(1,5)])
    story.append(p('Suggested next actions',heading))
    for action in report.get('action_items',[]):story.append(p(str(action.get('title',''))+': '+str(action.get('description',''))))
    story.append(p('Scope and limitations',heading))
    story.extend(p('• '+str(item),small) for item in report.get('limitations',[]))
    story.extend([p('Source snapshot: '+str(report.get('fingerprint','')),small),p('Included receipt IDs: '+', '.join(map(str,report.get('record_ids',[]))),small)])
    def footer(canvas,document):
        canvas.saveState();canvas.setFont(font,8);canvas.setFillColor(colors.HexColor('#647680'))
        canvas.drawString(40,20,'Receipt Desk / Receipt insights');canvas.drawRightString(A4[0]-40,20,str(document.page));canvas.restoreState()
    SimpleDocTemplate(str(path),pagesize=A4,leftMargin=40,rightMargin=40,topMargin=35,bottomMargin=36,title='Receipt insights',author='Receipt Desk').build(story,onFirstPage=footer,onLaterPages=footer)


def create_report_export(report,format,output_path):
    """Export the supplied report snapshot, without re-running extraction or AI."""
    fmt=str(format).lower().lstrip('.')
    if fmt not in {'html','pdf','json'}:raise ValueError('Unsupported report format: '+fmt)
    path=Path(output_path).resolve();path.parent.mkdir(parents=True,exist_ok=True)
    if fmt=='html':path.write_text(_report_html(report),encoding='utf-8')
    elif fmt=='json':path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    else:_create_report_pdf(report,path)
    return path
