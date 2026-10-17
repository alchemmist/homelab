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
const drag = (state,source,target,y=0) => {
  const row=document.querySelector(`[data-node-id="${source}"] > .nav-row`);
  const start=new state.dom.window.Event('dragstart',{bubbles:true,cancelable:true});
  Object.defineProperty(start,'dataTransfer',{value:{setData(){},effectAllowed:''}});row.dispatchEvent(start);
  const drop=new state.dom.window.MouseEvent('drop',{bubbles:true,cancelable:true,clientY:y});target.dispatchEvent(drop);
};
test('root toolbar contains only two named SVG icons without row controls',async()=>{
  await setup();const root=document.querySelector('.wiki-tree-root');
  assert.equal(root.querySelectorAll('button').length,2);assert.equal(root.querySelectorAll('svg').length,2);assert.equal(root.textContent,'');
  assert.equal(document.querySelector('.wiki-tree-controls'),null);assert.equal(document.querySelector('select'),null);
  assert.equal(document.querySelector('[data-node-id="ai/chat.md"] a').draggable,false);
});
test('new note opens article editor directly at root without publishing an empty page',async()=>{
  const state=await setup();click('Новая заметка');await tick();
  assert.deepEqual(state.getSeed(),{parent:'',title:'Новая заметка',slug:''});assert.equal(state.calls.length,1);
  assert.equal(document.querySelector('.wiki-tree-create'),null);
});
test('folder creation carries tree revision and always targets root',async()=>{
  const state=await setup();click('Новая папка');
  assert.equal(document.querySelector('select'),null);
  document.querySelector('[aria-label="Название новой папки"]').value='Folder';document.querySelector('[aria-label="Адрес новой папки"]').value='folder';click('Создать папку');await tick();
  assert.deepEqual(state.calls[1],{endpoint:'/folders',data:{parent:'',title:'Folder',slug:'folder',revision:'r1'}});assert.deepEqual(state.events,['changed']);
});
test('dirty article blocks new notes, folders and dragging',async()=>{
  const state=await setup(true);click('Новая папка');click('Новая заметка');
  drag(state,'ai/chat.md',document.querySelector('.wiki-tree-root'));await tick();
  assert.equal(state.getSeed(),undefined);assert.equal(state.calls.length,1);assert.equal(document.querySelector('.wiki-tree-create'),null);assert.match(state.messages.at(-1),/опубликуйте/);
});
test('drag to root moves note with revision and updates article path',async()=>{
  const state=await setup();drag(state,'ai/chat.md',document.querySelector('.wiki-tree-root'));await tick();
  assert.deepEqual(state.calls[1],{endpoint:'/move',data:{source:'ai/chat.md',target_parent:'',before:null,revision:'r1'}});
  assert.deepEqual(state.moves,[{source:'ai/chat.md',target:'chat.md'}]);assert.deepEqual(state.events,['moved','changed']);
  assert.equal(document.querySelector('.wiki-tree-dragging'),null);
});
test('drag positions support before, after and inside folder',async()=>{
  for (const [y,parent,before] of [[10,'','ai'],[90,'','other.md'],[50,'ai',null]]) {
    const state=await setup();state.data.nodes.push({id:'other.md',kind:'page',title:'Other',url:'/other/'},{id:'note.md',kind:'page',title:'Note',url:'/note/'});await state.controller.refresh();
    const target=document.querySelector('[data-node-id="ai"] > .nav-row');target.getBoundingClientRect=()=>({top:0,height:100});
    drag(state,'note.md',target,y);await tick();
    assert.deepEqual(state.calls.at(-1),{endpoint:'/move',data:{source:'note.md',target_parent:parent,before,revision:'r1'}});
  }
});

test('folder title only expands and never links to a nonexistent section page',async()=>{
  await setup();const row=document.querySelector('[data-node-id="ai"] > .nav-row');assert.equal(row.querySelector('a'),null);assert.equal(row.querySelector('svg path').getAttribute('d'),'m9 5 7 7-7 7');click('Раскрыть AI');assert.equal(document.querySelector('[data-node-id="ai"] > ul').hidden,true);
});
test('new page remains unlinked until its publication completes',async()=>{
  const state=await setup();state.data.nodes[0].children.push({id:'ai/new.md',kind:'page',title:'New',url:'/ai/new/'});await state.controller.refresh({pendingPage:'ai/new.md',commit:'c2'});
  assert.equal(document.querySelector('[data-node-id="ai/new.md"] a').hasAttribute('href'),false);state.publish();await tick();assert.equal(document.querySelector('[data-node-id="ai/new.md"] a').getAttribute('href'),'/ai/new/');
});
