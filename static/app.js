'use strict';

const $ = id => document.getElementById(id);
const state = {records:[],categories:[],filtered:[],selected:new Set(),view:'review',tableView:'review',detail:null,report:null,reportSignature:null,reportDirty:false,importing:false,processing:false,reportBusy:false,exportBusy:false,bulkBusy:false,loaded:false};
const categoryNames = {'超市与食品':'Groceries & food','餐饮':'Dining','家居与五金':'Home & hardware','健康与药房':'Health & pharmacy','服饰与百货':'Clothing & retail','交通与燃油':'Transport & fuel','电子与办公':'Electronics & office','其他':'Other','待分类':'Uncategorised'};
const purposeLabels = {unknown:'Not set',personal:'Personal',work:'Work'};
const statusLabels = {review:'Needs review',auto_confirmed:'Auto-confirmed',confirmed:'Reviewed by you'};
const fieldLabels = {merchant:'Merchant',date:'Transaction date',total:'Receipt total',category:'Category',currency:'Currency',tags:'Tags',notes:'Notes',purpose:'Purpose',status:'Status'};
const methodLabels = {ocr_match:'Recognised text',source_metadata:'Source information',default_assumption:'Default value',merchant_rule:'Merchant category suggestion',ai_suggestion:'AI category suggestion',ai_grounded:'AI with source evidence',user_review:'Your correction',multi_engine_consensus:'Matching model readings',single_engine_evidence:'One model reading',multi_engine_reconciliation:'Combined source evidence',printed_total_cross_checked_with_complete_item_sum:'Total checked against complete item arithmetic'};
const engineLabels = {paddle:'PaddleOCR',unlimited:'U2',oxr:'OXR'};
const decisionLabels = {accepted:'Extracted',conflict:'Conflicting readings',review:'Evidence needs review',missing:'No reliable reading'};
const qualityLabels = {complete:'Complete text output',empty:'No usable text',truncated:'Output limit reached',failed:'Recognition incomplete'};
const viewNames = {all:'All receipts',review:'Needs review',auto_confirmed:'Auto-confirmed',confirmed:'Reviewed by you',categories:'Categories',report:'Insights'};
const viewTitles = {all:'Your receipt inbox',review:'Review the exceptions',auto_confirmed:'Organised automatically',confirmed:'Reviewed by you',categories:'Everything in its place',report:'From receipts to insight'};
const filterIds = ['search','filter-merchant','filter-category','filter-purpose','filter-start','filter-end','filter-min','filter-max','filter-currency','filter-missing','filter-tag','filter-confidence'];
let toastTimer,processingTimer,blindTimer;

function node(tag,className,text) { const el=document.createElement(tag); if(className)el.className=className; if(text!==undefined)el.textContent=String(text); return el; }
function englishText(value,fallback='') { const text=String(value || ''); return /[\u3400-\u9fff]/.test(text) ? fallback : text; }
function categoryLabel(value) { return categoryNames[value] || value || 'Uncategorised'; }
function validTotal(record) { return typeof record.total==='number' && Number.isFinite(record.total); }
function amount(value) { return Number(value).toLocaleString('en-AU',{minimumFractionDigits:2,maximumFractionDigits:2}); }
function dateLabel(value) { const parts=String(value || '').split('-'); return parts.length===3 ? `${parts[2]}/${parts[1]}/${parts[0]}` : 'Date unavailable'; }
function knownMerchant(record) { return typeof record.merchant==='string' && !['','待识别商家','待确认','unknown','unknown merchant','unrecognised merchant','unrecognized merchant'].includes(record.merchant.trim().toLowerCase()); }
function merchantLabel(record) { return knownMerchant(record) ? record.merchant : 'Unknown merchant'; }
function hasMissing(record) { return !knownMerchant(record) || !record.date || !validTotal(record); }
function needsReview(record) { return !['confirmed','auto_confirmed'].includes(record.status); }
function confidenceScore(record) { return Number.isFinite(record.confidence?.score) ? Math.max(0,Math.min(100,record.confidence.score)) : null; }
function confidenceBand(record) { return record.confidence?.band || 'unassessed'; }
function engineLabel(value) { const [name,variant]=String(value || '').split(':'); return (engineLabels[name] || name || 'Unknown model')+(variant==='focus'?' · focus view':variant==='detail'?' · detail view':''); }
function supportCount(decision) { return new Set((decision.engines || (decision.evidence || []).map(e=>e.engine)).map(e=>String(e).split(':')[0]).filter(Boolean)).size; }
function imagePath(record) { const path=record.source?.preview_path || record.source?.local_path || ''; const at=path.indexOf('data/'); return at>=0 ? '/'+path.slice(at).split('/').map(encodeURIComponent).join('/') : ''; }
function safeSourceURL(value) { try { const url=new URL(value); return ['http:','https:'].includes(url.protocol)?url.href:''; } catch { return ''; } }
function valueLabel(field,value,currency) { if(value===null || value===undefined || value==='' || value==='待识别商家')return 'Unavailable'; if(field==='total')return `${currency || 'AUD'} ${amount(value)}`; if(field==='date')return dateLabel(value); if(field==='category')return categoryLabel(value); if(field==='purpose')return purposeLabels[value] || value; if(field==='status')return statusLabels[value] || value; return Array.isArray(value)?value.join(', '):String(value); }
function moneySummary(records) { const sums=new Map(); for(const r of records)if(validTotal(r)){const c=r.currency || 'UNKNOWN';sums.set(c,(sums.get(c)||0)+Math.round(r.total*100));} return sums; }
function moneyLabel(records) { const sums=moneySummary(records); return sums.size ? [...sums].map(([c,v])=>`${c==='AUD'?'A$':c+' '}${amount(v/100)}`).join(' · ') : 'No recorded amount'; }
function showToast(message,error=false) { const el=$('toast');el.textContent=message;el.className='toast'+(error?' error':'');el.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.hidden=true,error?9000:5000); }
async function api(url,body) { const response=await fetch(url,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let data;try{data=await response.json();}catch{throw new Error('The local service returned an unexpected response.');}if(!response.ok)throw new Error(englishText(data.error,'The request could not be completed. Please check the selected records and try again.'));return data; }
async function refreshBlindStatus() {
  clearTimeout(blindTimer);let complete=false;
  try{const progress=await api('/api/blind-status'),target=Number(progress.target_count)||100,count=Math.max(0,Math.min(target,Number(progress.completed)||0));complete=progress.state==='complete'&&!!progress.report_url;const current=$('blind-quality-link');
    if(complete&&progress.report_url){const url=new URL(progress.report_url,location.href);if(url.origin===location.origin){const link=node('a','quality-link',`Blind test report · ${count}/${target} ↗`);link.id='blind-quality-link';link.href=url.href;link.target='_blank';link.rel='noopener';current.replaceWith(link);}else current.textContent='Blind test complete';}
    else{const status=node('span','quality-status',`Blind test: ${count}/${target}${progress.state==='runner_failed'?' · interrupted':''}`);status.id='blind-quality-link';current.replaceWith(status);}
  }catch{const current=$('blind-quality-link');if(current&&current.tagName!=='A')current.textContent='Blind test preparing';}
  finally{if(!complete)blindTimer=setTimeout(refreshBlindStatus,15000);}
}
function fillOptions(id,values,placeholder,label=x=>x) { const select=$(id),previous=select.value;select.replaceChildren(node('option','',placeholder));select.firstElementChild.value='';for(const value of values){const option=node('option','',label(value));option.value=value;select.append(option);}if(values.includes(previous))select.value=previous; }

async function loadRecords(notify=false) {
  try {
    const data=await api('/api/receipts');state.records=data.receipts || [];state.categories=data.categories || [];state.processing=!!data.processing;state.loaded=true;refreshReportStaleness();
    $('processing-notice').hidden=!state.processing;$('import-button').disabled=state.processing || state.importing;$('camera-button').disabled=state.processing || state.importing;
    clearTimeout(processingTimer);if(state.processing)processingTimer=setTimeout(()=>loadRecords(),5000);
    const ids=new Set(state.records.map(r=>r.id));state.selected=new Set([...state.selected].filter(id=>ids.has(id)));
    fillOptions('filter-merchant',[...new Set(state.records.map(r=>r.merchant).filter(Boolean))].sort((a,b)=>a.localeCompare(b)),'All merchants',value=>merchantLabel({merchant:value}));
    fillOptions('filter-category',state.categories,'All categories',categoryLabel);fillOptions('bulk-category',state.categories,'Choose category…',categoryLabel);
    fillOptions('filter-currency',[...new Set(state.records.map(r=>r.currency || 'UNKNOWN'))].sort(),'All currencies');
    fillOptions('filter-tag',[...new Set(state.records.flatMap(r=>r.tags || []))].sort((a,b)=>a.localeCompare(b)),'All tags');
    const previous=$('edit-category').value;$('edit-category').replaceChildren(...state.categories.map(c=>{const o=node('option','',categoryLabel(c));o.value=c;return o;}));if(state.categories.includes(previous))$('edit-category').value=previous;
    const sampleCount=state.records.filter(r=>r.source?.kind==='public_sample').length;$('sample-notice').hidden=!sampleCount;$('sample-count').textContent=`${sampleCount} public samples`;
    const pending=state.records.filter(needsReview).length,auto=state.records.filter(r=>r.status==='auto_confirmed').length,manual=state.records.filter(r=>r.status==='confirmed').length;
    $('nav-total').textContent=state.records.length;$('nav-pending').textContent=pending;$('nav-auto-count').textContent=auto;$('nav-done').textContent=manual;
    $('workflow-title').textContent=auto?`${auto} receipts auto-confirmed · ${pending} need review`:pending?`${pending} receipts need review`:'Your review queue is clear';
    $('workflow-copy').textContent=auto?'The system handles strong evidence. You can override any result at any time.':pending?'Uncertain readings stay here. Confirm or correct the exceptions, then export.':'Use categories and insights to organise and export your receipts.';
    $('review-exceptions').textContent=pending?'Open review queue →':'Browse all receipts →';
    render();if(state.view==='categories')renderCategories();if(state.view==='report')renderInsights();
    if($('receipt-dialog').open){for(const control of $('detail-form').elements)control.disabled=state.processing;$('save-detail').disabled=state.processing;}
    if(notify)showToast('Receipts refreshed.');
  } catch(error) {$('table-footer-text').textContent='Unable to load receipts.';$('empty-state').hidden=false;$('empty-title').textContent='Cannot connect to your workspace';$('empty-description').textContent=error.message;$('empty-action').textContent='Try again';showToast(error.message,true);}
}

function filterRecords() {
  const term=$('search').value.trim().toLowerCase(),merchant=$('filter-merchant').value,category=$('filter-category').value,purpose=$('filter-purpose').value;
  const start=$('filter-start').value,end=$('filter-end').value,min=$('filter-min').value===''?null:Number($('filter-min').value),max=$('filter-max').value===''?null:Number($('filter-max').value);
  const currency=$('filter-currency').value,missing=$('filter-missing').value,tag=$('filter-tag').value,confidence=$('filter-confidence').value;
  const rows=state.records.filter(r=>{
    if(state.tableView==='review'&&!needsReview(r))return false;if(state.tableView==='auto_confirmed'&&r.status!=='auto_confirmed')return false;if(state.tableView==='confirmed'&&r.status!=='confirmed')return false;
    if(merchant&&r.merchant!==merchant || category&&r.category!==category || purpose&&(r.purpose||'unknown')!==purpose || currency&&(r.currency||'UNKNOWN')!==currency)return false;
    if((start||end)&&!r.date || start&&r.date<start || end&&r.date>end)return false;
    if((min!==null||max!==null)&&!validTotal(r) || min!==null&&r.total<min || max!==null&&r.total>max)return false;
    if(missing==='missing'&&!hasMissing(r) || missing==='complete'&&hasMissing(r) || tag&&!(r.tags||[]).includes(tag) || confidence&&confidenceBand(r)!==confidence)return false;
    return !term || [r.merchant,categoryLabel(r.category),r.notes,r.id,...(r.tags||[])].join(' ').toLowerCase().includes(term);
  });
  const sort=$('sort').value;
  return rows.sort((a,b)=>{if(sort==='merchant')return merchantLabel(a).localeCompare(merchantLabel(b))||a.id.localeCompare(b.id);if(sort==='confidence')return (confidenceScore(a)??-1)-(confidenceScore(b)??-1);if(sort==='amount-desc'){if(!validTotal(a)&&validTotal(b))return 1;if(validTotal(a)&&!validTotal(b))return -1;if(a.currency!==b.currency)return (a.currency||'').localeCompare(b.currency||'');return (b.total||0)-(a.total||0);}if(!a.date&&b.date)return 1;if(a.date&&!b.date)return -1;return sort==='date-asc'?(a.date||'').localeCompare(b.date||''):(b.date||'').localeCompare(a.date||'');});
}
function scopeRecords() { const scope=$('export-scope').value;return scope==='all'?state.records:scope==='selected'?state.records.filter(r=>state.selected.has(r.id)):state.filtered; }
function scopeLabel() { const scope=$('export-scope').value;return scope==='all'?'All receipts':scope==='selected'?'Selected receipts':`Current results · ${viewNames[state.tableView]}`; }
function updateSelection() {
  const count=state.filtered.filter(r=>state.selected.has(r.id)).length,all=$('select-all');all.checked=count>0&&count===state.filtered.length;all.indeterminate=count>0&&count<state.filtered.length;all.disabled=!state.filtered.length;
  $('selection-text').textContent=state.selected.size?`${state.selected.size} selected · ${count} in this view`:'Select current results';
  $('bulk-bar').hidden=!state.selected.size;$('bulk-count').textContent=`${state.selected.size} selected`;$('bulk-apply').disabled=state.bulkBusy || state.processing || !$('bulk-category').value;
  const n=scopeRecords().length;$('export-count').textContent=`${n} receipt${n===1?'':'s'}`;$('export-button').disabled=!n||state.exportBusy;$('generate-report').disabled=!n||state.reportBusy;
}
function confidenceBadge(record) { const score=confidenceScore(record),band=confidenceBand(record),badge=node('span','confidence-badge '+band,score===null?'Not assessed':`${score}/100 evidence`);badge.title='Evidence index, not a probability of correctness. Open the receipt for supporting reasons.';return badge; }
function render() {
  state.filtered=filterRecords();const rows=state.filtered,totals=moneySummary(rows),known=rows.filter(validTotal).length;
  $('stat-count').textContent=rows.length;$('stat-count-note').textContent=`${state.records.length} total · ${new Set(rows.map(r=>r.merchant)).size} merchants`;
  $('stat-amount').textContent=totals.size>1?`${totals.size} currencies`:totals.size?moneyLabel(rows):'—';$('stat-amount').title=moneyLabel(rows);$('stat-amount-note').textContent=totals.size>1?'Each currency is kept separate':`${known}/${rows.length} amounts recorded`;
  $('stat-review').textContent=rows.filter(needsReview).length;$('stat-missing').textContent=rows.filter(hasMissing).length;$('stat-missing-note').textContent=`Missing: ${rows.filter(r=>!knownMerchant(r)).length} merchant · ${rows.filter(r=>!r.date).length} date · ${rows.filter(r=>!validTotal(r)).length} total`;
  $('result-count').textContent=rows.length;$('table-footer-text').textContent=`Showing ${rows.length} of ${state.records.length} receipts`;
  const fragment=document.createDocumentFragment();
  for(const record of rows){
    const row=node('tr','receipt-row'+(state.selected.has(record.id)?' selected':''));row.dataset.id=record.id;row.tabIndex=0;row.setAttribute('aria-label',`Open ${merchantLabel(record)} receipt ${record.id}`);
    const checkCell=node('td','check-cell'),check=node('input');check.type='checkbox';check.checked=state.selected.has(record.id);check.setAttribute('aria-label',`Select ${record.id}`);check.addEventListener('click',e=>e.stopPropagation());check.addEventListener('change',()=>{check.checked?state.selected.add(record.id):state.selected.delete(record.id);row.classList.toggle('selected',check.checked);updateSelection();});checkCell.append(check);row.append(checkCell);
    const cell=node('td'),wrap=node('div','merchant-cell'),image=node('img','receipt-thumbnail');image.src=imagePath(record);image.alt='';image.loading=fragment.childElementCount<12?'eager':'lazy';image.decoding='async';image.addEventListener('error',()=>image.style.opacity='.15',{once:true});const copy=node('div','merchant-copy');copy.append(node('strong','',merchantLabel(record)),node('small','',`${dateLabel(record.date)} · ${record.source?.kind==='public_sample'?'Public sample':'Photo import'}`));wrap.append(image,copy);cell.append(wrap);row.append(cell,node('td',record.date?'':'unknown',dateLabel(record.date)));
    const category=node('td');category.append(node('span','category-name',categoryLabel(record.category)));if(record.tags?.length){const tags=node('div','tag-list');for(const tag of record.tags.slice(0,2)){const el=node('span','tag',tag);el.title=tag;tags.append(el);}category.append(tags);}row.append(category,node('td',!record.purpose||record.purpose==='unknown'?'unknown':'',purposeLabels[record.purpose]||'Not set'));
    const status=node('td','status-cell');status.append(node('span','status-badge '+(record.status||'review'),statusLabels[record.status]||'Needs review'),confidenceBadge(record));row.append(status);
    const money=node('td','amount-col'+(validTotal(record)?'':' unknown'),validTotal(record)?amount(record.total):'Not extracted');if(validTotal(record))money.append(node('small','',record.currency||'Unknown currency'));row.append(money,node('td','arrow-cell','›'));
    row.addEventListener('click',()=>openDetail(record.id));row.addEventListener('keydown',e=>{if(e.target===row&&['Enter',' '].includes(e.key)){e.preventDefault();openDetail(record.id);}});fragment.append(row);
  }
  $('receipt-rows').replaceChildren(fragment);$('empty-state').hidden=!!rows.length;
  const clearQueue=state.tableView==='review'&&!state.records.some(needsReview)&&state.records.length>0;
  $('empty-title').textContent=clearQueue?'You are all caught up':state.records.length?'No matching receipts':'Your first receipt starts here';
  $('empty-description').textContent=clearQueue?'No receipts currently need manual review. Browse your organised receipts or open Insights.':state.records.length?'Try a different merchant, category, date or amount range.':'Import a photo to extract, organise and export its details.';
  $('empty-action').textContent=clearQueue?'View all receipts':state.records.length?'Reset filters':'Import photos';updateSelection();
}
function clearFilters() { for(const id of filterIds)$(id).value='';render(); }
function setView(view) {
  state.view=view;if(!['categories','report'].includes(view))state.tableView=view;
  if(view==='categories')$('export-scope').value='all';
  $('workspace-view').hidden=['categories','report'].includes(view);$('categories-view').hidden=view!=='categories';$('report-view').hidden=view!=='report';
  $('page-title').textContent=viewTitles[view];$('breadcrumb').textContent=viewNames[view];
  $('page-subtitle').textContent=view==='categories'?'Group receipts, correct categories and export exactly what you need.':view==='report'?'Understand the records in your selected scope, with every total traceable.':view==='auto_confirmed'?'Strong evidence, filed for you. Open any receipt to correct it.':'Your receipts, sorted. Your attention, only where it is needed.';
  for(const el of document.querySelectorAll('.nav-item'))el.classList.toggle('active',el.dataset.view===view);
  if(view==='categories')renderCategories();else if(view==='report'){renderInsights();if(!state.report&&!state.reportBusy)loadSampleReport();}else render();
  updateSelection();
}
function showCategory(category) { setView('all');for(const id of filterIds)$(id).value='';$('filter-category').value=category;$('export-scope').value='filtered';render(); }
function renderCategories() {
  const grid=$('category-grid');grid.replaceChildren();
  const values=[...new Set([...state.categories,...state.records.map(r=>r.category || 'Uncategorised')])];
  for(const category of values){const rows=state.records.filter(r=>(r.category||'Uncategorised')===category),card=node('button','category-card');card.type='button';card.dataset.category=category;card.append(node('span','category-card-symbol','▦'),node('h3','',categoryLabel(category)),node('strong','',rows.length),node('small','',`receipt${rows.length===1?'':'s'}`),node('p','category-card-total',moneyLabel(rows)),node('span','category-card-link',rows.length?'Open receipts →':'No receipts yet'));card.disabled=!rows.length;card.addEventListener('click',()=>showCategory(category));grid.append(card);}
}
async function applyBulkCategory() {
  const category=$('bulk-category').value,ids=[...state.selected];if(!category||!ids.length)return;
  state.bulkBusy=true;$('bulk-apply').textContent='Applying…';updateSelection();
  try{const result=await api('/api/bulk-update',{ids,changes:{category}});state.reportDirty=true;await loadRecords();showToast(`Category updated for ${result.count??ids.length} receipts. Each change is saved in its history.`);}catch(error){showToast(error.message,true);}finally{state.bulkBusy=false;$('bulk-apply').textContent='Apply category';updateSelection();}
}

function renderConfidence(record) {
  const panel=$('detail-confidence');panel.replaceChildren();const score=confidenceScore(record),heading=node('div','confidence-heading');
  heading.append(node('strong','',statusLabels[record.status]||'Needs review'),node('span','confidence-value',score===null?'Not assessed':`${score}/100`));panel.append(heading);
  if(score!==null){const track=node('div','confidence-track'),fill=node('span','confidence-fill '+confidenceBand(record));fill.style.width=`${score}%`;track.append(fill);panel.append(track);}
  panel.append(node('p','',record.status==='auto_confirmed'?'The system accepted the core fields using its evidence policy. You can still override any field.':record.status==='confirmed'?'You have reviewed or corrected this receipt. Its original extraction is retained.':'The evidence did not meet the automatic confirmation policy. Check the core fields against the photo.'));
  const fields=record.confidence?.fields||{},fieldCards=node('div','confidence-fields');
  for(const key of ['merchant','date','total']){const field=fields[key],input=$('detail-form').elements.namedItem(key);input.closest('label').classList.toggle('field-needs-review',record.status==='review'&&field?.ready===false);if(!field)continue;const card=node('div','confidence-field '+(field.ready?'ready':'needs-check'));card.append(node('strong','',key==='date'?'Date':key==='total'?'Total':'Merchant'),node('span','',`${field.score}/100`),node('small','',`${field.independent_models?.length||0} supporting models`));if(!field.ready)card.append(node('small','',record.status==='confirmed'?'Original evidence':'Needs checking'));fieldCards.append(card);}if(fieldCards.childElementCount)panel.append(fieldCards);
  const reasons=record.confidence?.reasons || [];const list=node('ul','confidence-reasons');
  for(const reason of reasons){const text=englishText(typeof reason==='string'?reason:reason.message||reason.description||reason.code);if(text)list.append(node('li','',text));}if(list.childElementCount)panel.append(list);
  panel.append(node('small','','Evidence index, not a calibrated probability or a guarantee of accuracy. Purpose and category can be corrected separately.'));
}
function renderHistory(record) {
  const container=$('detail-history');container.replaceChildren();
  const extraction=record.extracted_fields || record.original_extraction || record.reconciliation || {};
  const original=node('div','history-original');original.append(node('strong','','Original extraction'));
  for(const key of ['merchant','date','total']){const value=extraction[key]??extraction.fields?.[key]?.value??record.reconciliation?.fields?.[key]?.value;if(value!==undefined)original.append(node('p','',`${fieldLabels[key]}: ${valueLabel(key,value,record.currency)}`));}container.append(original);
  const history=record.edit_history || [];
  if(!history.length)container.append(node('p','evidence-note','No manual changes yet.'));
  for(const entry of [...history].reverse()){
    const card=node('div','history-entry');const at=entry.at || entry.created_at;card.append(node('strong','',at?new Date(at).toLocaleString('en-AU',{hour12:false}):'Manual change'));
    for(const [key,value] of Object.entries(entry.after || entry.changes || {}))card.append(node('p','',`${fieldLabels[key]||key}: ${valueLabel(key,entry.before?.[key],record.currency)} → ${valueLabel(key,value,record.currency)}`));container.append(card);
  }
}
function appendQuotes(container,evidence) { const seen=new Set();for(const item of Array.isArray(evidence)?evidence:[]){const quote=String(item.evidence||'').trim(),key=`${item.engine||''}:${quote}`;if(!quote||seen.has(key))continue;seen.add(key);const block=node('blockquote','evidence-quote');block.append(node('span','quote-source',engineLabel(item.engine)),node('p','',quote));if(item.flags?.includes('source_output_capped'))block.append(node('small','evidence-caution','This source hit its output limit; only the returned fragment is shown.'));container.append(block);}return seen.size; }
function evidenceReason(decision) { const text=englishText(decision.review_reason);if(text)return text;if(decision.review_source==='detail_with_full_arithmetic')return 'An actual TOTAL reading was checked against the complete item quantities, discounts and subtotal from another model.';if(decision.review_source==='detail_consensus')return 'Independent models agreed when the original image was re-read in a focused view.';if(decision.logo_disambiguation)return 'The receipt logo provides additional evidence for this merchant spelling.';if(decision.invoice_balance_checks?.length)return 'The unpaid account balance provides a separate printed check for the total.';return ''; }
function renderFieldEvidence(record) {
  const container=$('detail-evidence');container.replaceChildren();const fields=record.field_evidence||{},decisions=record.reconciliation?.fields||{};$('evidence-score-note').hidden=!record.ocr_engines;
  const keys=[...new Set([...['merchant','date','total'],...Object.keys(fields)])];
  for(const key of keys){const value=fields[key]||{},decision=Array.isArray(value.candidates)?value:decisions[key],section=node('section','evidence-item'),heading=node('div','evidence-heading');heading.append(node('strong','',fieldLabels[key]||key),node('small','',methodLabels[value.method]||'Recorded evidence'));section.append(heading);
    if(['merchant','date','total'].includes(key))section.append(node('p','current-field-value',`Current record: ${valueLabel(key,record[key],record.currency)}`));
    if(decision){const meta=node('div','evidence-meta'),count=supportCount(decision);meta.append(node('span','decision-badge '+(decision.status==='accepted'?'accepted':'needs-review'),decisionLabels[decision.status]||'Needs review'));if(count)meta.append(node('span','support-count',`${count} independent model${count===1?'':'s'} support${count===1?'s':''} this reading`));if(Number.isFinite(decision.score))meta.append(node('span','ranking-score',`Candidate rank ${decision.score} · not accuracy`));section.append(meta);
      if(value.method==='user_review')section.append(node('p','evidence-note','You changed the current value. The evidence below describes the original model readings.'));
      if(decision.disagreement)section.append(node('p','evidence-caution','Different readings were observed. The original candidates remain available for comparison.'));
      const reason=evidenceReason(decision);if(reason)section.append(node('p','evidence-note',reason));
      if(decision.arithmetic_checks?.length){const proof=node('details','candidate-comparison');proof.append(node('summary','','Item quantities and arithmetic check'));for(const check of decision.arithmetic_checks){proof.append(node('p','',`${engineLabel(String(check.engine).split(':')[0])}: ${check.item_count} items, calculated sum ${amount(check.value)}`));const lines=[...(check.items||[]),...(check.discounts||[])].map(i=>i.evidence).filter(Boolean);if(check.count_evidence)lines.push(check.count_evidence);proof.append(node('pre','',lines.join('\n')));}section.append(proof);}
      if(!appendQuotes(section,decision.evidence))section.append(node('p','',englishText(value.text,'No reliable source quote is available for this field.')));
      const candidates=decision.candidates||[];if(candidates.length>1){const comparison=node('details','candidate-comparison');comparison.open=decision.status==='conflict';comparison.append(node('summary','',`Compare ${candidates.length} readings`));for(const candidate of candidates){const card=node('section','candidate-card'),headline=node('div','candidate-headline');headline.append(node('strong','',valueLabel(key,candidate.value,record.currency)),node('span','',`${supportCount(candidate)} model(s)`));card.append(headline);appendQuotes(card,candidate.evidence);comparison.append(card);}section.append(comparison);}
    }else section.append(node('p','',englishText(value.text,value.method==='merchant_rule'?'Suggested from the merchant type; mixed purchases may need another category.':value.method==='user_review'?'Updated by you.':'No additional explanation is available.')));container.append(section);
  }
}
function renderEngineEvidence(record) {
  const entries=Object.entries(record.ocr_engines||{});$('engine-evidence-section').hidden=!entries.length;$('legacy-ocr-section').hidden=!!entries.length;$('detail-ocr').textContent=record.ocr_text||'No recognised text.';const container=$('detail-engines');container.replaceChildren();if(!entries.length)return;
  const expected=record.ensemble_quality?.expected_engines||entries.length,complete=entries.filter(([,e])=>e.recognition_complete).length;$('engine-overview').textContent=`${complete}/${expected} models have complete text output. Alternate views from one model count once.`;
  for(const [name,info] of entries){const section=node('details','ocr-engine'),summary=node('summary','ocr-engine-summary');summary.append(node('strong','',engineLabel(name)),node('span','engine-status '+(info.recognition_complete?'complete':'partial'),qualityLabels[info.status]||'Needs review'));section.append(summary);
    for(const variant of info.variants||[]){const quality=variant.quality||{},view=node('details','ocr-view'),title=node('summary','');title.append(node('span','',variant.variant==='focus'?'Focus view':'Full image'),node('small','',qualityLabels[quality.status]||'Unknown output quality'));view.append(title);if(!quality.has_text)view.append(node('p','evidence-caution','No usable text was returned by this attempt.'));else{if(quality.capped)view.append(node('p','evidence-caution','This is an incomplete text fragment; the output limit was reached.'));view.append(node('pre','engine-transcript',variant.evidence_text||variant.normalized?.text||''));}section.append(view);}if(info.errors?.length)section.append(node('p','evidence-caution','Some attempts were excluded because recognition or cache validation failed. Valid source evidence is retained.'));container.append(section);
  }
}
function openDetail(id) {
  const record=state.records.find(r=>r.id===id);if(!record)return;state.detail=id;$('detail-title').textContent=merchantLabel(record);$('receipt-image').src=imagePath(record);$('original-link').href=imagePath(record);
  const form=$('detail-form');for(const key of ['merchant','date','currency','category','purpose','notes'])form.elements.namedItem(key).value=record[key]||(key==='purpose'?'unknown':'');if(!knownMerchant(record))form.elements.namedItem('merchant').value='';form.elements.namedItem('total').value=validTotal(record)?record.total:'';form.elements.namedItem('tags').value=(record.tags||[]).join(', ');form.elements.namedItem('confirmed').checked=record.status==='confirmed';
  const warnings=[...new Set([...(record.workflow_warnings||[]),...(record.warnings||[])].map(w=>englishText(w)).filter(Boolean))];$('detail-warnings').replaceChildren(...warnings.map(w=>node('p','',w)));$('detail-warnings').hidden=!warnings.length;renderConfidence(record);renderHistory(record);renderFieldEvidence(record);renderEngineEvidence(record);
  const source=safeSourceURL(record.source?.page_url||record.source?.source_page_url||record.source?.source_url),link=$('detail-source');if(source){link.href=source;link.textContent=new URL(source).hostname+' · Open original source ↗';}else{link.removeAttribute('href');link.textContent=record.source?.original_name||'Locally imported photo';}
  $('detail-license').textContent=englishText(record.source?.license||record.source?.licence_status||record.source?.image_license,'Source terms are retained in the exported record.');$('detail-id').textContent=record.id;$('save-hint').textContent=state.processing?'Editing resumes after processing.':'Your changes preserve the original extraction.';for(const control of form.elements)control.disabled=state.processing;$('save-detail').disabled=state.processing;$('receipt-dialog').showModal();
}
async function saveDetail(event) {
  event.preventDefault();if(state.processing)return showToast('Please wait for the current processing job.');const original=state.records.find(r=>r.id===state.detail);if(!original)return;
  const form=$('detail-form'),get=key=>form.elements.namedItem(key).value.trim();const values={merchant:get('merchant'),date:get('date')||null,total:get('total')===''?null:Number(get('total')),currency:get('currency'),category:get('category'),purpose:get('purpose'),tags:get('tags').split(/[,，]/).map(s=>s.trim()).filter(Boolean),notes:get('notes')};
  const changed=Object.fromEntries(Object.entries(values).filter(([key,value])=>JSON.stringify(value)!==JSON.stringify(key==='merchant'&&!knownMerchant(original)?'':original[key]??(key==='date'||key==='total'?null:key==='tags'?[]:''))));const checked=form.elements.namedItem('confirmed').checked,coreChanged=['merchant','date','total','currency'].some(key=>Object.hasOwn(changed,key));
  if(checked!== (original.status==='confirmed'))changed.status=checked?'confirmed':'review';
  if(coreChanged&&!hasMissing(values))changed.status='confirmed';
  if(changed.status==='confirmed'&&hasMissing(values)){$('save-hint').textContent='Complete the merchant, date and total before confirming.';return;}
  if(!Object.keys(changed).length){$('receipt-dialog').close();return showToast('No changes to save.');}
  $('save-detail').disabled=true;$('save-hint').textContent='Saving…';
  try{await api('/api/update',{id:state.detail,changes:changed});state.reportDirty=true;$('receipt-dialog').close();await loadRecords();showToast(coreChanged?'Your correction is saved. The original reading remains in history.':'Changes saved.');}catch(error){$('save-hint').textContent=error.message;showToast(error.message,true);}finally{$('save-detail').disabled=false;}
}
function base64File(file) { return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('Cannot read '+file.name));reader.readAsDataURL(file);}); }
async function importFiles(list) {
  const files=[...list];if(!files.length)return;if(state.processing||state.importing)return showToast('Please wait for the current import to finish.');if(files.length>40)return showToast('Import up to 40 photos at a time.',true);const invalid=files.find(f=>!/\.(jpe?g|png|webp|heic|heif|tiff?)$/i.test(f.name));if(invalid)return showToast('Unsupported image format: '+invalid.name,true);const big=files.find(f=>f.size>24*1024*1024);if(big)return showToast('Each image must be under 24 MB: '+big.name,true);if(files.reduce((n,f)=>n+f.size,0)>105*1024*1024)return showToast('Please split this import into batches below 105 MB.',true);
  state.importing=true;$('import-button').disabled=true;$('camera-button').disabled=true;$('import-progress').hidden=false;$('progress-title').textContent='Importing photos';$('progress-detail').textContent='Photos stay on this computer while each receipt is recognised and organised.';$('progress-errors').replaceChildren();$('progress-bar').value=0;$('progress-count').textContent=`0 / ${files.length}`;
  try{const images=[];for(const file of files)images.push({name:file.name,data:await base64File(file)});const job=await api('/api/import',{images});while(true){const p=await api('/api/jobs/'+job.job_id);$('progress-title').textContent=p.state==='done'?'Import complete':'Recognising and organising…';$('progress-count').textContent=`${p.done} / ${p.total}`;$('progress-bar').value=p.done/p.total*100;$('progress-detail').textContent=`${p.imported} imported · ${p.duplicates} duplicate files skipped · ${p.errors.length} unsuccessful`;$('progress-errors').replaceChildren(...p.errors.map(e=>node('li','',`${e.name}: ${englishText(e.error,'Recognition did not complete; the original photo was retained.')}`)));if(p.state==='done'){state.reportDirty=true;await loadRecords();showToast(`Imported ${p.imported} receipts; ${p.duplicates} duplicates skipped.`);break;}await new Promise(r=>setTimeout(r,1500));}}catch(error){$('progress-title').textContent='Import interrupted';$('progress-detail').textContent=error.message;showToast(error.message,true);}finally{state.importing=false;$('import-button').disabled=state.processing;$('camera-button').disabled=state.processing;$('file-input').value='';$('camera-input').value='';}
}
async function exportRecords() {
  const records=scopeRecords(),format=$('export-format').value;if(!records.length)return showToast('There are no receipts in this scope.');state.exportBusy=true;$('export-button').textContent='Exporting…';$('export-result').hidden=true;updateSelection();
  try{const result=await api('/api/export',{ids:records.map(r=>r.id),format});const a=node('a');a.href=result.url;a.download='';document.body.append(a);a.click();a.remove();const feedback=$('export-result'),link=node('a','text-button','Download again ↗');link.href=result.url;link.download='';feedback.replaceChildren(node('span','',`${result.count} receipts exported as ${format.toUpperCase()} · ${scopeLabel()}`),link);feedback.hidden=false;showToast(`${result.count} receipts exported as ${format.toUpperCase()}.`);}catch(error){showToast('Export failed: '+error.message,true);}finally{state.exportBusy=false;$('export-button').textContent='Export ↓';updateSelection();}
}

function groupRecords(records,key) { const groups=new Map();for(const r of records){const value=key==='month'?(r.date?.slice(0,7)||'No date'):key==='merchant'?merchantLabel(r):r[key]||(key==='category'?'Uncategorised':'Unknown merchant');if(!groups.has(value))groups.set(value,[]);groups.get(value).push(r);}return [...groups].sort((a,b)=>key==='month'?b[0].localeCompare(a[0]):b[1].length-a[1].length); }
function reportMatchesScope(report,records) { if(!report)return false;const ids=new Set(report.record_ids||[]);return ids.size===records.length&&records.every(r=>ids.has(r.id)); }
function recordsSignature(records) { return JSON.stringify([...records].sort((a,b)=>a.id.localeCompare(b.id)).map(r=>({id:r.id,merchant:r.merchant,date:r.date,total:r.total,currency:r.currency,category:r.category,purpose:r.purpose,tags:r.tags||[],notes:r.notes||'',status:r.status,confidence:r.confidence?.score,confidence_band:r.confidence?.band,auto_confirmable:r.confidence?.auto_confirmable,updated_at:r.updated_at||null}))); }
function signatureForReport(report,records=state.records) { const ids=new Set(report?.record_ids||[]),matching=records.filter(r=>ids.has(r.id));return matching.length===ids.size?recordsSignature(matching):null; }
function refreshReportStaleness() { if(!state.report)return;state.reportDirty=!!state.report.stale || (state.reportSignature!==null&&signatureForReport(state.report)!==state.reportSignature); }
function makeAction(title,description,label,callback) {const card=node('div','insight-action');const copy=node('div');copy.append(node('strong','',title),node('p','',description));const button=node('button','text-button',label);button.addEventListener('click',callback);card.append(copy,button);return card;}
function renderInsights() {
  const records=scopeRecords(),container=$('report-body');container.replaceChildren();const count=records.length,known=records.filter(validTotal).length,auto=records.filter(r=>r.status==='auto_confirmed').length,review=records.filter(needsReview).length,manual=records.filter(r=>r.status==='confirmed').length;
  $('insight-scope-label').textContent=`${scopeLabel()} · ${count} receipts`;$('report-title').textContent='Your receipts at a glance';$('report-meta').textContent='Live totals from the selected records. Refunds retain their negative amounts.';
  $('report-engine').textContent=state.reportBusy?'Generating AI insight…':'Live overview';for(const id of ['report-download','report-read','report-pdf'])$(id).hidden=true;
  if(!count){container.append(node('div','empty-state'));const empty=container.firstElementChild;empty.append(node('h3','','No receipts in this scope'),node('p','','Choose all receipts, change your filters or select records to analyse.'));return;}
  const facts=node('div','report-facts');for(const [title,value,note] of [['Recorded total',moneyLabel(records),`${known}/${count} amounts available · currencies kept separate`],['Ready to use',`${auto+manual} of ${count}`,`${auto} auto-confirmed · ${manual} reviewed by you`],['Needs review',String(review),'Only uncertain extraction goes to manual review'],['Purpose not set',String(records.filter(r=>!r.purpose||r.purpose==='unknown').length),'Work or personal purpose needs your context']]){const card=node('div','report-fact');card.append(node('span','',title),node('strong','',value),node('small','',note));facts.append(card);}container.append(facts);
  const report=state.report,matches=reportMatchesScope(report,records),stale=state.reportDirty||report?.stale||records.some(r=>matches&&r.updated_at&&report?.created_at&&new Date(r.updated_at)>new Date(report.created_at));
  const ai=node('section','insight-ai'),aiHeader=node('div','insight-ai-heading');aiHeader.append(node('h3','','AI organisation insight'));
  const generate=node('button','button secondary',state.reportBusy?'Generating…':matches&&report?.ai_text?'Refresh AI insight':'Generate AI insight');generate.disabled=state.reportBusy;generate.addEventListener('click',generateReport);aiHeader.append(generate);ai.append(aiHeader);
  const aiText=matches&&!stale?englishText(report?.ai_text):'';
  if(state.reportBusy)ai.append(node('p','report-prose','Analysing the selected records. Your exact totals remain visible above.'));
  else if(matches&&stale){ai.append(node('p','report-warning','This insight is out of date. Receipt records changed after its snapshot. Generate a new insight before sharing it.'),node('p','evidence-note','The figures above are live. Previous AI commentary and report downloads are hidden until refreshed.'));$('report-engine').textContent='Update needed';}
  else if(aiText){ai.append(node('div','report-prose',aiText));$('report-engine').textContent='AI insight available';const created=report.created_at?new Date(report.created_at).toLocaleString('en-AU',{hour12:false}):'';ai.append(node('small','evidence-note',`Generated ${created}${stale?' · Records changed; refresh this insight.':''}`));}
  else if(matches&&(report?.ai_status==='unavailable'||report?.ai_unavailable_reason)){ai.append(node('p','report-warning','AI commentary is unavailable for this run. Your calculated statistics and exports are still ready.'),node('p','evidence-note',englishText(report.ai_unavailable_reason,'You can retry generation at any time.')));const narrative=englishText(report.narrative);if(narrative)ai.append(node('p','report-prose',narrative));}
  else ai.append(node('p','evidence-note','Generate a short explanation and suggested next steps for exactly this scope. The calculations below are ready now.'));
  container.append(ai);
  if(matches&&!stale&&!state.reportBusy){for(const [id,url] of [['report-download',report.downloads?.json||report.download_url],['report-read',report.downloads?.html],['report-pdf',report.downloads?.pdf]])if(url){$(id).hidden=false;$(id).href=url;}}
  const categories=groupRecords(records,'category'),categorySection=node('section','report-section');categorySection.append(node('h3','','Category breakdown'),node('p','section-caption','Open a category to inspect its receipts or export that group.'));
  const bars=node('div','category-bars'),max=Math.max(...categories.map(([,r])=>r.length));for(const [category,items] of categories){const row=node('button','bar-row'),label=node('span','',categoryLabel(category)),track=node('span','bar-track'),fill=node('span','bar-fill');row.type='button';row.setAttribute('aria-label',`Open ${categoryLabel(category)} receipts`);fill.style.width=`${items.length/max*100}%`;track.append(fill);const value=node('span','bar-value',`${items.length} · ${moneyLabel(items)}`);row.append(label,track,value);row.addEventListener('click',()=>showCategory(category));bars.append(row);}categorySection.append(bars);container.append(categorySection);
  const tables=node('div','insight-tables');for(const [title,key] of [['Top merchants','merchant'],['Receipt dates by month','month']]){const section=node('section','report-section');section.append(node('h3','',title));const table=node('table','insight-table'),head=node('thead'),tr=node('tr');for(const name of [key==='month'?'Month':'Merchant','Receipts','Recorded total'])tr.append(node('th','',name));head.append(tr);table.append(head);const body=node('tbody');for(const [name,items] of groupRecords(records,key).slice(0,8)){const row=node('tr');row.append(node('td','',name),node('td','',items.length),node('td','',moneyLabel(items)));body.append(row);}table.append(body);section.append(table);tables.append(section);}container.append(tables);
  const actions=node('section','report-section');actions.append(node('h3','','What to do next'));if(review)actions.append(makeAction(`${review} receipts need review`,'Check uncertain fields against their original photos.','Review receipts →',()=>setView('review')));
  const unknownPurpose=records.filter(r=>!r.purpose||r.purpose==='unknown').length;if(unknownPurpose)actions.append(makeAction(`${unknownPurpose} purposes not set`,'Add work or personal context when it is useful to your filing.','Filter these receipts →',()=>{setView('all');clearFilters();$('filter-purpose').value='unknown';render();}));
  actions.append(makeAction('Export this scope',`${count} receipts · Excel, PDF with originals, CSV or JSON. Use the scope control below to change the selection.`,'Export current format ↓',exportRecords));container.append(actions);
  const limits=node('div','report-limitations');if(records.some(r=>r.source?.kind==='public_sample'))limits.append(node('p','','Public samples come from different people and periods. These charts describe this test collection, not personal spending habits.'));limits.append(node('p','','Evidence confidence and categorisation are separate. Every field remains editable, and original images and correction history are retained.'));container.append(limits);
}
async function loadSampleReport() {const recordsAtRequest=[...state.records];try{const report=await api('/api/sample-report');if(report.summary&&!state.report&&!state.reportBusy){state.report=report;state.reportSignature=signatureForReport(report,recordsAtRequest);refreshReportStaleness();if(state.view==='report')renderInsights();}}catch{/* Live statistics remain usable if a saved report is absent. */}}
async function generateReport() {
  const records=[...scopeRecords()];if(!records.length)return showToast('No receipts in this scope.');if(state.reportBusy)return;const requestedSignature=recordsSignature(records);state.reportBusy=true;$('generate-report').textContent='Generating…';setView('report');updateSelection();
  try{const report=await api('/api/report',{ids:records.map(r=>r.id)});state.report=report;state.reportSignature=requestedSignature;refreshReportStaleness();renderInsights();showToast(state.reportDirty?'Receipt records changed during generation. Generate a fresh insight.':report.ai_text?`AI insight generated for ${records.length} receipts.`:`Statistics ready for ${records.length} receipts. AI commentary was unavailable.`);}catch(error){showToast('Report generation failed: '+error.message,true);state.report={record_ids:records.map(r=>r.id),ai_status:'unavailable',ai_unavailable_reason:error.message};state.reportSignature=requestedSignature;refreshReportStaleness();}finally{state.reportBusy=false;$('generate-report').textContent='✧ Generate AI insight';updateSelection();if(state.view==='report')renderInsights();}
}

for(const id of filterIds)$(id).addEventListener(['search','filter-min','filter-max'].includes(id)?'input':'change',render);
$('sort').addEventListener('change',render);$('clear-filters').addEventListener('click',clearFilters);$('refresh').addEventListener('click',()=>loadRecords(true));
$('advanced-toggle').addEventListener('click',()=>{const panel=$('advanced-filters');panel.hidden=!panel.hidden;$('advanced-toggle').setAttribute('aria-expanded',String(!panel.hidden));$('advanced-toggle').lastElementChild.textContent=panel.hidden?'＋':'−';});
for(const el of document.querySelectorAll('.nav-item'))el.addEventListener('click',()=>setView(el.dataset.view));
$('review-exceptions').addEventListener('click',()=>setView(state.records.some(needsReview)?'review':'all'));$('category-show-all').addEventListener('click',()=>{setView('all');clearFilters();});
$('select-all').addEventListener('change',()=>{for(const r of state.filtered)$('select-all').checked?state.selected.add(r.id):state.selected.delete(r.id);render();});
$('bulk-category').addEventListener('change',updateSelection);$('bulk-apply').addEventListener('click',applyBulkCategory);$('clear-selection').addEventListener('click',()=>{state.selected.clear();render();});
$('export-scope').addEventListener('change',()=>{updateSelection();if(state.view==='report')renderInsights();});$('export-button').addEventListener('click',exportRecords);$('generate-report').addEventListener('click',generateReport);
$('detail-form').addEventListener('submit',saveDetail);for(const id of ['close-detail','cancel-detail'])$(id).addEventListener('click',()=>$('receipt-dialog').close());
$('receipt-dialog').addEventListener('click',e=>{if(e.target===$('receipt-dialog')){const rect=e.target.getBoundingClientRect();if(e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom)e.target.close();}});
$('import-button').addEventListener('click',()=>$('file-input').click());$('camera-button').addEventListener('click',()=>$('camera-input').click());$('file-input').addEventListener('change',e=>importFiles(e.target.files));$('camera-input').addEventListener('change',e=>importFiles(e.target.files));
$('empty-action').addEventListener('click',()=>{const action=$('empty-action').textContent;if(action==='Try again')loadRecords();else if(action==='View all receipts'){setView('all');clearFilters();}else if(state.records.length)clearFilters();else $('file-input').click();});
const drop=$('drop-zone');drop.addEventListener('click',()=>$('file-input').click());drop.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();$('file-input').click();}});for(const name of ['dragenter','dragover'])drop.addEventListener(name,e=>{e.preventDefault();drop.classList.add('dragover');});for(const name of ['dragleave','drop'])drop.addEventListener(name,e=>{e.preventDefault();drop.classList.remove('dragover');});drop.addEventListener('drop',e=>importFiles(e.dataTransfer.files));window.addEventListener('dragover',e=>e.preventDefault());window.addEventListener('drop',e=>{if(!drop.contains(e.target))e.preventDefault();});
loadRecords();
refreshBlindStatus();
