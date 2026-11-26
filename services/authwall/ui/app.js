const $ = (sel) => document.querySelector(sel);
const jobs = new Map();
let poll = 0;

function openQueue() {
  const panel = $("#save-progress");
  panel.hidden = false;
  panel.dataset.state = "saving";
  $("#dismiss-progress").hidden = true;
  requestAnimationFrame(() => { panel.dataset.open = ""; });
}

function renderQueue() {
  const items = [...jobs.values()];
  $("#queue").innerHTML = items.map((job) => `<li><span>${job.name}</span><span>${job.url ? `<a href="${job.url}" target="_blank" rel="noopener">n8n</a>` : job.state}</span></li>`).join("");
  const pending = items.some((job) => job.state === "sending" || job.state === "processing" || job.state === "uploaded");
  const failed = items.some((job) => job.state === "failed");
  const done = items.length > 0 && items.every((job) => job.state === "ready");
  $("#save-status").textContent = failed ? "Needs attention" : done ? "Ready" : `Processing ${items.filter((job) => job.state !== "ready").length}`;
  if (failed) {
    $("#save-progress").dataset.state = "error";
    $("#notice").textContent = "One upload did not finish. The picture stays in the gallery.";
    $("#dismiss-progress").hidden = false;
  } else if (done) {
    $("#notice").textContent = "";
    $("#save-progress").dataset.state = "success";
    setTimeout(() => {
      delete $("#save-progress").dataset.open;
      setTimeout(() => { $("#save-progress").hidden = true; jobs.clear(); }, 350);
    }, 900);
  } else {
    $("#save-progress").dataset.state = "saving";
  }
  if (pending && !poll) poll = setInterval(refreshJobs, 1500);
  if (!pending && poll) { clearInterval(poll); poll = 0; }
}

async function refreshJobs() {
  const response = await fetch("/authwall/api/items");
  const data = await response.json();
  const byId = new Map(data.items.map((item) => [item.id, item]));
  for (const job of jobs.values()) {
    if (!job.id) continue;
    const row = byId.get(job.id);
    if (row) { job.state = row.status; job.url = row.execution_url || ""; }
  }
  renderQueue();
  draw(data.items);
}

const sharpPending = [];
let sharpRunning = 0;
const upgraded = new Set();
const previews = new Map();

async function upgradeFrame(frame, full) {
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const timer = AbortSignal.timeout(20000);
    try {
      let response = await fetch(full, { signal: timer });
      if (response.status === 404 && /-w\d+\.webp$/.test(full)) response = await fetch(full.replace(/-w\d+\.webp$/, ".webp"), { signal: timer });
      if (!response.ok) throw new Error(String(response.status));
      const blob = await response.blob();
      if (!frame.isConnected) return false;
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.src = url;
      await img.decode();
      const layer = frame.querySelector(".hq");
      if (!layer || !frame.isConnected) return false;
      layer.style.backgroundImage = `url("${url}")`;
      layer.classList.add("shown");
      return true;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 700 * (attempt + 1)));
    }
  }
  return false;
}

function pumpSharp() {
  while (sharpRunning < 4 && sharpPending.length) {
    const [frame, full] = sharpPending.shift();
    const id = frame.closest(".card")?.dataset.id;
    sharpRunning += 1;
    upgradeFrame(frame, full).then((ok) => { if (!ok && id) upgraded.delete(id); }).finally(() => { sharpRunning -= 1; pumpSharp(); });
  }
}

function cardFor(item) {
  const blur = previews.get(item.id) || `/authwall/media/${item.id}-blur.webp?v=2`;
  const button = document.createElement("div");
  button.className = "card";
  button.dataset.id = item.id;
  button.dataset.active = String(item.active);
  button.className = item.active ? "card active" : "card";
  button.innerHTML = `<span class="frame" style="background-image:url('${blur}')"><span class="hq"></span></span><figcaption>${item.filename}<small></small></figcaption>`;
  const tip = document.createElement("span");
  tip.className = "confirm-tip";
  tip.textContent = "Delete forever? This cannot be undone.";
  const trash = document.createElement("button");
  trash.type = "button";
  trash.className = "trash";
  trash.setAttribute("aria-label", "Delete");
  trash.addEventListener("mouseleave", () => { delete button.dataset.confirm; });
  trash.innerHTML = '<svg class="bin" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path fill-rule="evenodd" d="M15.7628 9H7.63719C7.18864 9 6.82501 9.37295 6.82501 9.833V16.5C6.82501 17.8807 7.91632 19 9.26251 19H14.1375C14.784 19 15.404 18.7366 15.8611 18.2678C16.3182 17.7989 16.575 17.163 16.575 16.5V9.833C16.575 9.37295 16.2114 9 15.7628 9Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path fill-rule="evenodd" d="M14.625 7L13.9191 5.553C13.7541 5.21427 13.4167 5.0002 13.0475 5H10.3526C9.98338 5.0002 9.64596 5.21427 9.48092 5.553L8.77502 7H14.625Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M10.8247 12.333C10.8247 11.9188 10.4889 11.583 10.0747 11.583C9.66047 11.583 9.32469 11.9188 9.32469 12.333H10.8247ZM9.32469 15.666C9.32469 16.0802 9.66047 16.416 10.0747 16.416C10.4889 16.416 10.8247 16.0802 10.8247 15.666H9.32469ZM14.0753 12.333C14.0753 11.9188 13.7396 11.583 13.3253 11.583C12.9111 11.583 12.5753 11.9188 12.5753 12.333H14.0753ZM12.5753 15.666C12.5753 16.0802 12.9111 16.416 13.3253 16.416C13.7396 16.416 14.0753 16.0802 14.0753 15.666H12.5753ZM14.625 6.25C14.2108 6.25 13.875 6.58579 13.875 7C13.875 7.41421 14.2108 7.75 14.625 7.75V6.25ZM16.575 7.75C16.9892 7.75 17.325 7.41421 17.325 7C17.325 6.58579 16.9892 6.25 16.575 6.25V7.75ZM8.77501 7.75C9.18923 7.75 9.52501 7.41421 9.52501 7C9.52501 6.58579 9.18923 6.25 8.77501 6.25V7.75ZM6.82501 6.25C6.4108 6.25 6.07501 6.58579 6.07501 7C6.07501 7.41421 6.4108 7.75 6.82501 7.75V6.25ZM9.32469 12.333V15.666H10.8247V12.333H9.32469ZM12.5753 12.333V15.666H14.0753V12.333H12.5753ZM14.625 7.75H16.575V6.25H14.625V7.75ZM8.77501 6.25H6.82501V7.75H8.77501V6.25Z" fill="currentColor"/></svg><svg class="warn" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 2 21h20L12 3Zm1 14h-2v-2h2v2Zm0-4h-2V9h2v4Z"/></svg>';
  button.append(tip, trash);
  return button;
}

function draw(items) {
  $("#empty").hidden = items.length > 0;
  const grid = $("#grid");
  const ids = new Set(items.map((item) => item.id));
  for (const card of [...grid.children]) {
    if (!ids.has(card.dataset.id)) card.remove();
  }
  let anchor = null;
  for (const item of items) {
    let card = grid.querySelector(`[data-id="${item.id}"]`);
    if (!card) {
      card = cardFor(item);
      grid.insertBefore(card, anchor ? anchor.nextSibling : grid.firstChild);
    }
    card.classList.toggle("active", item.active);
    card.dataset.active = String(item.active);
    const note = card.querySelector("small");
    if (note) note.textContent = item.status;
    if (item.status === "ready" && !upgraded.has(item.id)) {
      upgraded.add(item.id);
      const frame = card.querySelector(".frame");
      const needed = Math.max(frame.clientWidth, frame.clientHeight * item.width / item.height) * (window.devicePixelRatio || 1);
      const width = [480, 768, 1280, 1920, 2560].find(w => w >= needed && w < item.width);
      sharpPending.push([frame, `/authwall/media/${item.id}${width ? `-w${width}` : ""}.webp`]);
      pumpSharp();
    }
    anchor = card;
  }
}

async function load() {
  const response = await fetch("/authwall/api/items");
  draw((await response.json()).items);
}

async function upload(files) {
  const list = [...files].filter((file) => file.type.startsWith("image/"));
  if (!list.length) {
    $("#photo-status").textContent = "That was not an image.";
    return;
  }
  openQueue();
  const local = list.map((file) => ({ name: file.name || "pasted", state: "sending", id: "", file }));
  local.forEach((job, index) => jobs.set(`local-${Date.now()}-${index}`, job));
  renderQueue();
  const body = new FormData();
  for (const file of list) body.append("file", file, file.name || "pasted.webp");
  const response = await fetch("/authwall/api/upload", { method: "POST", body });
  if (!response.ok) {
    local.forEach((job) => { job.state = "failed"; });
    renderQueue();
    return;
  }
  const data = await response.json();
  data.ids.forEach((id, index) => {
    local[index].id = id;
    local[index].state = "processing";
    if (local[index].file) previews.set(id, URL.createObjectURL(local[index].file));
  });
  renderQueue();
  refreshJobs();
}

$("#choose").onclick = () => $("#file").click();
$("#file").onchange = () => { if ($("#file").files.length) upload($("#file").files); $("#file").value = ""; };
$("#paste").onclick = async () => {
  try {
    const items = await navigator.clipboard.read();
    const files = [];
    for (const item of items) {
      const type = item.types.find((name) => name.startsWith("image/"));
      if (type) files.push(new File([await item.getType(type)], "pasted", { type }));
    }
    if (!files.length) $("#photo-status").textContent = "Clipboard has no image. Copy the picture, or press Ctrl+V / ⌘V here.";
    else upload(files);
  } catch {
    $("#photo-status").textContent = "Clipboard is blocked. Focus this page and press Ctrl+V / ⌘V.";
  }
};
$(".photo-field").addEventListener("paste", (event) => {
  const files = [...event.clipboardData.files];
  if (files.length) { event.preventDefault(); upload(files); }
});
function placeTip(card) {
  const tip = card.querySelector(".confirm-tip");
  const trash = card.querySelector(".trash");
  if (!tip || !trash) return;
  const box = trash.getBoundingClientRect();
  const width = tip.offsetWidth || 190;
  const height = tip.offsetHeight || 48;
  tip.style.left = Math.max(8, Math.min(box.right - width, window.innerWidth - width - 8)) + "px";
  tip.style.top = Math.max(8, box.top - height - 8) + "px";
}

function closeConfirms(except) {
  document.querySelectorAll(".card[data-confirm]").forEach((card) => {
    if (card !== except) delete card.dataset.confirm;
  });
}

async function removeCard(card) {
  const id = card.dataset.id;
  const response = await fetch(`/authwall/api/items/${id}/delete`, { method: "POST" });
  if (!response.ok) return;
  upgraded.delete(id);
  previews.delete(id);
  card.remove();
  $("#empty").hidden = $("#grid").childElementCount > 0;
}

$("#grid").onclick = (event) => {
  const card = event.target.closest(".card");
  const trash = event.target.closest(".trash");
  if (trash && card) {
    if (card.dataset.confirm === "1") removeCard(card);
    else { closeConfirms(card); card.dataset.confirm = "1"; requestAnimationFrame(() => placeTip(card)); }
    return;
  }
  if (!card) return;
  if (card.dataset.confirm === "1") {
    delete card.dataset.confirm;
    return;
  }
  closeConfirms();
  const active = card.dataset.active !== "true";
  card.dataset.active = String(active);
  card.classList.toggle("active", active);
  fetch(`/authwall/api/items/${card.dataset.id}/active`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ active }),
  });
};
$("#dismiss-progress").onclick = () => {
  delete $("#save-progress").dataset.open;
  setTimeout(() => { $("#save-progress").hidden = true; }, 350);
};
window.addEventListener("scroll", () => { const card = document.querySelector(".card[data-confirm]"); if (card) placeTip(card); }, true);
load();
