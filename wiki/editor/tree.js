export async function initializeTree({api, dirty, openPage, currentPath, moved, changed = async () => {}, message, publication}) {
  const nav = document.querySelector('.page-tree');
  if (!nav) return;
  const pendingLinks = new Map();
  let tree, pending = false, dragging = '', expanded = new Set(), chooser;
  const error = text => message(text, true);
  const button = (text, label, action) => {
    const el = document.createElement('button'); el.type = 'button'; el.textContent = text; el.setAttribute('aria-label', label); el.title = label; el.addEventListener('click', action); return el;
  };
  const flatten = nodes => nodes.flatMap(node => [node, ...flatten(node.children || [])]);
  const parentOf = id => id.includes('/') ? id.slice(0, id.lastIndexOf('/')) : '';
  const guard = () => {
    if (pending) return false;
    if (dirty()) { error('Сначала опубликуйте или отмените правки заметки.'); return false; }
    message(''); return true;
  };
  function watchPublication(commit) {
    const snapshot = new Map(pendingLinks);
    publication(commit).then(published => {
      if (!published) return;
      for (const [id, url] of snapshot) if (pendingLinks.get(id) === url) pendingLinks.delete(id);
      render();
    });
  }
  const refresh = async ({pendingPage, commit} = {}) => {
    if (pendingPage) pendingLinks.set(pendingPage, null);
    tree = await api('/tree'); render();
    if (commit) watchPublication(commit);
  };
  async function mutate(endpoint, payload) {
    if (!guard()) return;
    pending = true;
    try {
      const result = await api(endpoint, {...payload, revision: tree.revision});
      const oldNodes = flatten(tree.nodes);
      if (endpoint === '/move') {
        const target = payload.target_parent ? payload.target_parent + '/' + payload.source.split('/').pop() : payload.source.split('/').pop();
        for (const node of oldNodes.filter(n => n.kind === 'page' && (n.id === payload.source || n.id.startsWith(payload.source + '/')))) pendingLinks.set(target + node.id.slice(payload.source.length), pendingLinks.has(node.id) ? pendingLinks.get(node.id) : node.url);
      }
      tree = result; render(); watchPublication(result.commit);
      return result;
    } catch (e) {
      if (e.status === 409) { await refresh(); error('Структура уже изменилась. Обновили список; повторите действие.'); }
      else error(e.message);
    } finally { pending = false; }
  }
  async function move(source, target_parent, before = null) {
    if (source === target_parent || target_parent.startsWith(source + '/') || source === before) return;
    const result = await mutate('/move', {source, target_parent, before});
    if (result) { moved(source, target_parent ? target_parent + '/' + source.split('/').pop() : source.split('/').pop()); render(); await changed(); }
  }
  function createFolder(anchor) {
    if (!guard()) return;
    chooser?.remove(); chooser = document.createElement('div'); chooser.className = 'wiki-tree-create';
    const title = document.createElement('input'); title.placeholder = 'Название папки'; title.setAttribute('aria-label','Название новой папки'); title.maxLength = 200;
    const slug = document.createElement('input'); slug.placeholder = 'adres-latinicey'; slug.setAttribute('aria-label','Адрес новой папки');
    const submit = button('Создать','Создать папку', async () => {
      if (!title.value.trim() || !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug.value)) { error('Укажите название и адрес: латинские буквы, цифры, дефисы.'); return; }
      const result = await mutate('/folders',{parent:'',title:title.value.trim(),slug:slug.value});
      if (result) await changed();
    });
    chooser.append(title,slug,submit,button('×','Отменить создание',()=>chooser.remove())); anchor.after(chooser); title.focus();
  }
  function iconButton(label, paths, action) {
    const el = button('', label, action);
    const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
    for (const [key,value] of Object.entries({width:'18',height:'18',viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.5','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'})) svg.setAttribute(key,value);
    for (const d of paths) { const path = document.createElementNS('http://www.w3.org/2000/svg','path'); path.setAttribute('d',d); svg.append(path); }
    el.append(svg); return el;
  }
  function clearDrop() { nav.querySelectorAll('[data-drop]').forEach(el=>delete el.dataset.drop); }
  function dropTarget(row,node,siblings) {
    const position = event => {
      const rect=row.getBoundingClientRect(), ratio=(event.clientY-rect.top)/rect.height;
      return node.kind==='folder' && ratio>.25 && ratio<.75 ? 'inside' : ratio<.5 ? 'before' : 'after';
    };
    row.addEventListener('dragover',event=>{ if(!dragging || dragging===node.id || node.id.startsWith(dragging+'/'))return; event.preventDefault();clearDrop();row.dataset.drop=position(event); });
    row.addEventListener('drop',event=>{
      event.preventDefault();event.stopPropagation();const where=position(event);clearDrop();
      if(!dragging)return;
      const source=dragging;dragging='';nav.classList.remove('wiki-tree-dragging');
      if(where==='inside') { expanded.add(node.id); move(source,node.id); }
      else move(source,parentOf(node.id),where==='before' ? node.id : siblings[siblings.indexOf(node)+1]?.id || null);
    });
  }
  function list(nodes, depth=0) {
    const ul=document.createElement('ul');ul.className='nav-level'+(!depth?' nav-root':'');
    for(const node of nodes) {
      const li=document.createElement('li');li.className='nav-item'+(node.kind==='folder'?' nav-section':'');li.dataset.nodeId=node.id;
      const row=document.createElement('div');row.className='nav-row wiki-tree-row';row.draggable=true;
      row.addEventListener('dragstart',event=>{if(!guard()){event.preventDefault();return;} dragging=node.id;nav.classList.add('wiki-tree-dragging');event.dataTransfer.setData('text/plain',node.id);event.dataTransfer.effectAllowed='move';});
      row.addEventListener('dragend',()=>{dragging='';nav.classList.remove('wiki-tree-dragging');clearDrop();});
      if(node.kind==='folder') {
        const toggle=button('', 'Раскрыть '+node.title,()=>{expanded.has(node.id)?expanded.delete(node.id):expanded.add(node.id);render();});
        toggle.className='tree-toggle wiki-tree-folder'; toggle.setAttribute('aria-expanded',String(expanded.has(node.id)));
        const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
        for(const [key,value] of Object.entries({class:'icon',width:'20',height:'20',viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.5','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))svg.setAttribute(key,value);
        const chevron=document.createElementNS('http://www.w3.org/2000/svg','path');chevron.setAttribute('d','m9 5 7 7-7 7');svg.append(chevron);
        const label=document.createElement('span');label.textContent=node.title;toggle.append(svg,label);row.append(toggle);
      } else {
        const link=document.createElement('a');link.draggable=false;link.href=pendingLinks.get(node.id) || node.url;link.textContent=node.title;
        if((node.page_path || node.id)===currentPath())link.setAttribute('aria-current','page');
        if(pendingLinks.has(node.id) && !pendingLinks.get(node.id)) {link.removeAttribute('href');link.setAttribute('aria-disabled','true');link.title='Ожидает публикации';}
        link.addEventListener('click',event=>{if(!link.hasAttribute('href')){event.preventDefault();return;}if(dirty()){event.preventDefault();error('Сначала опубликуйте или отмените правки заметки.');}});row.append(link);
      }
      li.append(row);dropTarget(row,node,nodes);
      if(node.children?.length){const children=list(node.children,depth+1);children.hidden=!expanded.has(node.id);li.append(children);}ul.append(li);
    }return ul;
  }
  function render() {
    nav.querySelector('.nav-root')?.remove();nav.querySelector('.wiki-tree-root')?.remove();chooser?.remove();
    const root=document.createElement('div');root.className='wiki-tree-root';
    root.append(
      iconButton('Новая заметка',['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z','M14 2v6h6','M12 12v6','M9 15h6'],async()=>{if(guard()){chooser?.remove();await openPage({parent:'',title:'Новая заметка',slug:''});}}),
      iconButton('Новая папка',['M20 20H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5l2 2h9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2Z','M12 10v6','M9 13h6'],()=>createFolder(root))
    );
    root.addEventListener('dragover',event=>{if(dragging){event.preventDefault();clearDrop();root.dataset.drop='inside';}});
    root.addEventListener('drop',event=>{event.preventDefault();const source=dragging;dragging='';nav.classList.remove('wiki-tree-dragging');clearDrop();if(source)move(source,'');});nav.append(root,list(tree.nodes));
  }
  tree=await api('/tree'); for(const node of flatten(tree.nodes))if(node.kind==='folder' && currentPath().startsWith(node.id+'/'))expanded.add(node.id);render();
  return {refresh, revision:()=>tree.revision};
}
