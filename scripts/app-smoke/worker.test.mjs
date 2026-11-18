import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';

function workerHarness(fail) {
  const calls = [], replies = [];
  const columns = {uid: new Uint8Array(8)};
  const results = {open_save:{game:'FM26'}, read_players:{numbers:columns,count:1,text:{}},read_staff:{numbers:columns,count:1,rows:[]},read_stats:{numbers:columns,kind:'overall'}};
  const context = vm.createContext({URL, Blob, Uint8Array, ArrayBuffer, console, onmessage:null, postMessage:m=>replies.push(m)});
  vm.runInContext(fs.readFileSync(new URL('../../docs/app/worker.js',import.meta.url),'utf8') + '\n globalThis.harness = {set(r,p){reader=r;pyodide=p;ready=Promise.resolve()},openSave};',context);
  context.harness.set({call(name){calls.push(name); return {toJs(){return fail===name ? {error:'Reader unavailable.',kind:'UnsupportedGameError'} : {ok:results[name]}},destroy(){}}}}, {FS:{mkdirTree(){},mount(){},unmount(){},filesystems:{WORKERFS:{}}}});
  return {context,calls,replies};
}

test('staff and statistics load before cleanup',()=>{
 const {context,calls,replies}=workerHarness();
 context.harness.openSave({name:'career.fm'},m=>replies.push(m));
 assert.deepEqual(calls,['open_save','read_players','read_staff','read_stats','close_save']);
 assert.deepEqual(replies.filter(m=>['players','staff','stats'].includes(m.type)).map(m=>m.type),['players','staff','stats']);
});
test('staff failure does not skip statistics or cleanup',()=>{
 const {context,calls,replies}=workerHarness('read_staff');
 context.harness.openSave({name:'career.fm'},m=>replies.push(m));
 assert.ok(calls.includes('read_stats'));assert.equal(calls.at(-1),'close_save');
 assert.ok(replies.some(m=>m.type==='error'&&m.request==='staff'));
 assert.ok(replies.some(m=>m.type==='stats'));
});
test('statistics failure still closes after staff',()=>{
 const {context,calls,replies}=workerHarness('read_stats');
 context.harness.openSave({name:'career.fm'},m=>replies.push(m));
 assert.equal(calls.at(-1),'close_save');assert.ok(replies.some(m=>m.type==='staff'));
});
