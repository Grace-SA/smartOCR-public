import { homedir } from 'node:os';
import { fileURLToPath, pathToFileURL } from 'node:url';
const { chromium } = await import(pathToFileURL(process.env.RECEIPT_PLAYWRIGHT || homedir() + '/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs').href);
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';

// Live checks are read-only. Mutation and AI-state checks use intercepted APIs;
// they verify the browser contract, not the OCR policy or backend accuracy.
const base = process.env.RECEIPT_TEST_URL || 'http://127.0.0.1:8765';
const root = fileURLToPath(new URL('..', import.meta.url)).replace(/\/$/, '');
const output = root + '/output/qa/english-workflow';
await fs.mkdir(output, {recursive:true});
const browser = await chromium.launch({headless:true, executablePath:process.env.RECEIPT_CHROMIUM || homedir() + '/Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'});
const page = await browser.newPage({viewport:{width:1440,height:1040}, deviceScaleFactor:1});
page.setDefaultTimeout(15000);
const errors=[];
page.on('pageerror',e=>errors.push(e.message));
const result={live:{}, mocked_contract:{}, errors};
const waitCount=async count=>page.waitForFunction(expected=>document.querySelector('#receipt-rows').children.length===expected,count);
const noOverflow=async()=>{
  const widths=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));
  assert(widths.document<=widths.viewport,JSON.stringify(widths));return widths;
};
try {
  const response=await page.request.get(base+'/api/receipts');assert.equal(response.status(),200);
  const actual=await response.json();assert(actual.receipts.length>0);
  const pending=actual.receipts.filter(r=>!['confirmed','auto_confirmed'].includes(r.status)).length;
  await page.goto(base);await page.waitForFunction(n=>Number(document.querySelector('#nav-total').textContent)===n,actual.receipts.length);
  assert.equal(await page.locator('html').getAttribute('lang'),'en-AU');await waitCount(pending);
  assert.equal(await page.locator('#nav-review').getAttribute('class'),'nav-item active');
  await page.screenshot({path:output+'/desktop.png'});
  await page.locator('#nav-auto').click();await waitCount(actual.receipts.filter(r=>r.status==='auto_confirmed').length);
  await page.locator('#nav-all').click();await waitCount(actual.receipts.length);
  await page.locator('#nav-categories').click();assert.equal(await page.locator('.category-card').count(),actual.categories.length);
  await page.screenshot({path:output+'/categories.png'});
  const firstCategory=actual.receipts.find(r=>r.category)?.category;
  await page.locator('.category-card').filter({has:page.locator('h3')}).evaluateAll((cards,category)=>cards.find(c=>c.dataset.category===category)?.click(),firstCategory);
  const categoryCount=actual.receipts.filter(r=>r.category===firstCategory).length;await waitCount(categoryCount);
  assert.equal(await page.locator('#filter-category').inputValue(),firstCategory);
  assert.equal(await page.locator('#export-count').textContent(),`${categoryCount} receipt${categoryCount===1?'':'s'}`);
  await page.locator('#clear-filters').click();await waitCount(actual.receipts.length);
  await page.locator('#search').fill('NO-MATCH-TEST-RECEIPT-XYZ');await waitCount(0);assert(await page.locator('#export-button').isDisabled());
  await page.locator('#search').fill('');await page.locator('.receipt-row').first().click();await page.locator('#receipt-dialog').waitFor({state:'visible'});
  await page.waitForFunction(()=>document.querySelector('#receipt-image').complete&&document.querySelector('#receipt-image').naturalWidth>0);
  assert.match(await page.locator('#detail-confidence').textContent(),/not a calibrated probability/);
  await page.screenshot({path:output+'/detail.png'});await page.locator('#close-detail').click();
  await page.locator('#export-scope').selectOption('all');await page.locator('#nav-report').click();assert(await page.locator('.report-fact').count()===4);
  assert.match(await page.locator('#insight-scope-label').textContent(),new RegExp(`${actual.receipts.length} receipts`));
  assert.equal(await page.locator('.bar-fill').first().evaluate(el=>getComputedStyle(el).display),'block');
  await page.screenshot({path:output+'/insights.png',fullPage:true});
  for(const view of ['nav-all','nav-categories','nav-report']){
    await page.locator('#'+view).click();await page.setViewportSize({width:390,height:844});await noOverflow();
    assert.equal(await page.evaluate(()=>/[\u3400-\u9fff]/.test(document.body.innerText)),false,'Visible application text must be English');
    await page.screenshot({path:output+'/'+view+'-mobile.png',fullPage:false});await page.setViewportSize({width:1440,height:1040});
  }
  result.live={count:actual.receipts.length,needs_review:pending,auto_confirmed:actual.receipts.filter(r=>r.status==='auto_confirmed').length,categories:actual.categories.length,category_filter_count:categoryCount,english:true,mobile_overflow:false};

  // Small explicit browser fixtures keep all writes away from the user's data.
  const categories=['Groceries & food','Dining','Home & hardware','Health & pharmacy','Clothing & retail','Transport & fuel','Electronics & office','Other','Uncategorised'];
  const template=actual.receipts[0];
  const fixture=[
    {id:'ui_auto',merchant:'Coles',date:'2026-01-02',total:10,category:categories[0],status:'auto_confirmed',confidence:{score:99,band:'high',reasons:['Three independent models support every core field.'],auto_confirmable:true}},
    {id:'ui_review',merchant:'Cafe Example',date:'2026-01-03',total:20,category:categories[1],status:'review',confidence:{score:55,band:'medium',reasons:['The models disagree on the receipt total.'],auto_confirmable:false}},
    {id:'ui_manual',merchant:'Bunnings',date:'2026-01-04',total:30,category:categories[2],status:'confirmed',confidence:{score:80,band:'medium',reasons:['Human correction is retained.'],auto_confirmable:false}}
  ].map(r=>({...r,currency:'AUD',purpose:'unknown',tags:[],notes:'',source:template.source,edit_history:[],original_extraction:{merchant:r.merchant,date:r.date,total:r.total}}));
  const requests={updates:[],bulk:[],exports:[],reports:[]};let reportMode='failure',releaseReport=null,blindComplete=false;
  await page.route('**/api/receipts',route=>route.fulfill({json:{receipts:fixture,categories,processing:false}}));
  await page.route('**/api/sample-report',route=>route.fulfill({json:{}}));
  await page.route('**/api/blind-status',route=>route.fulfill({json:blindComplete==='awaiting_report'?{target_count:100,completed:100,state:'complete'}:blindComplete?{target_count:100,completed:100,state:'complete',report_url:'/output/quality/blind100.html'}:{target_count:100,completed:12,state:'running'}}));
  await page.route('**/api/update',route=>{
    const payload=route.request().postDataJSON();requests.updates.push(payload);const record=fixture.find(r=>r.id===payload.id);
    const before=Object.fromEntries(Object.keys(payload.changes).map(key=>[key,record[key]]));Object.assign(record,payload.changes);
    record.edit_history.push({at:'2026-11-13T01:00:00Z',before,after:payload.changes});return route.fulfill({json:record});
  });
  await page.route('**/api/bulk-update',route=>{
    const payload=route.request().postDataJSON();requests.bulk.push(payload);for(const r of fixture)if(payload.ids.includes(r.id))Object.assign(r,payload.changes);
    return route.fulfill({json:{count:payload.ids.length,records:fixture.filter(r=>payload.ids.includes(r.id))}});
  });
  await page.route('**/api/export',route=>{const payload=route.request().postDataJSON();requests.exports.push(payload);return route.fulfill({json:{url:'/qa-contract-download.'+payload.format,count:payload.ids.length}});});
  await page.route('**/qa-contract-download.*',route=>route.fulfill({status:200,headers:{'Content-Type':'application/octet-stream','Content-Disposition':'attachment; filename="browser-contract-download.txt"'},body:'UI contract fixture only'}));
  await page.route('**/api/report',async route=>{
    const payload=route.request().postDataJSON();requests.reports.push(payload);if(reportMode==='delayed')await new Promise(resolve=>{releaseReport=resolve;});else await new Promise(resolve=>setTimeout(resolve,150));
    if(reportMode==='failure')return route.fulfill({status:503,json:{error:'The analysis service is temporarily unavailable.'}});
    return route.fulfill({json:{record_ids:payload.ids,created_at:'2026-11-13T01:00:00Z',ai_status:'ready',ai_text:'This selected collection has a clear category breakdown. Review uncertain readings before sharing.',download_url:'/qa-contract-download.json',downloads:{json:'/qa-contract-download.json',html:'/qa-contract-download.html',pdf:'/qa-contract-download.pdf'}}});
  });
  await page.reload();await waitCount(1);await page.waitForFunction(()=>document.querySelector('#blind-quality-link').textContent==='Blind test: 12/100');
  blindComplete='awaiting_report';await page.evaluate(()=>refreshBlindStatus());assert.equal(await page.locator('#blind-quality-link').evaluate(el=>el.tagName),'SPAN');assert.equal(await page.evaluate(()=>!!blindTimer),true);
  blindComplete=true;await page.evaluate(()=>refreshBlindStatus());assert.equal(await page.locator('#blind-quality-link').getAttribute('href'),base+'/output/quality/blind100.html');
  await page.locator('#nav-auto').click();await page.locator('[data-id="ui_auto"]').click();
  assert.match(await page.locator('#detail-confidence').textContent(),/99\/100/);
  await page.locator('#detail-form [name=notes]').fill('Household filing');await page.locator('#save-detail').click();await page.locator('#receipt-dialog').waitFor({state:'hidden'});
  assert.equal(requests.updates.at(-1).changes.status,undefined,'Notes alone must preserve automatic confirmation');
  await page.locator('[data-id="ui_auto"]').click();await page.locator('#detail-form [name=total]').fill('10.50');await page.locator('#save-detail').click();await page.locator('#receipt-dialog').waitFor({state:'hidden'});
  assert.equal(requests.updates.at(-1).changes.status,'confirmed');assert.equal(requests.updates.at(-1).changes.total,10.5);
  await page.locator('#nav-confirmed').click();await page.locator('[data-id="ui_auto"]').click();
  await page.locator('#history-section summary').click();assert.match(await page.locator('#detail-history').textContent(),/AUD 10.00 → AUD 10.50/);assert.match(await page.locator('#detail-history').textContent(),/Original extraction/);
  await page.locator('#close-detail').click();await page.locator('#nav-all').click();await waitCount(3);
  await page.locator('#advanced-toggle').click();await page.locator('#filter-start').fill('2026-01-02');await page.locator('#filter-end').fill('2026-01-03');await page.locator('#filter-min').fill('11');await page.locator('#filter-max').fill('21');await waitCount(1);
  assert.equal(await page.locator('.receipt-row').first().getAttribute('data-id'),'ui_review');await page.locator('#clear-filters').click();await waitCount(3);
  await page.locator('[data-id="ui_auto"] input').check();await page.locator('[data-id="ui_review"] input').check();
  await page.locator('#bulk-category').selectOption('Other');await page.locator('#bulk-apply').click();await page.waitForFunction(()=>document.querySelector('#bulk-apply').textContent==='Apply category');
  assert.deepEqual(requests.bulk.at(-1),{ids:['ui_auto','ui_review'],changes:{category:'Other'}});
  await page.locator('#export-scope').selectOption('selected');
  for(const format of ['xlsx','pdf','csv','json']){
    await page.locator('#export-format').selectOption(format);const downloaded=page.waitForEvent('download');await page.locator('#export-button').click();await downloaded;
    assert.deepEqual(requests.exports.at(-1),{ids:['ui_auto','ui_review'],format});await page.waitForFunction(()=>!document.querySelector('#export-button').disabled);
    assert.match(await page.locator('#export-result').textContent(),/2 receipts exported/);
  }
  await page.locator('#generate-report').click();await page.waitForFunction(()=>document.querySelector('#report-body').textContent.includes('AI commentary is unavailable'));
  assert(await page.locator('.report-fact').count()===4);assert.deepEqual(requests.reports.at(-1).ids,['ui_auto','ui_review']);
  reportMode='success';await page.locator('#generate-report').click();await page.waitForFunction(()=>document.querySelector('#report-engine').textContent==='AI insight available');
  assert.match(await page.locator('.insight-ai').textContent(),/This selected collection/);for(const id of ['report-download','report-read','report-pdf'])assert(await page.locator('#'+id).isVisible());
  fixture[0].total=11;fixture[0].updated_at='2026-11-13T00:00:00Z';
  await page.locator('#refresh').click();await page.waitForFunction(()=>document.querySelector('#report-engine').textContent==='Update needed');
  assert.match(await page.locator('.insight-ai').textContent(),/out of date/);assert.doesNotMatch(await page.locator('.insight-ai').textContent(),/This selected collection/);
  for(const id of ['report-download','report-read','report-pdf'])assert(await page.locator('#'+id).isHidden());
  await page.locator('#generate-report').click();await page.waitForFunction(()=>document.querySelector('#report-engine').textContent==='AI insight available');
  reportMode='delayed';await page.locator('#generate-report').click();
  await page.waitForFunction(()=>document.querySelector('#generate-report').textContent==='Generating…');
  while(!releaseReport)await new Promise(resolve=>setTimeout(resolve,10));
  fixture[0].category='Dining';fixture[0].updated_at='2026-11-13T00:01:00Z';
  const reloaded=page.waitForResponse(r=>r.url().endsWith('/api/receipts'));await page.locator('#refresh').click();await reloaded;
  await page.waitForFunction(()=>document.querySelectorAll('.bar-row').length===2);releaseReport();releaseReport=null;
  await page.waitForFunction(()=>document.querySelector('#report-engine').textContent==='Update needed');
  assert.doesNotMatch(await page.locator('.insight-ai').textContent(),/This selected collection/);for(const id of ['report-download','report-read','report-pdf'])assert(await page.locator('#'+id).isHidden());
  reportMode='success';await page.locator('#generate-report').click();await page.waitForFunction(()=>document.querySelector('#report-engine').textContent==='AI insight available');
  await page.locator('#export-scope').selectOption('all');assert.doesNotMatch(await page.locator('.insight-ai').textContent(),/This selected collection/,'A report for selected IDs must not appear as an all-record report');
  await page.locator('#export-scope').selectOption('selected');await page.locator('#nav-all').click();await page.locator('#clear-selection').click();await page.locator('#nav-report').click();
  assert.match(await page.locator('#report-body').textContent(),/No receipts in this scope/);assert(await page.locator('#generate-report').isDisabled());assert(await page.locator('#export-button').isDisabled());
  result.mocked_contract={notes_preserve_auto:true,core_override_confirmed:true,original_and_history_visible:true,date_amount_filters:true,bulk_category:true,selected_export_formats:['xlsx','pdf','csv','json'],ai_failure_and_success:true,external_change_marks_report_stale:true,change_during_generation_marks_report_stale:true,stale_ai_and_downloads_hidden:true,blind_progress_and_report_link:true,waits_for_scoring_after_ocr_complete:true,scope_mismatch_hidden:true,empty_scope:true};
  fixture.push({id:'ui_unknown',merchant:'待识别商家',date:null,total:null,currency:'AUD',category:'Uncategorised',purpose:'unknown',status:'review',tags:[],notes:'',source:template.source,edit_history:[]});
  await page.reload();await waitCount(2);await page.locator('#nav-all').click();await waitCount(4);
  assert.equal(await page.locator('#filter-merchant option[value="待识别商家"]').textContent(),'Unknown merchant');
  await page.locator('[data-id="ui_unknown"]').click();assert.equal(await page.locator('#detail-form [name=merchant]').inputValue(),'');
  await page.locator('#detail-form [name=notes]').fill('Keep this for a clearer photo');await page.locator('#save-detail').click();await page.locator('#receipt-dialog').waitFor({state:'hidden'});
  assert.equal(requests.updates.at(-1).changes.merchant,undefined,'Displaying an unknown merchant in English must not alter its saved reading');
  await page.locator('[data-id="ui_manual"]').click();await page.locator('#detail-form [name=date]').fill('');await page.locator('#save-detail').click();await page.locator('#receipt-dialog').waitFor({state:'hidden'});
  assert.equal(requests.updates.at(-1).changes.date,null);
  await page.locator('#export-scope').selectOption('all');await page.locator('#nav-report').click();
  assert.equal(await page.evaluate(()=>/[\u3400-\u9fff]/.test(document.body.innerText)),false,'Unknown placeholders must also be English in filters and insights');
  result.mocked_contract.unknown_merchant_display_preserves_raw_reading=true;result.mocked_contract.date_can_be_cleared=true;
  assert.deepEqual(errors,[]);result.passed=true;
  await fs.writeFile(output+'/browser-check.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
} finally {await browser.close();}
