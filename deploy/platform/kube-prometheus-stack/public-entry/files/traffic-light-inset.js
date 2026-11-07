(function () {
  var path = location.pathname;
  var publicTv = /^\/public-dashboards\/[a-f0-9]{32}\/?$/.test(path) &&
    /(?:^|&)socratTv=1(?:&|$)/.test(location.search.slice(1));
  if (!publicTv && path !== "/d/socrat-traffic-light" && path.indexOf("/d/socrat-traffic-light/") !== 0) return;
  var id = "socrat-tv-inset", model = null;
  var legacy = '[class*="body-wrapper"]{padding:5px !important;box-sizing:border-box !important;}';
  function publicRules() {
    if (!model || model.uid !== "socrat-traffic-light" || !model.panels) return "";
    var page = document.querySelector('[data-testid="public-dashboard-scene-page"]');
    if (!page) return "";
    var items = page.querySelectorAll('.react-grid-item[data-griditem-key]');
    if (items.length !== model.panels.length || !items.length) return "";
    var grid = items[0].parentElement, width = parseFloat(grid.style.width) || parseFloat(grid.parentElement.style.width) || grid.clientWidth;
    if (!width) return "";
    var colStep = (width + 8) / 24, positions = [], rows = 0;
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
      var x = Math.round(Number(move[1]) / colStep), y = Math.round(Number(move[2]) / rowStep);
      var w = Math.round((parseFloat(item.style.width) + 8) / colStep), h = panel.gridPos.h;
      if (!isFinite(x+y+w+h) || x < 0 || y < 0 || w < 1 || x + w > 24 || h < 1 || y + h > 1000) return "";
      positions.push({key:key,x:x,y:y,w:w,h:h}); rows = Math.max(rows, y + h);
    }
    grid.classList.add("socrat-tv-public-grid");
    var css = '[data-testid="public-dashboard-scene-page"]{padding:5px!important;box-sizing:border-box!important;}' +
      '[data-testid="public-dashboard-scene-page"]>:first-child,[data-testid="public-dashboard-footer"]{display:none!important;}' +
      '[data-testid="public-dashboard-scene-page"] .react-grid-layout{width:100%!important;height:100%!important;min-height:0!important;}' +
      '.socrat-tv-public-grid{display:grid!important;grid-template-columns:repeat(24,minmax(0,1fr))!important;grid-template-rows:repeat(' + rows + ',minmax(0,1fr))!important;gap:8px!important;}' +
      '.socrat-tv-public-grid>.react-grid-item{position:relative!important;transform:none!important;width:100%!important;height:100%!important;min-height:0!important;pointer-events:none!important;}' +
      '.socrat-tv-public-grid>.react-grid-item>div,.socrat-tv-public-grid [data-viz-panel-id],.socrat-tv-public-grid section[data-testid*="Panel header"]{width:100%!important;height:100%!important;}';
    for (i = 0; i < positions.length; i++) {
      var p = positions[i];
      css += '[data-griditem-key="' + p.key + '"]{grid-column:' + (p.x+1) + ' / span ' + p.w + '!important;grid-row:' + (p.y+1) + ' / span ' + p.h + '!important;}';
    }
    return css;
  }
  function apply() {
    var style = document.getElementById(id);
    if (!style) { style = document.createElement("style"); style.id = id; (document.head || document.documentElement).appendChild(style); }
    var css = legacy + (publicTv ? publicRules() : "");
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
  if (publicTv) {
    var request = new XMLHttpRequest();
    request.open("GET", "/api/public/dashboards/" + path.split("/")[2]);
    request.onload = function () {
      if (request.status !== 200) return;
      try { var data = JSON.parse(request.responseText); if (data.dashboard.uid === "socrat-traffic-light") { model = data.dashboard; apply(); } } catch (_) { /* Native page remains usable; no unsafe fallback. */ }
    };
    request.send();
  }
})();
