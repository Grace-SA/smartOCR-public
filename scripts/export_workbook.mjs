import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const [inputPath, outputPath, previewDir] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error('Usage: node export_workbook.mjs records.json output.xlsx [preview-directory]');
const records = JSON.parse(await fs.readFile(inputPath, 'utf8'));
if (!Array.isArray(records)) throw new Error('records must be an array');
const number = value => value === null || value === undefined || value === '' || typeof value === 'boolean' || !Number.isFinite(Number(value)) ? null : Number(value);
const text = value => {
  const str = value === null || value === undefined ? '' : String(value);
  return /^[\s]*[=+@-]|^[\t\r\n]/.test(str) ? "'" + str : str;
};
const purpose = {unknown: 'Not set', personal: 'Personal', work: 'Work'};
const status = {review: 'Needs review', auto_confirmed: 'Auto-confirmed', confirmed: 'Human confirmed'};
const methods = {ai_suggestion:'AI suggestion',ai_grounded:'AI with source evidence',merchant_rule:'Merchant category suggestion',user_review:'User correction',ocr_match:'OCR source match',source_metadata:'Source information',default_assumption:'Default assumption'};
const categories = ['Groceries & food','Dining','Home & hardware','Health & pharmacy','Clothing & retail','Transport & fuel','Electronics & office','Other','Uncategorised'];
const legacyCategories = Object.fromEntries(['超市与食品','餐饮','家居与五金','健康与药房','服饰与百货','交通与燃油','电子与办公','其他','待分类'].map((value,index)=>[value,categories[index]]));
legacyCategories['食品杂货'] = categories[0];
const category = value => legacyCategories[value] || (categories.includes(value) ? value : 'Uncategorised');
const legacySystemText = {'根据有票面依据的商家类型建议；混合购买可手动调整':'Suggestion based on the merchant shown on the receipt; mixed purchases can be recategorised.'};
const date = value => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.valueOf()) && parsed.toISOString().slice(0,10) === value ? parsed : null;
};
const wb = Workbook.create();
const overview = wb.worksheets.add('Overview');
const receipts = wb.worksheets.add('Receipts');
for (const sh of [overview, receipts]) sh.showGridLines = false;
overview.tabColor = '#243f50';
const rows = records.map(r => {
  const src = r.source || {};
  const categoryEvidence = r.field_evidence?.category || {};
  return [text(r.id), text(r.merchant), date(r.date), text(category(r.category)), text(purpose[r.purpose] || r.purpose || 'Not set'), number(r.total), text(r.currency || 'Unknown currency'), text(status[r.status] || 'Needs review'), text((r.tags || []).join(', ')), text(r.notes), text(src.original_name || (src.local_path ? path.basename(src.local_path) : '')), text(src.page_url || src.source_page_url), text(src.image_url), text(src.license), text(methods[categoryEvidence.method] || categoryEvidence.method || 'Not recorded'), text(legacySystemText[categoryEvidence.text] || categoryEvidence.text), text(src.attribution), number(r.confidence?.score), text((r.confidence?.reasons || []).join('; '))];
});
const headers = ['Receipt ID', 'Merchant', 'Date', 'Category', 'Purpose', 'Amount', 'Currency', 'Status', 'Tags', 'Notes', 'Original filename', 'Source page', 'Original image', 'Licence', 'Category method', 'Category evidence', 'Attribution', 'Confidence index', 'Review reasons'];
receipts.getRange('A1:S1').values = [headers];
if (rows.length) receipts.getRange(`A2:S${rows.length + 1}`).values = rows;
const last = Math.max(2, rows.length + 1);
receipts.getRange(`A1:S${last}`).format.font = {name: 'Arial', size: 10, color: '#243b49'};
receipts.getRange(`A1:S${last}`).format.verticalAlignment = 'center';
receipts.getRange(`A1:S${last}`).format.rowHeight = 24;
const widths = {A:25, B:28, C:14, D:25, E:12, F:14, G:12, H:21, I:36, J:60, K:30, L:70, M:70, N:35, O:29, P:65, Q:65, R:22, S:70};
for (const [col, width] of Object.entries(widths)) receipts.getRange(`${col}1:${col}${last}`).format.columnWidth = width;
for (const range of ['A1:S1']) {
  receipts.getRange(range).format.fill = '#243f50';
  receipts.getRange(range).format.font = {name: 'Arial', size: 10, bold:true, color:'#ffffff'};
  receipts.getRange(range).format.horizontalAlignment = 'center';
}
receipts.getRange(`C2:C${last}`).setNumberFormat('dd/mm/yyyy');
receipts.getRange(`C2:C${last}`).format.horizontalAlignment = 'center';
receipts.getRange(`G2:G${last}`).format.horizontalAlignment = 'center';
receipts.getRange(`F2:F${last}`).setNumberFormat('#,##0.00;[Red](#,##0.00);0.00');
receipts.getRange(`F2:F${last}`).format.horizontalAlignment = 'right';
receipts.getRange(`R2:R${last}`).setNumberFormat('0');
receipts.getRange(`H2:H${last}`).conditionalFormats.add('containsText', {text:'Needs review', format:{fill:'#fff0cc',font:{color:'#7a5200'}}});
receipts.freezePanes.freezeRows(1);
receipts.freezePanes.freezeColumns(2);
for (const column of ['B','D','H','I','J','K','L','M','N','O','P','Q','S']) receipts.getRange(`${column}2:${column}${last}`).format.wrapText = true;
receipts.getRange(`A2:S${last}`).format.autofitRows();
if (rows.length) {
  const table = receipts.tables.add(`A1:S${last}`, true, 'ReceiptRecords');
  table.showFilterButton = true;
}

overview.getRange('B2').values = [['Receipt export overview']];
overview.getRange('B4:B7').values = [['Selected receipts'], ['Missing amounts'], ['Needs review'], ['Purpose not set']];
overview.getRange('C4:C7').formulas = rows.length ? [
  [`=COUNTA('Receipts'!A2:A${last})`],
  [`=COUNTBLANK('Receipts'!F2:F${last})`],
  [`=COUNTIFS('Receipts'!H2:H${last},"Needs review")`],
  [`=COUNTIFS('Receipts'!E2:E${last},"Not set")`],
] : [['=0'],['=0'],['=0'],['=0']];
overview.getRange('E4:E6').values = [['Auto-confirmed'], ['Human confirmed'], ['Ready for export']];
overview.getRange('F4:F6').formulas = rows.length ? [
  [`=COUNTIFS('Receipts'!H2:H${last},"Auto-confirmed")`],
  [`=COUNTIFS('Receipts'!H2:H${last},"Human confirmed")`],
  ['=SUM(F4:F5)'],
] : [['=0'],['=0'],['=SUM(F4:F5)']];
overview.getRange('B9:C9').values = [['Currency', 'Recorded net total']];
const currencies = [...new Set(rows.map(r => r[6]))].sort();
let row = 10;
for (const currency of currencies) {
  overview.getRange(`B${row}`).values = [[currency]];
  overview.getRange(`C${row}`).formulas = [[`=IF(SUMPRODUCT(('Receipts'!$G$2:$G$${last}=B${row})*ISNUMBER('Receipts'!$F$2:$F$${last}))=0,"Not recorded",ROUND(SUMIFS('Receipts'!$F$2:$F$${last},'Receipts'!$G$2:$G$${last},B${row}),2))`]];
  row++;
}
overview.getRange(`B${row + 1}`).values = [['Totals include unreviewed amounts; blanks are excluded. Refunds retain their sign.']];
overview.getRange(`B${row + 2}`).values = [['Purpose requires user input. A work label does not establish tax deductibility.']];
overview.getRange(`B${row + 3}`).values = [['Receipts contains exactly this selection, including tags, evidence and sources.']];
overview.getRange(`B${row + 4}`).values = [['Confidence is an evidence index, not a probability of accuracy. Corrections remain available.']];
overview.getRange(`B2:H${row + 4}`).format.font = {name:'Arial', size:10, color:'#243b49'};
overview.getRange('B2').format.font = {name:'Arial',size:16,bold:true,color:'#243f50'};
overview.getRange(`B2:H${row + 4}`).format.rowHeight = 25;
overview.getRange(`A1:A${row + 4}`).format.columnWidth = 3;
overview.getRange(`B1:B${row + 4}`).format.columnWidth = 30;
overview.getRange(`C1:C${row + 4}`).format.columnWidth = 20;
overview.getRange(`D1:D${row + 4}`).format.columnWidth = 3;
overview.getRange(`E1:E${row + 4}`).format.columnWidth = 24;
overview.getRange(`F1:H${row + 4}`).format.columnWidth = 10;
overview.getRange('C4:C7').setNumberFormat('#,##0');
overview.getRange('F4:F6').setNumberFormat('#,##0');
overview.getRange(`C10:C${Math.max(10, row-1)}`).setNumberFormat('#,##0.00;[Red](#,##0.00);0.00');
overview.getRange('B9:C9').format.fill = '#243f50';
overview.getRange('B9:C9').format.font = {name:'Arial',size:10,bold:true,color:'#ffffff'};
overview.getRange('B9:C9').format.horizontalAlignment = 'center';

wb.recalculate();
if (previewDir) {
  const index = rows.findIndex(r => typeof r[5] === 'number');
  if (index >= 0) {
    const cell = receipts.getRange(`F${index + 2}`);
    const result = overview.getRange(`C${10 + currencies.indexOf(rows[index][6])}`);
    const before = result.values[0][0];
    cell.values = [[rows[index][5] + 1]];
    wb.recalculate();
    if (Math.abs(result.values[0][0] - before - 1) > 1e-8) throw new Error('Currency subtotal failed recalculation check');
    cell.values = [[rows[index][5]]];
    wb.recalculate();
  }
}
const summary = await wb.inspect({kind:'table',range:`Overview!B4:C${Math.max(row-1,10)}`,include:'values,formulas',tableMaxRows:20,tableMaxCols:2,maxChars:4000});
const errors = await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},summary:'Export formula scan',maxChars:1500});
if (previewDir) {
  await fs.mkdir(previewDir,{recursive:true});
  for (const [sheetName, range] of [['Overview',`A1:H${row+5}`],['Receipts',`A1:J${Math.min(last,8)}`],['Receipts',`L1:N${Math.min(last,5)}`],['Receipts',`O1:S${Math.min(last,5)}`]]) {
    const blob = await wb.render({sheetName,range,scale:1.5,format:'png'});
    await fs.writeFile(path.join(previewDir,`${sheetName}-${range.split(':')[0]}.png`),new Uint8Array(await blob.arrayBuffer()));
  }
  await fs.writeFile(path.join(previewDir,'inspection.txt'),summary.ndjson+'\n'+errors.ndjson);
}
await fs.mkdir(path.dirname(outputPath),{recursive:true});
const file = await SpreadsheetFile.exportXlsx(wb);
await file.save(outputPath);
console.log(JSON.stringify({output:outputPath,records:rows.length,summary:summary.ndjson,errors:errors.ndjson}));
