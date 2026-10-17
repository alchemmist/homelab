import { Editor } from '@tiptap/core';
import { extensions, prepareMarkdown, sourceBody } from './markdown.js';

const root = document.getElementById('wiki-editor');
if (root) initialize();
function initialize() {
  const heading = document.getElementById('page-title');
  const article = document.querySelector('.document .hc-content');
  if (!heading || !article) return;
  const status = root.querySelector('[role="status"]');
  const editbar = root.querySelector('.wiki-editbar');
  const actions = root.querySelector('.wiki-editor-actions');
  const save = root.querySelector('[data-editor-save]');
  const originalHTML = article.innerHTML;
  const originalTitle = heading.textContent;
  let csrf = '', revision = '', path = root.dataset.path, original = '', originalJSON, refs;
  let editor, toolbar, fields, linkForm, baselineTitle, creating = false, busy = false, generation = 0;
  const message = (text, error = false) => { status.textContent = text; status.dataset.error = String(error); };
  const api = async (endpoint, data, method = 'POST') => {
    const response = await fetch('/api/editor' + endpoint, {method: data === undefined ? 'GET' : method, credentials: 'same-origin', cache: 'no-store', headers: data === undefined ? {} : {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: data === undefined ? undefined : JSON.stringify(data)});
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(response.status === 409 ? 'Заметка уже изменена. Ваши правки остаются на странице. Скопируйте текст перед загрузкой актуальной версии.' : response.status === 401 || response.status === 403 ? 'Нет доступа. Проверьте Socrat WireGuard. Ваш текст остаётся на странице.' : result.error || result.detail || 'Не удалось выполнить запрос. Проверьте соединение и повторите попытку.');
    return result;
  };
  const dirty = () => editor && (creating || heading.textContent !== baselineTitle || JSON.stringify(editor.getJSON()) !== JSON.stringify(originalJSON));
  const setBusy = value => { busy = value; save.disabled = value; root.querySelector('[data-editor-cancel]').disabled = value; editor?.setEditable(!value); heading.contentEditable = editor && !value ? 'true' : 'false'; };
  const stop = () => {
    if (busy || dirty() && !confirm('Отменить несохранённые изменения?')) return;
    generation++;
    editor?.destroy(); editor = null;
    toolbar?.remove(); fields?.remove(); linkForm?.remove();
    article.innerHTML = originalHTML;
    article.classList.remove('wiki-rich-editor');
    heading.textContent = originalTitle;
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
  async function open(isNew) {
    if (busy || editor) return;
    busy = true; message('Загрузка…');
    try {
      path = root.dataset.path; creating = isNew;
      const page = creating ? {title:'Новая заметка',body:'',revision:''} : await api('/pages?path=' + encodeURIComponent(path));
      const prepared = prepareMarkdown(page.body);
      const catalog = creating ? await api('/catalog') : null;
      original = page.body; refs = prepared.refs; revision = page.revision;
      article.replaceChildren(); article.classList.add('wiki-rich-editor');
      editor = new Editor({element: article, extensions: extensions(), content: prepared.prepared, contentType:'markdown', editorProps:{
        attributes:{'aria-label':'Текст заметки',role:'textbox','aria-multiline':'true'},
        handlePaste(view, event) { event.preventDefault(); const text = event.clipboardData?.getData('text/plain') || ''; view.dispatch(view.state.tr.insertText(text)); return true; },
        handleDrop() { return true; }
      }});
      originalJSON = editor.getJSON(); baselineTitle = page.title;
      heading.textContent = page.title; heading.contentEditable = 'true'; heading.setAttribute('role','textbox'); heading.setAttribute('aria-label','Название заметки');
      addToolbar();
      if (creating) {
        fields = document.createElement('div'); fields.className = 'wiki-new-fields';
        const sectionLabel = document.createElement('label'); sectionLabel.textContent = 'Раздел';
        const section = document.createElement('select'); section.name = 'section'; for (const item of catalog.sections) section.append(new Option(item.title,item.path));
        const current = path.includes('/') ? path.slice(0,path.lastIndexOf('/')) : ''; if ([...section.options].some(option => option.value === current)) section.value = current;
        sectionLabel.append(section);
        const slugLabel = document.createElement('label'); slugLabel.textContent = 'Адрес: латинские буквы, цифры, дефисы';
        const slug = document.createElement('input'); slug.name = 'slug'; slug.placeholder = 'new-note'; slugLabel.append(slug);
        fields.append(sectionLabel,slugLabel); heading.parentElement.after(fields);
      }
      actions.hidden = true; editbar.hidden = false; document.body.classList.add('wiki-editing');
      message('Правьте заголовок и текст прямо на странице.'); heading.focus();
    } catch (error) { message(error.message,true); }
    finally { busy = false; }
  }
  async function publication(commit, token, url) {
    for (let attempt=0; attempt<120 && generation===token; attempt++) {
      await new Promise(resolve => setTimeout(resolve,5000));
      if (generation!==token) return;
      try {
        const result = await api('/publications/' + encodeURIComponent(commit));
        if (generation!==token) return;
        if (result.status === 'failed') { message('Изменения сохранены, но публикация не прошла. Обратитесь к администратору.',true); return; }
        if (result.status === 'published') {
          message('Заметка опубликована. '); const link = document.createElement('a'); link.textContent = 'Открыть страницу'; const target = new URL(result.url || url,location.origin); if (target.origin===location.origin) link.href=target.href; status.append(link); return;
        }
      } catch { message('Правки сохранены. Проверка публикации временно недоступна.'); }
    }
    if (generation===token) message('Правки сохранены. Публикация ещё не подтверждена; проверьте страницу позже.');
  }
  save.addEventListener('click', async () => {
    if (busy || !editor) return;
    const title = heading.textContent.trim();
    if (!title || title.length>200) { message('Укажите заголовок длиной до 200 символов.',true); heading.focus(); return; }
    const body = sourceBody(original,originalJSON,editor.getJSON(),editor.getMarkdown(),refs);
    const payload = {title,body};
    if (creating) { payload.section=fields.querySelector('select').value; payload.slug=fields.querySelector('input').value.trim(); if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(payload.slug)) { message('В адресе используйте латинские буквы, цифры и дефисы.',true); return; } }
    else Object.assign(payload,{path,revision});
    setBusy(true); message('Сохранение…');
    try {
      const result = await api('/pages',payload,creating ? 'POST':'PUT');
      path=result.path; revision=result.revision; original=body; originalJSON=editor.getJSON(); baselineTitle=title; creating=false; fields?.remove(); fields=null;
      message('Правки сохранены. Публикация выполняется…'); publication(result.commit,++generation,result.url);
    } catch(error) { message(error.message,true); }
    finally { setBusy(false); }
  });
  heading.addEventListener('keydown', event => { if (editor && event.key==='Enter') {event.preventDefault();editor.commands.focus('start');} });
  heading.addEventListener('paste', event => { if (!editor) return; event.preventDefault(); document.execCommand('insertText',false,event.clipboardData.getData('text/plain').replace(/\s*\n\s*/g,' ')); });
  root.querySelector('[data-editor-open]').addEventListener('click',()=>open(false));
  root.querySelector('[data-editor-new]').addEventListener('click',()=>open(true));
  root.querySelector('[data-editor-cancel]').addEventListener('click',stop);
  window.addEventListener('beforeunload',event=>{if(dirty()){event.preventDefault();event.returnValue='';}});
  api('/session').then(session=>{
    if(!session.writable || !session.csrf_token)return;
    csrf=session.csrf_token;root.hidden=false;
    const mobile=document.querySelector('.mobile-actions');const media=matchMedia('(max-width: 900px)');
    const position=()=>{if(media.matches&&mobile)mobile.prepend(actions);else root.prepend(actions);};media.addEventListener('change',position);position();
  }).catch(()=>{});
}
