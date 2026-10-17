export function createWorkspace(storage, key = 'socrat-wiki-workspace-v1') {
  let state;
  try { state = JSON.parse(storage.getItem(key)); } catch {}
  if (!state || !Array.isArray(state.drafts)) state = {active:false, drafts:[]};
  const commit = next => { storage.setItem(key, JSON.stringify(next)); state = next; };
  const update = change => { const next = structuredClone(state); change(next); commit(next); };
  return {
    active: () => state.active,
    start() { commit({...state,active:true}); },
    discard() { commit({active:false,drafts:[]}); },
    drafts: () => structuredClone(state.drafts),
    get: path => structuredClone(state.drafts.find(draft => draft.path === path)),
    put(draft) {
      update(next => {
        const index = next.drafts.findIndex(item => item.path === draft.path);
        if (index < 0) next.drafts.push(structuredClone(draft));
        else next.drafts[index] = structuredClone(draft);
      });
    },
    remove(path) { commit({...state,drafts:state.drafts.filter(item => item.path !== path)}); },
    acknowledge(submitted) {
      commit({...state,drafts:state.drafts.filter(draft => !submitted.some(item => JSON.stringify(item) === JSON.stringify(draft)))});
    },
    move(source, target) {
      update(next => { for (const draft of next.drafts) if (draft.path === source || draft.path.startsWith(source + '/')) draft.path = target + draft.path.slice(source.length); });
    }
  };
}

export function batchPages(drafts) {
  return drafts.map(({path, revision, title, body, creating, slug}) => creating ? {section:'',slug,title,body} : {path,revision,title,body});
}
