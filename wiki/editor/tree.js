export async function initializeTree({api, workspace, begin = () => true, dirty, structureDirty = dirty, openPage, currentPath, moved, changed = async () => {}, message, publication}) {
  const nav = document.querySelector('.page-tree');
  if (!nav) return;
  const pendingLinks = new Map();
  let tree, loading, treeGeneration = 0, pending = false, dragging = '', expanded = new Set(), chooser, pointer, drop, expandTimer, expandId, scrollFrame;
  const error = text => message(text, true);
  const button = (text, label, action) => {
    const el = document.createElement('button'); el.type = 'button'; el.textContent = text; el.setAttribute('aria-label', label); el.title = label; el.addEventListener('click', action); return el;
  };
  const flatten = nodes => nodes.flatMap(node => [node, ...flatten(node.children || [])]);
  const parentOf = id => id.includes('/') ? id.slice(0, id.lastIndexOf('/')) : '';
  const canDrag = () => !workspace || workspace.active();
  const guard = (structure = true) => {
    if (pending) return false;
    if (dirty() || !workspace && structure && structureDirty()) { error('Опубликуйте или отмените правки wiki перед изменением структуры.'); return false; }
    message(''); return true;
  };
  function loadTree() {
    if (!loading) {
      const generation = treeGeneration;
      loading = api('/tree').then(value => { if (generation === treeGeneration) { if (workspace) { workspace.seedTree(value); tree = workspace.tree(); } else tree = value; } return tree; }).finally(() => { loading = null; });
    }
    return loading;
  }
  async function ensureRevision() {
    if (!tree) await loadTree();
    return tree.revision;
  }
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
    await loadTree(); render();
    if (commit) watchPublication(commit);
  };
  async function mutate(endpoint, payload) {
    if (!guard()) return;
    pending = true; nav.setAttribute('aria-busy', 'true');
    try {
      if (loading) await loading;
      const revision = await ensureRevision();
      let result;
      if (workspace) {
        if (!begin()) return;
        workspace.stage({type:endpoint === "/move" ? "move" : "folder",...payload});
        result = workspace.tree();
      } else result = await api(endpoint, {...payload, revision});
      const oldNodes = flatten(tree.nodes);
      if (endpoint === '/move') {
        const target = payload.target_parent ? payload.target_parent + '/' + payload.source.split('/').pop() : payload.source.split('/').pop();
        for (const node of oldNodes.filter(n => n.kind === 'page' && (n.id === payload.source || n.id.startsWith(payload.source + '/')))) pendingLinks.set(target + node.id.slice(payload.source.length), pendingLinks.has(node.id) ? pendingLinks.get(node.id) : node.url);
      }
      treeGeneration++; tree = result; chooser?.remove(); render(); if (!workspace) watchPublication(result.commit);
      return result;
    } catch (e) {
      if (e.status === 409 && !workspace) { await refresh(); error('Структура уже изменилась. Обновили список; повторите действие.'); }
      else error(e.message);
    } finally { pending = false; nav.removeAttribute('aria-busy'); }
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
  const dragHint = document.createElement('div');
  dragHint.className = 'wiki-tree-drag-hint'; dragHint.hidden = true; dragHint.setAttribute('role', 'status'); nav.append(dragHint);
  function clearDrop() {
    nav.querySelectorAll('[data-drop]').forEach(el => delete el.dataset.drop);
    drop = null; dragHint.hidden = true;
  }
  function finishDrag() {
    clearTimeout(expandTimer); expandId = ''; cancelAnimationFrame(scrollFrame);
    dragging = ''; pointer = null; nav.classList.remove('wiki-tree-dragging');
    nav.querySelectorAll('.wiki-tree-source').forEach(el => el.classList.remove('wiki-tree-source'));
    clearDrop();
  }
  function targetAt(row, node, siblings, event) {
    if (!dragging || dragging === node.id || node.id.startsWith(dragging + '/')) return;
    const rect = row.getBoundingClientRect(), offset = event.clientY - rect.top;
    const edge = Math.min(10, rect.height / 3);
    const where = node.kind === 'folder' && offset > edge && offset < rect.height - edge ? 'inside' : offset < rect.height / 2 ? 'before' : 'after';
    const remaining = siblings.filter(item => item.id !== dragging);
    return {row, node, where, parent: where === 'inside' ? node.id : parentOf(node.id), before: where === 'inside' ? null : where === 'before' ? node.id : remaining[remaining.indexOf(node) + 1]?.id || null};
  }
  function showDrop(target, event) {
    clearDrop();
    if (!target) { clearTimeout(expandTimer); expandId = ''; return; }
    drop = target;
    const marker = target.where === 'after' && target.node?.kind === 'folder' ? target.row.parentElement : target.row;
    marker.dataset.drop = target.where;
    dragHint.textContent = target.node ? `${target.where === 'inside' ? 'В папку' : target.where === 'before' ? 'Перед' : 'После'} «${target.node.title}»` : 'В корень';
    dragHint.hidden = false; dragHint.style.left = `${event.clientX + 14}px`; dragHint.style.top = `${event.clientY + 16}px`;
    const nextExpand = target.where === 'inside' && target.node?.kind === 'folder' && !expanded.has(target.node.id) ? target.node.id : '';
    if (nextExpand !== expandId) {
      clearTimeout(expandTimer); expandId = nextExpand;
      if (nextExpand) expandTimer = setTimeout(() => {
        expanded.add(nextExpand);
        const children = target.row.parentElement.querySelector(':scope > ul');
        if (children) children.hidden = false;
        target.row.querySelector('[aria-expanded]')?.setAttribute('aria-expanded', 'true');
      }, 650);
    }
  }
  function executeDrop() {
    const source = dragging, target = drop;
    finishDrag();
    if (canDrag() && source && target) {
      if (target.where === 'inside' && target.node) expanded.add(target.node.id);
      move(source, target.parent, target.before);
    }
  }
  function dropTarget(row, node, siblings) {
    row.wikiDropTarget = event => targetAt(row, node, siblings, event);
    row.addEventListener('dragover', event => {
      const target = row.wikiDropTarget(event);
      if (!target) return;
      event.preventDefault(); event.stopPropagation(); showDrop(target, event);
    });
    row.addEventListener('drop', event => {
      event.preventDefault(); event.stopPropagation(); showDrop(row.wikiDropTarget(event), event); executeDrop();
    });
  }
  function updatePointer(event) {
    const hit = document.elementFromPoint(event.clientX, event.clientY);
    const row = hit?.closest('.wiki-tree-row');
    const root = hit?.closest('.wiki-tree-root');
    showDrop(row && nav.contains(row) ? row.wikiDropTarget(event) : root && nav.contains(root) ? {row: root, where: 'inside', parent: '', before: null} : null, event);
  }
  function scrollDuringDrag() {
    if (!pointer || !dragging) return;
    const container = nav, bounds = container.getBoundingClientRect();
    const speed = pointer.y < bounds.top + 40 ? -10 : pointer.y > bounds.bottom - 40 ? 10 : 0;
    if (speed) { container.scrollTop += speed; updatePointer({clientX: pointer.x, clientY: pointer.y}); }
    scrollFrame = requestAnimationFrame(scrollDuringDrag);
  }
  nav.addEventListener('pointermove', event => {
    if (!pointer || event.pointerId !== pointer.id) return;
    if (!canDrag()) { finishDrag(); return; }
    pointer.x = event.clientX; pointer.y = event.clientY;
    if (!dragging) {
      if (Math.hypot(event.clientX - pointer.startX, event.clientY - pointer.startY) < 5) return;
      if (!guard()) { finishDrag(); return; }
      dragging = pointer.node.id; nav.classList.add('wiki-tree-dragging'); pointer.row.classList.add('wiki-tree-source');
      nav.setPointerCapture?.(event.pointerId); scrollFrame = requestAnimationFrame(scrollDuringDrag);
    }
    event.preventDefault(); updatePointer(event);
  });
  nav.addEventListener('pointerup', event => {
    if (!pointer || event.pointerId !== pointer.id) return;
    if (dragging) {
      event.preventDefault();
      const suppress = event => { event.preventDefault(); event.stopPropagation(); };
      nav.addEventListener('click', suppress, {capture: true, once: true});
      setTimeout(() => nav.removeEventListener('click', suppress, true), 0);
      executeDrop();
    } else pointer = null;
  });
  nav.addEventListener('pointercancel', event => { if (pointer?.id === event.pointerId) finishDrag(); });
  nav.addEventListener('lostpointercapture', () => { if (pointer) finishDrag(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && pointer) finishDrag(); });
  function list(nodes, depth=0) {
    const ul=document.createElement('ul');ul.className='nav-level'+(!depth?' nav-root':'');
    for(const node of nodes) {
      const li=document.createElement('li');li.className='nav-item'+(node.kind==='folder'?' nav-section':'');li.dataset.nodeId=node.id;
      const row=document.createElement('div');row.className='nav-row wiki-tree-row';row.draggable=false;
      row.addEventListener('pointerdown', event => {
        if (event.button !== 0 || pending || !canDrag()) return;
        pointer = {id: event.pointerId, node, row, startX: event.clientX, startY: event.clientY, x: event.clientX, y: event.clientY};
      });
      row.addEventListener('dragstart',event=>{if(!canDrag() || !guard()){event.preventDefault();return;} dragging=node.id;nav.classList.add('wiki-tree-dragging');event.dataTransfer.setData('text/plain',node.id);event.dataTransfer.effectAllowed='move';});
      row.addEventListener('dragend',finishDrag);
      if(node.kind==='folder') {
        const toggle=button('', 'Раскрыть '+node.title,()=>{expanded.has(node.id)?expanded.delete(node.id):expanded.add(node.id);render();});
        toggle.className='tree-toggle wiki-tree-folder'; toggle.setAttribute('aria-expanded',String(expanded.has(node.id)));
        const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
        for(const [key,value] of Object.entries({class:'icon',width:'20',height:'20',viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.5','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))svg.setAttribute(key,value);
        const chevron=document.createElementNS('http://www.w3.org/2000/svg','path');chevron.setAttribute('d','m9 5 7 7-7 7');svg.append(chevron);
        const label=document.createElement('span');label.textContent=node.title;toggle.append(svg,label);row.append(toggle);
      } else {
        const link=document.createElement('a');link.draggable=false;link.href=node.origin_url || pendingLinks.get(node.id) || node.url;link.textContent=node.title;
        if((node.page_path || node.id)===currentPath())link.setAttribute('aria-current','page');
        if(pendingLinks.has(node.id) && !pendingLinks.get(node.id)) {link.removeAttribute('href');link.setAttribute('aria-disabled','true');link.title='Ожидает публикации';}
        link.addEventListener('click',event=>{if(node.draft_path){event.preventDefault();openPage({draftPath:node.draft_path});return;}if(!link.hasAttribute('href')){event.preventDefault();return;}if(dirty()){event.preventDefault();error('Сначала опубликуйте или отмените правки заметки.');}});row.append(link);
      }
      li.append(row);dropTarget(row,node,nodes);
      if(node.children?.length){const children=list(node.children,depth+1);children.hidden=!expanded.has(node.id);li.append(children);}ul.append(li);
    }return ul;
  }
  function render() {
    if (!tree) return;
    nav.querySelector('.nav-root')?.remove();
    nav.append(list(tree.nodes));
  }
  function mountToolbar() {
    const root=document.createElement('div');root.className='wiki-tree-root';
    root.append(
      iconButton('Новая заметка',['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z','M14 2v6h6','M12 12v6','M9 15h6'],async()=>{if(guard(false)){chooser?.remove();await openPage({parent:'',title:'Новая заметка',slug:''});}}),
      iconButton('Новая папка',['M20 20H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5l2 2h9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2Z','M12 10v6','M9 13h6'],()=>createFolder(root))
    );
    root.addEventListener('dragover',event=>{if(dragging){event.preventDefault();clearDrop();root.dataset.drop='inside';}});
    root.addEventListener('drop',event=>{event.preventDefault();showDrop({row:root,where:'inside',parent:'',before:null},event);executeDrop();});nav.prepend(root);
  }
  mountToolbar();
  const ready = loadTree().then(() => { for(const node of flatten(tree.nodes))if(node.kind==='folder' && currentPath().startsWith(node.id+'/'))expanded.add(node.id);render(); }).catch(e => error(e.message));
  return {refresh, render:()=>{ if (workspace) tree = workspace.tree() || tree; render(); }, reset:()=>{finishDrag();tree=undefined;return refresh();}, revision:()=>tree?.revision, ensureRevision, ready};
}
