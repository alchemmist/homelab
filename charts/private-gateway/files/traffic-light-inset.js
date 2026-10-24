(function () {
  var path = location.pathname;
  if (path !== "/d/socrat-traffic-light" && path.indexOf("/d/socrat-traffic-light/") !== 0) {
    return;
  }
  var id = "socrat-tv-inset";
  function apply() {
    if (!document.getElementById(id)) {
      var style = document.createElement("style");
      style.id = id;
      style.textContent = "[class*=\"body-wrapper\"]{padding:5px !important;box-sizing:border-box !important;}";
      (document.head || document.documentElement).appendChild(style);
    }
    var nodes = document.querySelectorAll('[class*="body-wrapper"]');
    for (var i = 0; i < nodes.length; i++) {
      var chrome = nodes[i].previousElementSibling;
      if (chrome && chrome.style.display !== "none") {
        chrome.style.setProperty("display", "none", "important");
      }
    }
  }
  apply();
  if (!window.__socratTvInset) {
    window.__socratTvInset = new MutationObserver(apply);
    window.__socratTvInset.observe(document.documentElement, {childList: true, subtree: true});
  }
})();
