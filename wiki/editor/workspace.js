const flatten = nodes => nodes.flatMap(node => [node, ...flatten(node.children || [])]);
const join = (parent, name) => parent ? parent + '/' + name : name;
const url = path => '/' + path.replace(/(?:^|\/)_(?:index)\.md$/, '/').replace(/\.md$/, '/').replace(/\/index\/$/, '/').replace(/\/+/g, '/');
const remap = (path, source, target) => path === source || path.startsWith(source + '/') ? target + path.slice(source.length) : path;

export function createWorkspace(storage, key = 'socrat-wiki-workspace-v1') {
  let state;
  try { state = JSON.parse(storage.getItem(key)); } catch {}
  if (!state || !Array.isArray(state.drafts)) state = {active:false, drafts:[]};
  state.operations ||= [];
  state.deletedPaths ||= [];
  const commit = next => { storage.setItem(key, JSON.stringify(next)); state = next; };
  const update = change => { const next = structuredClone(state); change(next); commit(next); };
  const nodes = () => flatten(state.tree?.nodes || []);
  const originPath = path => {
    const node = nodes().find(item => item.origin_path === path || item.draft_path === path) || nodes().find(item => item.page_path === path || item.id === path);
    return node?.draft_path || node?.origin_path || path;
  };
  const injectDraft = (next, draft) => {
    if (next.deletedPaths?.includes(draft.path)) return;
    if (!next.tree || !draft.creating || !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(draft.slug || '')) return;
    const all = flatten(next.tree.nodes), existing = all.find(node => node.draft_path === draft.path);
    if (all.some(node => node !== existing && node.origin_path === draft.slug + '.md')) throw new Error('Этот адрес уже принадлежит другой заметке.');
    if (existing) {
      if (existing.creation_slug !== draft.slug) {
        if (existing.creation_locked) throw new Error('Нельзя изменить адрес новой страницы после её перемещения или изменения порядка.');
        const path = draft.slug + '.md';
        if (all.some(node => node !== existing && (node.id === path || node.id === draft.slug))) throw new Error('Страница с таким адресом уже существует.');
        Object.assign(existing,{id:path,path,page_path:path,url:url(path),creation_slug:draft.slug});
      }
      existing.title = draft.title; return;
    }
    const path = draft.slug + '.md';
    if (next.deletedPaths?.includes(path) || next.deletedPaths?.includes(draft.slug)) throw new Error('Этот адрес удалён в текущем черновике. Сначала опубликуйте изменения.');
    if (all.some(node => (node.id === path || node.id === draft.slug))) throw new Error('Страница с таким адресом уже существует.');
    next.tree.nodes.push({id:path,path,page_path:path,draft_path:draft.path,creation_slug:draft.slug,kind:'page',title:draft.title,url:url(path),children:[]});
  };
  return {
    active: () => state.active,
    start() { commit({...state,active:true}); },
    discard() { commit({active:false,drafts:[],operations:[],deletedPaths:[]}); },
    drafts: () => structuredClone(state.drafts),
    get: path => structuredClone(state.drafts.find(draft => draft.path === originPath(path) || draft.path === path)),
    originPath,
    isDeleted: path => state.deletedPaths.includes(path),
    virtualPath(path) { return nodes().find(node => node.origin_path === path || node.draft_path === path)?.page_path || path; },
    tree: () => structuredClone(state.tree),
    slugLocked: path => !!nodes().find(node => node.draft_path === path)?.creation_locked,
    operations: () => structuredClone(state.operations),
    hasChanges: () => !!(state.drafts.length || state.operations.length),
    seedTree(value) {
      if (state.tree && (state.drafts.length || state.operations.length)) return structuredClone(state.tree);
      update(next => {
        next.tree = structuredClone(value);
        for (const node of flatten(next.tree.nodes)) { node.path ||= node.id; node.page_path ||= node.kind === 'folder' ? node.id + '/_index.md' : node.id; node.origin_path = node.page_path; node.origin_url = node.url; }
        for (const draft of next.drafts) injectDraft(next, draft);
      });
      return structuredClone(state.tree);
    },
    stage(operation) {
      update(next => {
        if (!next.tree) throw new Error('Структура wiki ещё не загружена.');
        const op = structuredClone(operation), all = flatten(next.tree.nodes);
        const children = parent => {
          if (!parent) return next.tree.nodes;
          const folder = all.find(node => node.id === parent && node.kind === 'folder');
          if (!folder) throw new Error('Папка не найдена.');
          return folder.children ||= [];
        };
        if (op.type === 'folder') {
          if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(op.slug || '') || !op.title?.trim()) throw new Error('Укажите название и адрес папки.');
          const siblings = children(op.parent), path = join(op.parent, op.slug);
          if (all.some(node => node.id === path || node.page_path === path + '.md')) throw new Error('Этот адрес уже занят.');
          siblings.push({id:path,path,page_path:path + '/_index.md',kind:'folder',title:op.title.trim(),url:url(path + '/_index.md'),children:[]});
        } else if (op.type === 'move') {
          const source = all.find(node => node.id === op.source);
          if (!source) throw new Error('Страница или папка не найдена.');
          if (op.source === op.target_parent || op.target_parent?.startsWith(op.source + '/')) throw new Error('Нельзя переместить папку внутрь себя.');
          const target = join(op.target_parent, op.source.split('/').pop()), siblings = children(op.target_parent);
          const alternate = target.endsWith('.md') ? target.slice(0,-3) : target + '.md';
          if (all.some(node => node !== source && (node.id === target || node.id === alternate))) throw new Error('Этот адрес уже занят.');
          if (op.before === op.source || op.before && !siblings.some(node => node.id === op.before)) throw new Error('Неверное место вставки.');
          for (const node of flatten([source])) if (node.draft_path) node.creation_locked = true;
          const beforeNode = all.find(node => node.id === op.before);
          if (beforeNode?.draft_path) beforeNode.creation_locked = true;
          const remove = list => { const index = list.indexOf(source); if (index >= 0) list.splice(index,1); else for (const node of list) remove(node.children || []); };
          remove(next.tree.nodes);
          for (const node of flatten([source])) {
            node.id = remap(node.id, op.source, target);
            node.path = remap(node.path, op.source, target);
            node.page_path = remap(node.page_path, op.source, target);
            node.url = url(node.page_path);
          }
          siblings.splice(op.before ? siblings.findIndex(node => node.id === op.before) : siblings.length, 0, source);
        } else if (op.type === 'delete') {
          const source = all.find(node => node.id === op.source);
          if (!source) throw new Error('Страница или папка не найдена.');
          for (const node of flatten([source])) {
            for (const path of [node.id, node.page_path, node.origin_path, node.draft_path, node.creation_slug ? node.creation_slug + '.md' : undefined]) {
              if (path && !next.deletedPaths.includes(path)) next.deletedPaths.push(path);
            }
          }
          const remove = list => {
            const index = list.indexOf(source);
            if (index >= 0) list.splice(index,1);
            else for (const node of list) remove(node.children || []);
          };
          remove(next.tree.nodes);
        } else throw new Error('Неизвестное изменение структуры.');
        const weights = list => list.forEach((node,index) => { node.weight = (index+1)*10; weights(node.children || []); });
        weights(next.tree.nodes);
        next.operations.push(op);
      });
      return structuredClone(state.tree);
    },
    put(draft) {
      if (state.deletedPaths.includes(draft.path)) return;
      update(next => {
        const value = structuredClone({...draft,path:originPath(draft.path)});
        const index = next.drafts.findIndex(item => item.path === value.path);
        if (index < 0) next.drafts.push(value);
        else next.drafts[index] = value;
        injectDraft(next, value);
        const node = flatten(next.tree?.nodes || []).find(item => item.origin_path === value.path || item.draft_path === value.path);
        if (node) node.title = value.title;
      });
    },
    remove(path) { commit({...state,drafts:state.drafts.filter(item => item.path !== originPath(path))}); },
    acknowledge(submitted, submittedOperations = state.operations) {
      const drafts = state.drafts.filter(draft => !submitted.some(item => JSON.stringify(item) === JSON.stringify(draft)));
      const matched = JSON.stringify(submittedOperations) === JSON.stringify(state.operations);
      commit({...state,drafts,operations:matched ? [] : state.operations,tree:matched ? undefined : state.tree,deletedPaths:matched ? [] : state.deletedPaths});
    },
    move(source, target) {
      update(next => { for (const draft of next.drafts) if (draft.path === source || draft.path.startsWith(source + '/')) draft.path = target + draft.path.slice(source.length); });
    }
  };
}

export function batchPages(drafts) {
  return drafts.map(({path, original_path, revision, title, body, creating, slug}) => creating ? {section:'',slug,title,body} : {path:original_path || path,revision,title,body});
}
