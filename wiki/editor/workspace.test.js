import test from 'node:test';
import assert from 'node:assert/strict';
import {createWorkspace, batchPages} from './workspace.js';
const storage = () => { const data = new Map(); return {getItem:key=>data.get(key),setItem:(key,value)=>data.set(key,value)}; };
const page = {path:'start/a.md',title:'A',body:'Body',revision:'abc'};
test('workspace survives page navigation and reload with multiple drafts', () => {
  const disk = storage(), first = createWorkspace(disk);
  first.start(); first.put(page);
  const second = createWorkspace(disk);
  second.put({...page,path:'help/b.md',title:'B'});
  assert.equal(second.active(),true);
  assert.equal(createWorkspace(disk).drafts().length,2);
  assert.deepEqual(second.get(page.path),page);
});
test('batch preserves revisions and supports root new pages', () => {
  assert.deepEqual(batchPages([page,{path:'draft:new',creating:true,slug:'new',title:'New',body:'Text'}]),[page,{section:'',slug:'new',title:'New',body:'Text'}]);
});
test('conflict leaves drafts intact and successful acknowledgement preserves newer edits', () => {
  const workspace = createWorkspace(storage()); workspace.start(); workspace.put(page);
  const submitted = workspace.drafts();
  assert.deepEqual(workspace.drafts(),submitted);
  workspace.put({...page,body:'Edited while publishing'});
  workspace.acknowledge(submitted);
  assert.equal(workspace.drafts().length,1);
  workspace.acknowledge(workspace.drafts());
  assert.equal(workspace.drafts().length,0);
  assert.equal(workspace.active(),true);
});
test('folder move remaps nested drafts and discard exits workspace', () => {
  const workspace = createWorkspace(storage()); workspace.start(); workspace.put(page);
  workspace.move('start','help/start');
  assert.equal(workspace.get('help/start/a.md').body,'Body');
  workspace.discard(); assert.equal(workspace.active(),false); assert.equal(workspace.drafts().length,0);
});
test('failed persistence never acknowledges unsaved in-memory updates', () => {
  const disk = storage(), workspace = createWorkspace(disk);
  workspace.start(); workspace.put(page);
  disk.setItem = () => { throw new Error('quota'); };
  assert.throws(()=>workspace.put({...page,body:'Unsaved changes'}),/quota/);
  assert.deepEqual(workspace.get(page.path),page);
  assert.throws(()=>workspace.remove(page.path),/quota/);
  assert.deepEqual(workspace.get(page.path),page);
  assert.throws(()=>workspace.acknowledge([page]),/quota/);
  assert.deepEqual(workspace.get(page.path),page);
  assert.throws(()=>workspace.discard(),/quota/);
  assert.equal(workspace.active(),true);
});
