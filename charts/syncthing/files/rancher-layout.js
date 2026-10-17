(() => {
  if (window.top !== window.self || window.__socratGrafanaAutosize) return;
  window.__socratGrafanaAutosize = true;

  const frames = new Map();
  const selector = '.dashboard-metrics .grafana-graph iframe';
  const dashboardPath = '/services/http:rancher-monitoring-grafana:80/proxy/d/';
  let pending = false;

  function matches(frame) {
    try {
      const url = new URL(frame.src, window.location.href);
      return url.origin === window.location.origin && url.pathname.includes(dashboardPath);
    } catch {
      return false;
    }
  }

  function schedule() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(update);
  }

  function detachDocument(state) {
    state.mutations?.disconnect();
    state.sizes?.disconnect();
    state.document?.removeEventListener('scroll', schedule, true);
    state.document = null;
    state.observed = new Set();
  }

  function attachDocument(frame, state) {
    detachDocument(state);
    try {
      if (!matches(frame)) return;
      const document = frame.contentDocument;
      if (!document?.documentElement) return;
      state.document = document;
      state.mutations = new MutationObserver(schedule);
      state.mutations.observe(document.documentElement, { childList: true, subtree: true });
      state.sizes = new ResizeObserver(schedule);
      document.addEventListener('scroll', schedule, true);
    } catch {
      detachDocument(state);
    }
    schedule();
  }

  function measure(frame, state) {
    if (!frame.getBoundingClientRect().width || !state.document) return null;
    const grids = [...state.document.querySelectorAll('.react-grid-layout')]
      .filter(grid => /^\d+(?:\.\d+)?px$/.test(grid.style.height));
    const footer = state.document.querySelector('a[href*="cnt=kiosk-dashboard"]')?.parentElement;
    const observed = new Set([...grids, ...(footer ? [footer] : [])]);
    for (const grid of grids) {
      for (let ancestor = grid.parentElement; ancestor; ancestor = ancestor.parentElement) {
        observed.add(ancestor);
      }
    }
    for (const element of state.observed) {
      if (!observed.has(element)) state.sizes.unobserve(element);
    }
    for (const element of observed) {
      if (!state.observed.has(element)) state.sizes.observe(element);
    }
    state.observed = observed;
    const footerHeight = footer?.getBoundingClientRect().height || 0;
    let height = 0;
    for (const grid of grids) {
      const bounds = grid.getBoundingClientRect();
      if (!bounds.width) continue;
      let scrollTop = 0;
      for (let ancestor = grid.parentElement; ancestor; ancestor = ancestor.parentElement) {
        scrollTop += ancestor.scrollTop;
      }
      height = Math.max(height, bounds.bottom + scrollTop + footerHeight + 16);
    }
    return height > 0 ? Math.ceil(height) : null;
  }

  function update() {
    pending = false;
    const current = new Set([...document.querySelectorAll(selector)].filter(matches));
    for (const [frame, state] of frames) {
      if (current.has(frame)) continue;
      detachDocument(state);
      state.frameSize.disconnect();
      frame.removeEventListener('load', state.load);
      frames.delete(frame);
    }
    for (const frame of current) {
      if (frames.has(frame)) continue;
      const state = { observed: new Set() };
      state.load = () => attachDocument(frame, state);
      state.frameSize = new ResizeObserver(schedule);
      state.frameSize.observe(frame);
      frame.addEventListener('load', state.load);
      frames.set(frame, state);
      attachDocument(frame, state);
    }
    const heights = new Map();
    for (const [frame, state] of frames) {
      const wrapper = frame.closest('.graphs');
      const height = measure(frame, state);
      if (wrapper && height !== null) heights.set(wrapper, Math.max(heights.get(wrapper) || 0, height));
    }
    for (const [wrapper, height] of heights) {
      if (wrapper.style.height !== `${height}px`) wrapper.style.height = `${height}px`;
    }
  }

  const mutations = new MutationObserver(schedule);
  mutations.observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['src']
  });
  schedule();
})();
