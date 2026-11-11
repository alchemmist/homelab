(function () {
  var path = location.pathname;
  var publicTv = /^\/public-dashboards\/[a-f0-9]{32}\/?$/.test(path) &&
    /(?:^|&)socratTv=1(?:&|$)/.test(location.search.slice(1));
  if (!publicTv && path !== "/d/socrat-traffic-light" && path.indexOf("/d/socrat-traffic-light/") !== 0) return;
  // Opt in only the saved TV/kiosk URL. Leave normal viewing/editing untouched.
  var authTv = !publicTv && /(?:^|&)kiosk=1(?:&|$)/.test(location.search.slice(1)) &&
    /(?:^|&)autofitpanels=true(?:&|$)/.test(location.search.slice(1)) &&
    !/(?:^|&)(?:editPanel|viewPanel)=/.test(location.search.slice(1));
  var id = "socrat-tv-inset", model = null;
  var legacy = '[class*="body-wrapper"]{padding:5px !important;box-sizing:border-box !important;}';
  function publicRules() {
    if (!model || model.uid !== "socrat-traffic-light" || !model.panels) return "";
    var page = publicTv ? document.querySelector('[data-testid="public-dashboard-scene-page"]') : document;
    if (!page) return "";
    var items = page.querySelectorAll('.react-grid-item[data-griditem-key]');
    if (items.length !== model.panels.length || !items.length) return "";
    var grid = items[0].parentElement, width = parseFloat(grid.style.width) || parseFloat(grid.parentElement.style.width) || grid.clientWidth;
    if (!width) return "";
    var colStep = (width + 8) / 24, positions = [], rows = 0, occupied = {};
    // Capture Grafana's COMPACTED layout, not raw gridPos (which can overlap).
    // Only CSS presentation changes; never touch React internals or dashboard JSON.
    for (var i = 0; i < items.length; i++) {
      var item = items[i], key = item.getAttribute("data-griditem-key");
      if (!/^grid-item-\d+$/.test(key)) return "";
      var move = /translate(?:3d)?\(\s*([-\d.]+)px,\s*([-\d.]+)px/.exec(item.style.transform);
      var panelId = Number(key.replace("grid-item-", "")), panel = null;
      for (var j = 0; j < model.panels.length; j++) if (model.panels[j].id === panelId) panel = model.panels[j];
      if (!move || !panel || !panel.gridPos || !panel.gridPos.h) return "";
      var rowStep = (parseFloat(item.style.height) + 8) / panel.gridPos.h;
      if (!(rowStep > 8)) return "";
      var x = authTv ? panel.gridPos.x : Math.round(Number(move[1]) / colStep);
      var y = authTv ? panel.gridPos.y : Math.round(Number(move[2]) / rowStep);
      var w = authTv ? panel.gridPos.w : Math.round((parseFloat(item.style.width) + 8) / colStep);
      var h = panel.gridPos.h;
      // Authenticated autofit mutates per-panel heights independently. Use the
      // saved grid only when it is integral and collision-free; edit mode is off.
      if (authTv) {
        if (x % 1 || y % 1 || w % 1 || h % 1) return "";
        for (var cy = y; cy < y + h; cy++) for (var cx = x; cx < x + w; cx++) {
          var cell = cx + ":" + cy;
          if (occupied[cell]) return "";
          occupied[cell] = true;
        }
      }
      if (!isFinite(x+y+w+h) || x < 0 || y < 0 || w < 1 || x + w > 24 || h < 1 || y + h > 1000) return "";
      positions.push({key:key,x:x,y:y,w:w,h:h}); rows = Math.max(rows, y + h);
    }
    var gridClass = publicTv ? "socrat-tv-public-grid" : "socrat-tv-auth-grid";
    grid.classList.add(gridClass);
    var css = publicTv ?
      '[data-testid="public-dashboard-scene-page"]{padding:5px!important;box-sizing:border-box!important;}' +
      '[data-testid="public-dashboard-scene-page"]>:first-child,[data-testid="public-dashboard-footer"]{display:none!important;}' +
      '[data-testid="public-dashboard-scene-page"] .react-grid-layout{width:100%!important;height:100%!important;min-height:0!important;}' :
      '[class*="body-wrapper"]{height:100dvh!important;overflow:hidden!important;}' +
      '.socrat-tv-auth-grid{width:100%!important;height:calc(100dvh - 10px)!important;min-height:0!important;}';
    css += '.' + gridClass + '{display:grid!important;grid-template-columns:repeat(24,minmax(0,1fr))!important;grid-template-rows:repeat(' + rows + ',minmax(0,1fr))!important;gap:8px!important;}' +
      '.' + gridClass + '>.react-grid-item{position:relative!important;transform:none!important;width:100%!important;height:100%!important;min-height:0!important;' + (publicTv ? 'pointer-events:none!important;' : '') + '}' +
      '.' + gridClass + '>.react-grid-item>div,.' + gridClass + ' [data-viz-panel-id],.' + gridClass + ' section[data-testid*="Panel header"]{width:100%!important;height:100%!important;}';
    for (i = 0; i < positions.length; i++) {
      var p = positions[i];
      css += '[data-griditem-key="' + p.key + '"]{grid-column:' + (p.x+1) + ' / span ' + p.w + '!important;grid-row:' + (p.y+1) + ' / span ' + p.h + '!important;}';
    }
    return css;
  }
  function compactArgoRules() {
    // Owner-approved exception: public TV only, never normal desktop/edit/kiosk.
    // Grafana subtracts fixed10px gaps BEFORE rendering each bar. Changing margins
    // alone leaves subpixel fills: flex must also redistribute the available width.
    if (!publicTv || !model || model.uid !== "socrat-traffic-light" || !Array.isArray(model.panels)) return "";
    var saved = null;
    for (var i = 0; i < model.panels.length; i++) if (model.panels[i].id === 909) saved = model.panels[i];
    if (!saved || saved.type !== "bargauge" || !saved.options ||
        saved.options.orientation !== "vertical" || saved.options.displayMode !== "gradient" ||
        saved.options.namePlacement !== "hidden" || saved.options.valueMode !== "hidden") return "";
    var root = document.querySelector('.socrat-tv-public-grid [data-viz-panel-id="panel-909"]');
    if (!root || typeof root.querySelector !== "function") return "";
    var content = root.querySelector('[data-testid="data-testid panel content"]');
    var layout = root.querySelector('[data-testid="data-testid viz-layout"]');
    var row = layout && layout.firstElementChild;
    if (!content || !row || row.style.flexDirection !== "row" || !row.children.length) return "";
    var cells = [], fills = [], names = Object.create(null);
    for (i = 0; i < row.children.length; i++) {
      var cell = row.children[i], links = cell.querySelectorAll('a[title]');
      var divs = cell.querySelectorAll('div'), colored = [];
      for (var j = 0; j < divs.length; j++) if (divs[j].style.background || divs[j].style.backgroundColor) colored.push(divs[j]);
      // Fail closed if Grafana changes its DOM: no guessed selectors, fabricated
      // bars, state colors or positional matching against a fixed inventory.
      if (links.length !== 1 || !links[0].title || names[links[0].title] ||
          colored.length !== 1 || colored[0].children.length) return "";
      names[links[0].title] = true; cells.push(cell); fills.push(colored[0]);
    }
    content.classList.add("socrat-tv-argo-content");
    layout.classList.add("socrat-tv-argo-layout");
    row.classList.add("socrat-tv-argo-row");
    for (i = 0; i < cells.length; i++) {
      cells[i].classList.add("socrat-tv-argo-cell");
      fills[i].classList.add("socrat-tv-argo-fill");
    }
    var scope = '.socrat-tv-public-grid [data-viz-panel-id="panel-909"] ';
    return scope + '.socrat-tv-argo-content{padding:3px!important;}' +
      scope + '.socrat-tv-argo-layout{width:100%!important;height:100%!important;}' +
      scope + '.socrat-tv-argo-row{width:100%!important;height:100%!important;gap:2px!important;justify-content:flex-start!important;}' +
      scope + '.socrat-tv-argo-cell{flex:1 1 0!important;min-width:0!important;width:0!important;height:100%!important;margin:0!important;}' +
      scope + '.socrat-tv-argo-cell>div{height:100%!important;}' +
      scope + '.socrat-tv-argo-cell a[data-testid="data-testid Data link"]{flex:1 1 0!important;min-width:0!important;width:100%!important;}' +
      scope + '.socrat-tv-argo-fill{width:100%!important;height:100%!important;}';
  }
  function apply() {
    var style = document.getElementById(id);
    if (!style) { style = document.createElement("style"); style.id = id; (document.head || document.documentElement).appendChild(style); }
    var css = legacy + ((publicTv || authTv) ? publicRules() : "") + compactArgoRules();
    if (style.textContent !== css) style.textContent = css;
    var nodes = document.querySelectorAll('[class*="body-wrapper"]');
    for (var i = 0; i < nodes.length; i++) {
      var chrome = nodes[i].previousElementSibling;
      if (chrome && chrome.style.display !== "none") chrome.style.setProperty("display", "none", "important");
    }
  }
  apply();
  if (!window.__socratTvInset) {
    window.__socratTvInset = new MutationObserver(apply);
    window.__socratTvInset.observe(document.documentElement, {childList:true,subtree:true});
    window.addEventListener("resize", apply);
  }
  if (publicTv || authTv) {
    var request = new XMLHttpRequest();
    request.open("GET", publicTv ? "/api/public/dashboards/" + path.split("/")[2] : "/api/dashboards/uid/socrat-traffic-light");
    request.onload = function () {
      if (request.status !== 200) return;
      try { var data = JSON.parse(request.responseText); if (data.dashboard.uid === "socrat-traffic-light") { model = data.dashboard; apply(); } } catch (_) { /* Native page remains usable; no unsafe fallback. */ }
    };
    request.send();
  }
})();
