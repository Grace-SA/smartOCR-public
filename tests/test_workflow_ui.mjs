import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {periodRange,attentionFields,fieldReason,readyForExport}=createRequire(import.meta.url)('../static/workflow.js');

test('Australian financial year switches on 1 July, using local calendar dates',()=>{
  assert.deepEqual(periodRange('financial-year',new Date(2026,5,30)),{start:'2025-07-01',end:'2026-06-30'});
  assert.deepEqual(periodRange('financial-year',new Date(2026,6,1)),{start:'2026-07-01',end:'2026-07-01'});
  assert.deepEqual(periodRange('last-financial-year',new Date(2026,10,13)),{start:'2025-07-01',end:'2026-06-30'});
});
test('month presets handle January rollover and leap February',()=>{
  assert.deepEqual(periodRange('last-month',new Date(2026,0,5)),{start:'2025-12-01',end:'2025-12-31'});
  assert.deepEqual(periodRange('last-month',new Date(2024,2,1)),{start:'2024-02-01',end:'2024-02-29'});
  assert.deepEqual(periodRange('month',new Date(2026,10,13)),{start:'2026-11-01',end:'2026-11-13'});
  assert.deepEqual(periodRange(''),{start:'',end:''});
});
test('human confirmation takes priority over old model warnings',()=>{
  const r={merchant:'Maple',date:'2024-01-02',total:0,status:'confirmed',confidence:{fields:{merchant:{ready:false}}}};
  assert.deepEqual(attentionFields(r),[]);assert.equal(readyForExport(r),true);
  r.status='review';assert.deepEqual(attentionFields(r),['merchant']);
});
test('only the uncertain field is highlighted and visual suggestions are explained',()=>{
  const r={merchant:'Maple',date:'2024-01-02',total:12,status:'review',confidence:{fields:{merchant:{ready:true},date:{ready:true},total:{ready:false}}},visual_review:{fields:{total:{state:'adopted_for_review'}}}};
  assert.deepEqual(attentionFields(r),['total']);assert.match(fieldReason(r,'total'),/AI suggested/);
});
test('ready-only export keeps real zero and refunds but excludes missing or invalid fields',()=>{
  const base={merchant:'Maple',date:'2024-01-02',total:0,status:'auto_confirmed'};
  assert.equal(readyForExport(base),true);assert.equal(readyForExport({...base,total:-10}),true);
  for(const patch of [{status:'review'},{total:null},{merchant:'Unknown merchant'},{date:'2024-02-31'},{date:''},{total:NaN}])assert.equal(readyForExport({...base,...patch}),false);
});
