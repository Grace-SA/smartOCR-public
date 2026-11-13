import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { timing, validateEvaluation } from '../scripts/export_blind_evaluation.mjs';
const fixture=JSON.parse(await fs.readFile(new URL('./fixtures/blind_evaluation.synthetic.json',import.meta.url),'utf8'));
test('synthetic fixture preserves failure, missing-reference and incorrect-auto denominators',()=>{
  const stats=validateEvaluation(fixture,{synthetic:true});
  assert.equal(fixture.automatic.coverage,0.5);
  assert.equal(fixture.automatic.precision,0.5);
  assert.equal(fixture.fields.total.reference_available,5);
  assert.equal(stats.pipeline.count,4);
  assert.equal(stats.wall.median,35);
  assert.equal(stats.wall.p90,120);
});
test('fixture cannot pass as real results',()=>assert.throws(()=>validateEvaluation(fixture)));
test('partial real evaluation is rejected',()=>{
  const r=structuredClone(fixture);delete r.synthetic_fixture;
  assert.throws(()=>validateEvaluation(r),/completed 100/);
});
test('no automatic confirmations remains unmeasurable precision, not zero',()=>{
  const r=structuredClone(fixture);
  for(const row of r.results) {row.auto_confirmed=false;if(row.status==='auto_confirmed') row.status='review';}
  r.automatic={count:0,coverage:0,fully_scorable:0,correct:0,false_confirmations:[],unverified_confirmations:[],precision:null};
  assert.doesNotThrow(()=>validateEvaluation(r,{synthetic:true}));
  r.automatic.precision=0;
  assert.throws(()=>validateEvaluation(r,{synthetic:true}),/precision/);
});
test('inconsistent score-file aggregate is rejected instead of silently regenerated',()=>{
  const r=structuredClone(fixture);r.automatic.precision=1;
  assert.throws(()=>validateEvaluation(r,{synthetic:true}),/precision/);
});
test('nearest-rank percentiles, blanks and real zero remain distinct',()=>{
  assert.deepEqual(timing([null,undefined]),{count:0,total:null,mean:null,median:null,p90:null,p95:null,maximum:null});
  assert.equal(timing([0,10,null]).median,5);
  assert.equal(timing([1,2,3,4,5,6,7,8,9,10]).p90,9);
});
