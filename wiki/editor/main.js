import { initializeTree } from './tree.js';
import { createPublishedView } from './published-view.js';
import { createPublicationState } from './publication-state.js';
import { Editor } from '@tiptap/core';
import { extensions, prepareMarkdown, sourceBody } from './markdown.js';

const root = document.getElementById('wiki-editor');
if (root) initialize();
function initialize() {
  const heading = document.getElementById('page-title');
  const article = document.querySelector('.document .hc-content');
  if (!heading || !article) return;
  const status = root.querySelector('[role="alert"]');
  heading.after(status);
  const editbar = root.querySelector('.wiki-editbar');
  const actions = root.querySelector('.wiki-editor-actions');
  const save = root.querySelector('[data-editor-save]');
  const publicationState = createPublicationState(save);
  const publications = new Map();
  const view = createPublishedView({article, heading, bodyHash: root.dataset.bodyHash});
  let csrf = '', revision = '', path = root.dataset.path, original = '', originalJSON, refs;
  let structure;
  let editor, toolbar, fields, linkForm, baselineTitle, creating = false, busy = false, generation = 0;
  const message = (text, error = false) => { status.textContent = error ? text : ''; status.hidden = !error; };
  const api = async (endpoint, data, method = 'POST') => {
    const response = await fetch('/api/editor' + endpoint, {method: data === undefined ? 'GET' : method, credentials: 'same-origin', cache: 'no-store', headers: data === undefined ? {} : {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: data === undefined ? undefined : JSON.stringify(data)});
    const result = await response.json().catch(() => ({}));
    if (!response.ok) { const error = new Error(response.status === 409 ? 'Заметка уже изменена. Ваши правки остаются на странице. Скопируйте текст перед загрузкой актуальной версии.' : response.status === 401 || response.status === 403 ? 'Нет доступа. Проверьте Socrat WireGuard. Ваш текст остаётся на странице.' : result.error || result.detail || 'Не удалось выполнить запрос. Проверьте соединение и повторите попытку.'); error.status=response.status; throw error; }
    return result;
  };
  const dirty = () => editor && (creating || heading.textContent !== baselineTitle || JSON.stringify(editor.getJSON()) !== JSON.stringify(originalJSON));
  const setBusy = value => { busy = value; save.disabled = value; root.querySelector('[data-editor-cancel]').disabled = value; editor?.setEditable(!value, false); heading.contentEditable = editor && !value ? 'true' : 'false'; };
  const stop = () => {
    if (busy || dirty() && !confirm('Отменить несохранённые изменения?')) return;
    generation++;
    editor?.destroy(); editor = null;
    toolbar?.remove(); fields?.remove(); linkForm?.remove();
    view.restore();
    article.classList.remove('wiki-rich-editor');

    heading.removeAttribute('contenteditable');
    heading.removeAttribute('role');
    heading.removeAttribute('aria-label');
    editbar.hidden = true; actions.hidden = false;
    document.body.classList.remove('wiki-editing');
    message('');
    root.querySelector('[data-editor-open]')?.focus();
  };
  function addToolbar() {
    toolbar = document.createElement('div'); toolbar.className = 'wiki-formatbar'; toolbar.setAttribute('role', 'toolbar'); toolbar.setAttribute('aria-label', 'Форматирование текста');
    const commands = [
      ['Текст', () => editor.chain().focus().setParagraph().run()],
      ['H2', () => editor.chain().focus().toggleHeading({level:2}).run()],
      ['H3', () => editor.chain().focus().toggleHeading({level:3}).run()],
      ['Жирный', () => editor.chain().focus().toggleBold().run()],
      ['Курсив', () => editor.chain().focus().toggleItalic().run()],
      ['Список', () => editor.chain().focus().toggleBulletList().run()],
      ['1. Список', () => editor.chain().focus().toggleOrderedList().run()],
      ['Код', () => editor.chain().focus().toggleCodeBlock().run()],
      ['Таблица', () => editor.chain().focus().insertTable({rows:3,cols:2,withHeaderRow:true}).run()],
      ['Ссылка', () => { linkForm.hidden = !linkForm.hidden; if (!linkForm.hidden) linkForm.querySelector('input').focus(); }]
    ];
    for (const [label, run] of commands) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
      button.addEventListener('mousedown', event => event.preventDefault());
      button.addEventListener('click', () => { if (!busy) run(); }); toolbar.append(button);
    }
    article.before(toolbar);
    linkForm = document.createElement('form'); linkForm.className = 'wiki-link-form'; linkForm.hidden = true;
    const input = document.createElement('input'); input.type = 'text'; input.placeholder = 'https://… или /раздел/заметка/'; input.setAttribute('aria-label', 'Адрес ссылки');
    const apply = document.createElement('button'); apply.type = 'submit'; apply.textContent = 'Добавить ссылку';
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Убрать ссылку';
    remove.addEventListener('click', () => { editor.chain().focus().unsetLink().run(); linkForm.hidden = true; });
    linkForm.append(input, apply, remove); toolbar.after(linkForm);
    linkForm.addEventListener('submit', event => { event.preventDefault(); const href = input.value.trim(); if (!/^(https?:\/\/|mailto:|\/(?!\/)|#)/i.test(href)) { message('Укажите https://, mailto:, якорь или путь от корня сайта.', true); return; } editor.chain().focus().extendMarkRange('link').setLink({href}).run(); linkForm.hidden = true; });
  }
  async function open(isNew, seed) {
    if (busy || editor) return;
    busy = true; generation++; publicationState.reset(); message('');
    try {
      creating = isNew;
      const page = creating ? {title:seed?.title || 'Новая заметка',body:'',revision:''} : await api('/pages?path=' + encodeURIComponent(path));
      const prepared = prepareMarkdown(page.body);
      if (!creating) await view.hydratePage({api, path, page, canApply:()=>true, apply:false});
      original = page.body; refs = prepared.refs; revision = page.revision;
      article.replaceChildren(); article.classList.add('wiki-rich-editor');
      editor = new Editor({onUpdate:()=>publicationState.reset(), element: article, extensions: extensions(), content: prepared.prepared, contentType:'markdown', editorProps:{
        attributes:{'aria-label':'Текст заметки',role:'textbox','aria-multiline':'true'},
        handlePaste(view, event) { event.preventDefault(); const text = event.clipboardData?.getData('text/plain') || ''; view.dispatch(view.state.tr.insertText(text)); return true; },
        handleDrop() { return true; }
      }});
      originalJSON = editor.getJSON(); baselineTitle = page.title;
      heading.textContent = page.title; heading.contentEditable = 'true'; heading.setAttribute('role','textbox'); heading.setAttribute('aria-label','Название заметки');
      addToolbar();
      if (creating) {
        fields = document.createElement('div'); fields.className = 'wiki-new-fields';
        const slugLabel = document.createElement('label'); slugLabel.textContent = 'Адрес: латинские буквы, цифры, дефисы';
        const slug = document.createElement('input'); slug.name = 'slug'; slug.placeholder = 'new-note'; slug.value = seed?.slug || ''; slugLabel.append(slug);
        fields.append(slugLabel); heading.parentElement.after(fields);
      }
      actions.hidden = true; editbar.hidden = false; document.body.classList.add('wiki-editing');
      message(''); heading.focus();
    } catch (error) { message(error.message,true); }
    finally { busy = false; }
  }
  async function refreshArticleRevision() {
    if (!editor || dirty()) return;
    const activeEditor=editor, activePath=path, activeJSON=JSON.stringify(editor.getJSON()), activeTitle=heading.textContent;
    try {
      const page=await api('/pages?path='+encodeURIComponent(activePath));
      if(editor!==activeEditor || path!==activePath || heading.textContent!==activeTitle || JSON.stringify(editor.getJSON())!==activeJSON || dirty())return;
      if(page.body!==original || page.title!==baselineTitle){message('Содержимое заметки изменилось. Обновите страницу перед редактированием.',true);return;}
      revision=page.revision;
    } catch(error) {message(error.message,true);}
  }
  function publication(commit) {
    if (publications.has(commit)) return publications.get(commit);
    const pending = (async () => {
      for (let attempt=0; attempt<120; attempt++) {
        await new Promise(resolve => setTimeout(resolve,5000));
        try {
          const result = await api('/publications/' + encodeURIComponent(commit));
          if (result.status === 'failed') { message('Изменения сохранены, но публикация не прошла. Обратитесь к администратору.',true); return false; }
          if (result.status === 'published') return true;
        } catch {}
      }
      message('Изменения сохранены. Публикация ещё не подтверждена спустя 10 минут. Обратитесь к администратору.',true);
      return false;
    })();
    publications.set(commit, pending);
    return pending;
  }

  save.addEventListener('click', async () => {
    if (busy || !editor) return;
    const title = heading.textContent.trim();
    if (!title || title.length>200) { message('Укажите заголовок длиной до 200 символов.',true); heading.focus(); return; }
    const body = sourceBody(original,originalJSON,editor.getJSON(),editor.getMarkdown(),refs);
    const payload = {title,body};
    if (creating) { payload.section=''; payload.slug=fields.querySelector('input').value.trim(); if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(payload.slug)) { message('В адресе используйте латинские буквы, цифры и дефисы.',true); return; } }
    else Object.assign(payload,{path,revision});
    setBusy(true); message('');
    try {
      if (creating && structure) payload.tree_revision=await structure.ensureRevision();
      const wasCreating=creating;
      const result = await api('/pages',payload,creating ? 'POST':'PUT');
      path=result.path; revision=result.revision; original=body; originalJSON=editor.getJSON(); baselineTitle=title; creating=false; fields?.remove(); fields=null;
      const fallback = document.createElement('template'); fallback.innerHTML = editor.getHTML();
      for (const link of fallback.content.querySelectorAll('a[href]')) {
        const ref = refs.get(link.getAttribute('href'));
        if (ref) {
          const [target, fragment] = ref.target.split('#');
          const base = target.startsWith('/') ? target : '/' + path.split('/').slice(0,-1).concat(target).join('/');
          link.setAttribute('href', target ? base.replace(/(?:_index|index)?\.md$/, '').replace(/\/$/, '') + '/' + (fragment ? '#' + fragment : '') : '#' + fragment);
        }
      }
      view.capture(title, fallback.innerHTML);
      try {
        const preview = await api('/preview', {title, body, path});
        view.capture(title, preview.html);
      } catch {}
      message(''); structure?.refresh({pendingPage:wasCreating ? result.path : undefined,commit:result.commit}).catch(()=>{}); publication(result.commit).then(publicationState.pending());
    } catch(error) { message(error.message,true); }
    finally { setBusy(false); }
  });
  heading.addEventListener('input',()=>{if(editor)publicationState.reset();});
  heading.addEventListener('keydown', event => { if (editor && event.key==='Enter') {event.preventDefault();editor.commands.focus('start');} });
  heading.addEventListener('paste', event => { if (!editor) return; event.preventDefault(); document.execCommand('insertText',false,event.clipboardData.getData('text/plain').replace(/\s*\n\s*/g,' ')); });
  root.querySelector('[data-editor-open]').addEventListener('click',()=>open(false));
  root.querySelector('[data-editor-cancel]').addEventListener('click',stop);
  window.addEventListener('beforeunload',event=>{if(dirty()){event.preventDefault();event.returnValue='';}});
  api('/session').then(session=>{
    if(!session.writable || !session.csrf_token)return;
    csrf=session.csrf_token;root.hidden=false;
    const hydrationGeneration = generation;
    view.hydrate({api, path, canApply:()=>!busy && !editor && generation===hydrationGeneration}).catch(error=>message(error.message,true));
    initializeTree({api, dirty:()=>busy || dirty(), currentPath:()=>path, message, changed:refreshArticleRevision, openPage:async seed=>{if(editor)stop();await open(true,seed);}, moved:(source,target)=>{if(path===source || path.startsWith(source+'/')){path=target+path.slice(source.length);root.dataset.path=path;}}, publication:commit=>publication(commit)}).then(value=>{structure=value;}).catch(error=>message(error.message,true));
    const mobile=document.querySelector('.mobile-actions');const media=matchMedia('(max-width: 900px)');
    const position=()=>{if(media.matches&&mobile)mobile.prepend(actions);else root.prepend(actions);};media.addEventListener('change',position);position();
  }).catch(()=>{});
}
