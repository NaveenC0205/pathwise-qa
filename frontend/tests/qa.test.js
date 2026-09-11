import test from 'node:test'
import assert from 'node:assert/strict'
import { generatePlan, csvPlan } from '../src/qa/client.js'

test('QA stream supports split unicode and emits real events before final result', async () => {
  const original = global.fetch
  const bytes = new TextEncoder().encode(JSON.stringify({type:'event',agent:'UI explorer',detail:'Home → Cart'})+'\n'+JSON.stringify({type:'result',result:{cases:[]}}))
  global.fetch = async () => new Response(new ReadableStream({start(c){ for(let i=0;i<bytes.length;i+=3)c.enqueue(bytes.slice(i,i+3));c.close() }}))
  try { const events=[]; const result=await generatePlan({}, e=>events.push(e));assert.equal(events[0].detail,'Home → Cart');assert.deepEqual(result,{cases:[]}) } finally { global.fetch=original }
})

test('QA truncated and error streams never return an incomplete plan', async () => {
  const original=global.fetch
  try {
    global.fetch=async()=>new Response('{"type":"event","agent":"Reviewer"}\n')
    await assert.rejects(()=>generatePlan({},()=>{}),/without a complete plan/)
    global.fetch=async()=>new Response('{"type":"error","message":"Model unavailable"}\n')
    await assert.rejects(()=>generatePlan({},()=>{}),/Model unavailable/)
  } finally {global.fetch=original}
})

test('CSV preserves step results, module and suite and neutralizes spreadsheet formulas', () => {
  const row={id:'SMK-001',name:' =HYPERLINK("bad")',description:'Human-readable case',module:'Cart',suite:'Smoke',testing_type:'Functional',steps:[{action:'Click Cart',expected_result:'Cart opens'}]}
  const text=csvPlan([row]);assert.match(text,/Expected: Cart opens/);assert.match(text,/"Cart","Smoke"/);assert.match(text,/"' =HYPERLINK/)
})
