(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.ReceiptWorkflow=api;})(typeof window==='object'?window:this,function(){
  'use strict';
  const core=['merchant','date','total'];
  const unknown=new Set(['','unknown','unknown merchant','unrecognised merchant','unrecognized merchant','待识别商家','待确认']);
  function valid(record,field){if(field==='merchant')return typeof record.merchant==='string'&&!unknown.has(record.merchant.trim().toLowerCase());if(field==='date'){if(!/^\d{4}-\d{2}-\d{2}$/.test(record.date||''))return false;const [y,m,d]=record.date.split('-').map(Number),date=new Date(Date.UTC(y,m-1,d));return date.getUTCFullYear()===y&&date.getUTCMonth()===m-1&&date.getUTCDate()===d;}return typeof record.total==='number'&&Number.isFinite(record.total);}
  function attentionFields(record){if(['confirmed','auto_confirmed'].includes(record.status))return [];return core.filter(field=>!valid(record,field)||record.confidence?.fields?.[field]?.ready===false||record.reconciliation?.fields?.[field]?.disagreement);}
  function fieldReason(record,field){
    if(!valid(record,field))return 'Not extracted. Check whether it is visible in the photo.';
    if(record.visual_review?.fields?.[field]?.state==='adopted_for_review')return 'AI suggested this value. Check it against the photo.';
    const decision=record.reconciliation?.fields?.[field],reasons=record.confidence?.fields?.[field]?.reasons||[];
    if(decision?.flags?.includes('external_legal_identity_requires_review'))return 'Business identity was supplemented from the public register.';
    if(decision?.disagreement||reasons.some(r=>r.includes('competing')))return 'Different readings were found. Check the printed value.';
    if(reasons.some(r=>r.includes('incomplete')))return 'Part of the photo could not be read reliably.';
    if(reasons.some(r=>r.includes('Fewer than two')))return 'Only one reliable reading is available.';
    if(reasons.some(r=>r.includes('differs')))return 'The current value differs from the original reading.';
    return 'Check this value against the original photo.';
  }
  function periodRange(period,today=new Date()){
    const year=today.getFullYear(),month=today.getMonth(),day=today.getDate();
    const iso=(y,m,d)=>`${y}-${String(m+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    if(period==='month')return {start:iso(year,month,1),end:iso(year,month,day)};
    if(period==='last-month'){const end=new Date(year,month,0);return {start:iso(end.getFullYear(),end.getMonth(),1),end:iso(end.getFullYear(),end.getMonth(),end.getDate())};}
    const financialStart=month>=6?year:year-1;
    if(period==='financial-year')return {start:iso(financialStart,6,1),end:iso(year,month,day)};
    if(period==='last-financial-year')return {start:iso(financialStart-1,6,1),end:iso(financialStart,5,30)};
    return {start:'',end:''};
  }
  function readyForExport(record){return ['confirmed','auto_confirmed'].includes(record.status)&&core.every(field=>valid(record,field));}
  return {attentionFields,fieldReason,periodRange,readyForExport,validField:valid};
});
