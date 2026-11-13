import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';

const fields = ['merchant', 'date', 'total'];
const finite = x => typeof x === 'number' && Number.isFinite(x);
const count = (rows, predicate) => rows.filter(predicate).length;
const ratio = (n, d) => d ? n / d : null;
const same = (a, b, label) => {
  if (a === null || b === null) assert.equal(a, b, label);
  else assert.ok(Math.abs(a - b) < 1e-8, `${label}: ${a} != ${b}`);
};
const literal = value => {
  const s = value == null ? '' : String(value);
  return /^[\s]*[=+@-]|^[\t\r\n]/.test(s) ? "'" + s : s;
};
const yesNo = x => x === true ? 'Yes' : x === false ? 'No' : 'Not recorded';
const matched = x => x === true ? 'Match' : x === false ? 'Mismatch' : 'No reference';
const numeric = x => x === null || x === undefined || x === '' || typeof x === 'boolean' || !Number.isFinite(Number(x)) ? null : Number(x);
const dateValue = x => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(x || '')) return literal(x);
  const d = new Date(`${x}T00:00:00Z`);
  return Number.isFinite(d.valueOf()) && d.toISOString().slice(0, 10) === x ? d : literal(x);
};

export function timing(values) {
  const sorted = values.filter(finite).sort((a, b) => a - b);
  const n = sorted.length;
  return {
    count: n, total: n ? sorted.reduce((a, b) => a + b, 0) : null,
    mean: n ? sorted.reduce((a, b) => a + b, 0) / n : null,
    median: n ? (sorted[Math.floor((n - 1) / 2)] + sorted[Math.floor(n / 2)]) / 2 : null,
    p90: n ? sorted[Math.ceil(n * .90) - 1] : null,
    p95: n ? sorted[Math.ceil(n * .95) - 1] : null,
    maximum: n ? sorted[n - 1] : null,
  };
}

// This checks the supplied evaluation. It never rescores predictions or opens source files.
export function validateEvaluation(report, { synthetic = false } = {}) {
  assert.ok(report && Array.isArray(report.results), 'Expected evaluation results');
  assert.equal(report.synthetic_fixture === true, synthetic, 'Synthetic input requires --synthetic; real input must not use it');
  if (!synthetic) assert.ok(report.complete && report.tested_count === 100 && report.selected_count === 100, 'Only a completed 100-receipt evaluation can produce a real workbook');
  const rows = report.results;
  assert.equal(new Set(rows.map(r => r.id)).size, rows.length, 'Duplicate receipt IDs');
  assert.equal(report.tested_count, rows.length, 'Tested count');
  for (const r of rows) {
    assert.ok(r.id && r.expected && r.actual && r.field_matches, 'Incomplete evaluation row');
    assert.ok(finite(r.wall_seconds) && r.wall_seconds >= 0, 'Invalid wall seconds');
    assert.ok(r.pipeline_seconds == null || finite(r.pipeline_seconds) && r.pipeline_seconds >= 0, 'Invalid pipeline seconds');
    for (const f of fields) assert.ok([true, false, null].includes(r.field_matches[f]), 'Invalid match flag');
  }
  for (const f of fields) {
    const available = count(rows, r => r.field_matches[f] !== null);
    const correct = count(rows, r => r.field_matches[f] === true);
    assert.equal(report.fields[f].correct, correct, `${f} correct`);
    assert.equal(report.fields[f].reference_available, available, `${f} denominator`);
    assert.equal(report.fields[f].missing_reference, rows.length - available, `${f} missing reference`);
    same(report.fields[f].accuracy, ratio(correct, available), `${f} accuracy`);
  }
  const auto = rows.filter(r => r.auto_confirmed);
  const known = auto.filter(r => r.reference_complete);
  assert.equal(report.all_core_correct, count(rows, r => r.core_correct), 'All-core count');
  assert.equal(report.complete_reference_count, count(rows, r => r.reference_complete), 'Complete references');
  assert.equal(report.processing_success_count, count(rows, r => r.processing_success), 'Processing count');
  assert.equal(report.all_three_complete_count, count(rows, r => r.all_three_complete), 'Three-model count');
  assert.equal(report.automatic.count, auto.length, 'Automatic count');
  assert.equal(report.automatic.fully_scorable, known.length, 'Scorable confirmations');
  assert.equal(report.automatic.correct, count(known, r => r.core_correct), 'Correct confirmations');
  same(report.automatic.coverage, rows.length ? auto.length / rows.length : 0, 'Automatic coverage');
  same(report.automatic.precision, ratio(count(known, r => r.core_correct), known.length), 'Automatic precision');
  assert.deepEqual([...report.automatic.false_confirmations].sort(), known.filter(r => !r.core_correct).map(r => r.id).sort());
  assert.deepEqual([...report.automatic.unverified_confirmations].sort(), auto.filter(r => !r.reference_complete).map(r => r.id).sort());
  const wall = timing(rows.map(r => r.wall_seconds));
  for (const key of ['total', 'mean', 'median', 'p90', 'p95', 'maximum']) same(report.timing_seconds[key], wall[key], `Wall ${key}`);
  return { wall, pipeline: timing(rows.map(r => r.pipeline_seconds)) };
}

export async function exportEvaluation(inputPath, outputPath, { synthetic = false, previewDir } = {}) {
  const input = await fs.readFile(inputPath);
  const report = JSON.parse(input);
  const stats = validateEvaluation(report, { synthetic });
  if (synthetic) assert.ok(/synthetic/i.test(outputPath), 'Synthetic output filename must contain synthetic');
  const { Workbook, SpreadsheetFile } = await import('@oai/artifact-tool');
  const wb = Workbook.create();
  const overview = wb.worksheets.add('Overview');
  const detail = wb.worksheets.add('Per receipt');
  const headers = ['Receipt ID', 'Merchant expected', 'Merchant actual', 'Merchant match', 'Date expected', 'Date actual', 'Date match', 'Total expected (AUD)', 'Total actual (AUD)', 'Total match', 'All core correct', 'Reference complete', 'Auto-confirmed', 'Decision', 'Confidence index', 'Wall seconds', 'Pipeline seconds', 'All three models complete', 'Processing success', 'Run failed', 'Timed out', 'Return code', 'Reference uncertainty', 'Confidence reasons', 'Paddle timing (JSON)', 'Unlimited timing (JSON)', 'OXR timing (JSON)', 'Image path', 'Image SHA-256', 'Prediction SHA-256', 'Run SHA-256', 'Source URL'];
  const rows = report.results.map(r => [
    literal(r.id), literal(r.expected.merchant), literal(r.actual.merchant), matched(r.field_matches.merchant),
    dateValue(r.expected.date), dateValue(r.actual.date), matched(r.field_matches.date),
    numeric(r.expected.total) ?? literal(r.expected.total), numeric(r.actual.total) ?? literal(r.actual.total), matched(r.field_matches.total),
    yesNo(r.core_correct), yesNo(r.reference_complete), yesNo(r.auto_confirmed), literal(r.status), numeric(r.confidence?.score),
    r.wall_seconds, r.pipeline_seconds ?? null, yesNo(r.all_three_complete), yesNo(r.processing_success), yesNo(!r.processing_success), yesNo(r.timed_out), r.returncode ?? null,
    literal((r.reference_uncertainty || []).join('; ')), literal((r.confidence?.reasons || []).join('; ')),
    ...['paddle', 'unlimited', 'oxr'].map(e => r.model_timing?.[e] ? JSON.stringify(r.model_timing[e]) : ''),
    literal(r.image_path), literal(r.image_sha256), literal(r.prediction_sha256), literal(r.run_sha256), literal(r.source_url),
  ]);
  const last = Math.max(2, rows.length + 1);
  for (const sh of [overview, detail]) sh.showGridLines = false;
  overview.tabColor = '#263c56';
  detail.getRange('A1:AF1').values = [headers];
  if (rows.length) detail.getRange(`A2:AF${last}`).values = rows;
  detail.getRange(`A1:AF${last}`).format.font = { name: 'Arial', size: 10, color: '#263c56' };
  detail.getRange(`A1:AF${last}`).format.verticalAlignment = 'center';
  detail.getRange(`A1:AF${last}`).format.rowHeight = 28;
  const widths = [18, 30, 30, 17, 16, 16, 17, 20, 20, 17, 18, 20, 20, 24, 21, 18, 19, 25, 23, 18, 18, 17, 58, 58, 55, 55, 55, 54, 70, 70, 70, 70];
  widths.forEach((w, i) => detail.getRangeByIndexes(0, i, last, 1).format.columnWidth = w);
  detail.getRange('A1:AF1').format.fill = '#263c56';
  detail.getRange('A1:AF1').format.font = { name: 'Arial', size: 10, bold: true, color: '#ffffff' };
  detail.getRange('A1:AF1').format.horizontalAlignment = 'center';
  detail.getRange('A1:AF1').format.wrapText = true;
  detail.getRange('A1:AF1').format.rowHeight = 42;
  detail.getRange(`E2:F${last}`).setNumberFormat('yyyy-mm-dd');
  detail.getRange(`E2:F${last}`).format.horizontalAlignment = 'center';
  detail.getRange(`H2:I${last}`).setNumberFormat('#,##0.00;[Red](#,##0.00);0.00');
  detail.getRange(`O2:O${last}`).setNumberFormat('0');
  detail.getRange(`P2:Q${last}`).setNumberFormat('0.00');
  for (const c of ['B','C','N','W','X','Y','Z','AA','AB','AC','AD','AE','AF']) detail.getRange(`${c}2:${c}${last}`).format.wrapText = true;
  detail.getRange(`A2:AF${last}`).format.autofitRows();
  for (let i=2;i<=last;i++) {
    const r=detail.getRange(`A${i}:AF${i}`);
    if(r.format.rowHeight<24) r.format.rowHeight=24;
  }
  for(const c of ['D','G','J','K','L','M','R','S','T','U']) detail.getRange(`${c}2:${c}${last}`).format.horizontalAlignment='center';
  for (const c of ['D','G','J']) {
    detail.getRange(`${c}2:${c}${last}`).conditionalFormats.add('containsText', {text:'Mismatch',format:{fill:'#fde9e7',font:{color:'#9d231e'}}});
    detail.getRange(`${c}2:${c}${last}`).conditionalFormats.add('containsText', {text:'No reference',format:{fill:'#fff2cc',font:{color:'#775600'}}});
  }
  for (const c of ['K','R','S']) detail.getRange(`${c}2:${c}${last}`).conditionalFormats.add('containsText', {text:'No',format:{fill:'#fde9e7',font:{color:'#9d231e'}}});
  for (const c of ['T','U']) detail.getRange(`${c}2:${c}${last}`).conditionalFormats.add('containsText', {text:'Yes',format:{fill:'#fde9e7',font:{color:'#9d231e'}}});
  detail.freezePanes.freezeRows(1); detail.freezePanes.freezeColumns(1);
  if (rows.length) detail.tables.add(`A1:AF${last}`, true, 'BlindEvaluationRows').showFilterButton = true;

  overview.getRange('A1:G48').format.font = {name:'Arial',size:10,color:'#263c56'};
  overview.getRange('A1:G48').format.verticalAlignment = 'center';
  overview.getRange('A1:G48').format.rowHeight = 25;
  for (const [c, w] of Object.entries({A:3,B:35,C:16,D:16,E:16,F:3,G:88})) overview.getRange(`${c}1:${c}48`).format.columnWidth = w;
  overview.getRange('B2').values = [[synthetic ? 'SYNTHETIC FIXTURE — layout test only' : 'Blind OCR evaluation']];
  overview.getRange('B2').format.font = {name:'Arial',size:15,bold:true,color:'#263c56'};
  overview.getRange('B3').values = [[synthetic ? 'Invented examples. No real blind-test scores.' : `Frozen first-pass evaluation. ${report.tested_count} receipts tested.`]];
  overview.getRange('B4').values = [[`Evaluation created: ${report.created_at}`]];
  const range = c => `'Per receipt'!$${c}$2:$${c}$${last}`;
  const put = (cell, value) => overview.getRange(cell).values = [[value]];
  const formula = (cell, value) => overview.getRange(cell).formulas = [[value]];
  const countif = (c, v) => `COUNTIFS(${range(c)},"${v}")`;
  const tested = `COUNTA(${range('A')})`;
  overview.getRange('B6:E6').values = [['Field accuracy','Correct','Scorable','Accuracy']];
  for (const [i, c] of ['D','G','J'].entries()) {
    const row = 7+i; put(`B${row}`, fields[i][0].toUpperCase()+fields[i].slice(1));
    formula(`C${row}`, `=${countif(c,'Match')}`);
    formula(`D${row}`, `=${tested}-${countif(c,'No reference')}`);
    formula(`E${row}`, `=IF(D${row}=0,"Not measurable",C${row}/D${row})`);
  }
  overview.getRange('B11:E11').values = [['Receipt correctness','Correct','Tested','Rate']];
  put('B12','All core fields correct'); formula('C12',`=${countif('K','Yes')}`); formula('D12',`=${tested}`); formula('E12','=IF(D12=0,"Not measurable",C12/D12)');
  put('B13','Complete references'); formula('C13',`=${countif('L','Yes')}`);
  overview.getRange('B15:E15').values = [['Automatic confirmation','Numerator','Denominator','Rate']];
  put('B16','Coverage'); formula('C16',`=${countif('M','Yes')}`); formula('D16','=D12'); formula('E16','=IF(D16=0,"Not measurable",C16/D16)');
  put('B17','Strict auto match rate'); formula('C17',`=COUNTIFS(${range('M')},"Yes",${range('L')},"Yes",${range('K')},"Yes")`); formula('D17',`=COUNTIFS(${range('M')},"Yes",${range('L')},"Yes")`); formula('E17','=IF(D17=0,"Not measurable",C17/D17)');
  put('B18','Strict auto nonmatches'); formula('C18',`=COUNTIFS(${range('M')},"Yes",${range('L')},"Yes",${range('K')},"No")`);
  put('B19','Unverified auto-confirmations'); formula('C19',`=COUNTIFS(${range('M')},"Yes",${range('L')},"No")`);
  overview.getRange('B21:C21').values = [['Processing','Count']];
  for (const [i,label,c,flag] of [[22,'Processing success','S','Yes'],[23,'All three models complete','R','Yes'],[24,'Run failed','T','Yes'],[25,'Timed out','U','Yes']]) { put(`B${i}`,label); formula(`C${i}`,`=${countif(c,flag)}`); }
  overview.getRange('B28:D28').values = [['Time (seconds)','Wall','Pipeline']];
  const timingSpecs = [[29,'Total','SUM'],[30,'Mean','AVERAGE'],[31,'Median','MEDIAN'],[32,'P90, nearest rank',.90],[33,'P95, nearest rank',.95],[34,'Maximum','MAX']];
  for (const [r,label,fn] of timingSpecs) {
    put(`B${r}`,label);
    for (const [out,c] of [['C','P'],['D','Q']]) {
      // Descending rank preserves nearest-rank percentiles when timings contain blanks.
      const expr = typeof fn==='number' ? `LARGE(${range(c)},COUNT(${range(c)})-ROUNDUP(COUNT(${range(c)})*${fn},0)+1)` : `${fn}(${range(c)})`;
      formula(`${out}${r}`,`=IF(COUNT(${range(c)})=0,"Not recorded",${expr})`);
    }
  }
  put('B35','Recorded timings'); formula('C35',`=COUNT(${range('P')})`); formula('D35',`=COUNT(${range('Q')})`);
  put('B36','Missing timings'); formula('C36','=D12-C35'); formula('D36','=D12-D35');
  const notes = [
    [6,'How to read these results'],
    [8,'Field accuracy uses available references for that field.'],
    [9,'All-core rate uses every tested receipt, including failed runs.'],
    [11,'Coverage = automatically confirmed / all tested receipts.'],
    [12,'Precision = correct / fully scorable automatic confirmations.'],
    [14,'Confidence is an evidence index, not a probability of accuracy.'],
    [16,'References: second assistant visual transcription and review.'],
    [17,'References are not an independent human gold standard.'],
    [19,synthetic ? 'Transport share: not applicable to this synthetic fixture.' : 'Sample bias: transport accounts for 73 of 100 receipts (73%).'],
    [20,synthetic ? 'Real cohort context: transport 73/100 (73%); this fixture has no sampling claim.' : 'Public sources and repeated layouts limit generalisation.'],
    [22,'Three-model completion means Paddle, Unlimited and OXR all completed.'],
    [23,'Individual model completion flags are not supplied by the evaluation.'],
    [25,'Wall time includes process/model loading, preparation and retries.'],
    [26,'Pipeline time is reported separately; missing values stay blank.'],
    [28,'P90/P95 use the nearest-rank rule from the scoring script.'],
    [30,'Reported accuracy does not guarantee accuracy on future receipts.'],
    [32,'Matching rule: exact ISO date and amount to the cent.'],
    [33,'Merchant ignores case, spaces and punctuation; & equals and.'],
    [34,'No aliases or fuzzy matching. Saved score flags are preserved.'],
    [35,'Name-only nonmatches need visual review; see the HTML interpretation.'],
    [36,'Actual values and reference values remain separate on Per receipt.'],
  ];
  for (const [r,t] of notes) put(`G${r}`,t);
  overview.getRange('G6').format.font = {name:'Arial',size:10,bold:true,color:'#263c56'};
  for (const address of ['B6:E6','B11:E11','B15:E15','B21:C21','B28:D28']) {
    const r=overview.getRange(address); r.format.fill='#263c56'; r.format.font={name:'Arial',size:10,bold:true,color:'#ffffff'}; r.format.horizontalAlignment='center';
  }
  overview.getRange('C7:D25').setNumberFormat('0');
  overview.getRange('E7:E17').setNumberFormat('0.0%');
  overview.getRange('C29:D34').setNumberFormat('0.00');
  overview.getRange('C35:D36').setNumberFormat('0');
  put('B39','Source and reproducibility');
  put('B40','Evaluation SHA-256'); put('C40',createHash('sha256').update(input).digest('hex'));
  put('B41','Manifest SHA-256'); put('C41',report.manifest_sha256);
  put('B42','Reference SHA-256'); put('C42',report.reference_sha256);
  put('B43','Extraction freeze SHA-256'); put('C43',report.extraction_freeze_sha256);
  put('B44','Confidence policy SHA-256'); put('C44',report.confidence_policy_sha256);
  put('B46','Per-receipt values are copied from the supplied evaluation. No OCR or rescoring occurs during export.');
  wb.recalculate();

  let recalculationCheck=null;
  if(synthetic && rows.length) {
    const before=overview.getRange('C29').values[0][0];
    const original=detail.getRange('P2').values[0][0];
    detail.getRange('P2').values=[[original+1]];
    wb.recalculate();
    same(overview.getRange('C29').values[0][0],before+1,'Temporary timing change recalculation');
    detail.getRange('P2').values=[[original]];
    wb.recalculate();
    same(overview.getRange('C29').values[0][0],before,'Restored timing recalculation');
    recalculationCheck={passed:true,temporary_change_restored:true};
  }

  // Compare formula results to the independent score-file aggregates before export.
  const checks = [];
  const check = (cell,expected,label=cell) => { const actual=overview.getRange(cell).values[0][0]; same(actual,expected,label); checks.push({cell,expected,actual}); };
  for (const [i,f] of fields.entries()) {check(`C${7+i}`,report.fields[f].correct);check(`D${7+i}`,report.fields[f].reference_available);if(report.fields[f].accuracy!==null)check(`E${7+i}`,report.fields[f].accuracy);}
  check('C12',report.all_core_correct); check('D12',report.tested_count); check('C13',report.complete_reference_count);
  check('C16',report.automatic.count); check('E16',report.automatic.coverage); check('C17',report.automatic.correct); check('D17',report.automatic.fully_scorable);
  if(report.automatic.precision!==null)check('E17',report.automatic.precision);
  check('C18',report.automatic.false_confirmations.length);check('C19',report.automatic.unverified_confirmations.length);
  check('C22',report.processing_success_count);check('C23',report.all_three_complete_count);
  for (const [c,data] of [['C',stats.wall],['D',stats.pipeline]]) for(const [i,k] of ['total','mean','median','p90','p95','maximum'].entries()) if(data[k]!==null)check(`${c}${29+i}`,data[k]);
  const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},summary:'Blind export formula error scan',maxChars:2000});
  const labels=await wb.inspect({kind:'table',range:'Overview!B6:E19',include:'values,formulas',tableMaxRows:14,tableMaxCols:4,maxChars:5500});
  if (previewDir) {
    await fs.mkdir(previewDir,{recursive:true});
    for(const [name,sheetName,range] of [['overview','Overview','A1:G46'],['fields','Per receipt',`A1:K${Math.min(last,7)}`],['decisions','Per receipt',`L1:V${Math.min(last,7)}`],['evidence','Per receipt',`W1:AA${Math.min(last,7)}`]]) {
      const blob=await wb.render({sheetName,range,scale:1.3,format:'png'});
      await fs.writeFile(path.join(previewDir,`${name}.png`),new Uint8Array(await blob.arrayBuffer()));
    }
    await fs.writeFile(path.join(previewDir,'checks.json'),JSON.stringify({synthetic,checks,recalculation_check:recalculationCheck,formula_errors:errors.ndjson,overview_inspection:labels.ndjson,source_sha256:createHash('sha256').update(input).digest('hex')},null,2));
  }
  await fs.mkdir(path.dirname(outputPath),{recursive:true});
  await (await SpreadsheetFile.exportXlsx(wb)).save(outputPath);
  return {output:outputPath,synthetic,records:rows.length,checks:checks.length,formula_errors:errors.ndjson};
}

if (process.argv[1] && fileURLToPath(import.meta.url)===path.resolve(process.argv[1])) {
  const args=process.argv.slice(2); const synthetic=args.includes('--synthetic'); const positional=args.filter(x=>x!=='--synthetic');
  if(positional.length<2) throw new Error('Usage: export_blind_evaluation.mjs evaluation.json output.xlsx [preview-dir] [--synthetic]');
  console.log(JSON.stringify(await exportEvaluation(positional[0],positional[1],{previewDir:positional[2],synthetic})));
}
