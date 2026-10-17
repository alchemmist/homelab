import test from 'node:test';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import { initializeTree } from './tree.js';

const fixture = () => ({revision:'r1',nodes:[{id:'ai',title:'AI',kind:'folder',url:'/ai/',children:[{id:'ai/chat.md',title:'Chat',kind:'page',url:'/ai/chat/'}]}]});
async function setup(isDirty=false) {
  const dom=new JSDOM('<nav class="page-tree"><ul class="nav-root"><li>Static</li></ul></nav>',{url:'https://wiki.example/'});
  globalThis.document=dom.window.document;globalThis.Option=dom.window.Option;
  const calls=[],messages=[],moves=[],events=[];let seed;const data=fixture();let resolvePublication;
  const controller=await initializeTree({api:async (endpoint,payload)=>{calls.push({endpoint,data:payload});return {...data,commit:'c1'};},dirty:()=>isDirty,currentPath:()=> 'ai/chat.md',openPage:async value=>{seed=value;},moved:(source,target)=>{moves.push({source,target});events.push('moved');},changed:async()=>events.push('changed'),message:text=>messages.push(text),publication:()=>new Promise(resolve=>{resolvePublication=resolve;})});
  return {dom,calls,messages,moves,events,data,controller,publish:()=>resolvePublication(true),getSeed:()=>seed};
}
const click = label => document.querySelector(`[aria-label="${label}"]`).click();
const tick = () => new Promise(resolve=>setTimeout(resolve,0));
test('sidebar creates note through article editor without publishing an empty page',async()=>{
  const state=await setup();click('Добавить в AI');
  document.querySelector('[aria-label="Название нового элемента"]').value='New';document.querySelector('[aria-label="Адрес нового элемента"]').value='new';click('Создать элемент');await tick();
  assert.equal(state.getSeed().parent,'ai');assert.equal(state.getSeed().slug,'new');assert.equal(state.calls.length,1);
});
test('folder creation carries tree revision and parent',async()=>{
  const state=await setup();click('Добавить в AI');document.querySelector('select').value='folder';document.querySelector('[aria-label="Название нового элемента"]').value='Folder';document.querySelector('[aria-label="Адрес нового элемента"]').value='folder';click('Создать элемент');await tick();
  assert.deepEqual(state.calls[1],{endpoint:'/folders',data:{parent:'ai',title:'Folder',slug:'folder',revision:'r1'}});assert.deepEqual(state.events,['changed']);
});
test('dirty article blocks structure operations',async()=>{
  const state=await setup(true);click('Добавить в AI');assert.equal(document.querySelector('.wiki-tree-create'),null);assert.match(state.messages.at(-1),/опубликуйте/);
});
test('keyboard move menu offers root and moves with revision',async()=>{
  const state=await setup();click('Переместить Chat');document.querySelector('select').value='';click('Переместить в папку');await tick();
  assert.deepEqual(state.calls[1],{endpoint:'/move',data:{source:'ai/chat.md',target_parent:'',before:null,revision:'r1'}});
});

test('folder title only expands and never links to a nonexistent section page',async()=>{
  await setup();const row=document.querySelector('[data-node-id="ai"] > .nav-row');assert.equal(row.querySelector('a'),null);assert.equal(row.querySelector('svg path').getAttribute('d'),'m9 5 7 7-7 7');click('Раскрыть AI');assert.equal(document.querySelector('[data-node-id="ai"] > ul').hidden,true);
});
test('move notifies article path remapping',async()=>{
  const state=await setup();click('Переместить Chat');document.querySelector('select').value='';click('Переместить в папку');await tick();assert.deepEqual(state.moves,[{source:'ai/chat.md',target:'chat.md'}]);assert.deepEqual(state.events,['moved','changed']);
});
test('new page remains unlinked until its publication completes',async()=>{
  const state=await setup();state.data.nodes[0].children.push({id:'ai/new.md',kind:'page',title:'New',url:'/ai/new/'});await state.controller.refresh({pendingPage:'ai/new.md',commit:'c2'});
  assert.equal(document.querySelector('[data-node-id="ai/new.md"] a').hasAttribute('href'),false);state.publish();await tick();assert.equal(document.querySelector('[data-node-id="ai/new.md"] a').getAttribute('href'),'/ai/new/');
});
