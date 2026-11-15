document.body.className='folio';const $=s=>document.querySelector(s);
const categoryLabels={'Техника':'Tech','Книги':'Books','Впечатления':'Experiences','Для дома':'Home'};
const seed=[{id:'a',title:'Механическая клавиатура',description:'Компактная, тактильная, без лишнего света. Для длинных текстов и маленьких программ.',price:'≈ 12 000 ₽',category:'Техника',url:'',mark:'',kind:'keys'},{id:'b',title:'Искусство программирования',description:'Бумажный Кнут. Чтобы иногда думать медленнее, чем работает компьютер.',price:'≈ 6 000 ₽',category:'Книги',url:'',mark:'',kind:'book'},{id:'c',title:'Ночь под звёздами',description:'Поездка в обсерваторию. Подальше от городской засветки и поближе к космосу.',price:'Впечатление',category:'Впечатления',url:'',mark:'полярная сова',kind:'star'},{id:'d',title:'Набор для пуровера',description:'Воронка, сервер и утренний ритуал. Ещё один хороший повод сделать паузу.',price:'≈ 4 000 ₽',category:'Для дома',url:'',mark:'',kind:'coffee'}];
let items;try{items=JSON.parse(localStorage.getItem('wishlist-design-v1'))||structuredClone(seed);if(!Array.isArray(items))throw Error();}catch{items=structuredClone(seed);}let selected=null,expectedMark=null;
const drawings={keys:'<rect x="20" y="40" width="160" height="70" rx="6"/><path d="M30 55h140M30 72h140M30 89h140M45 48v42M65 48v42M85 48v42M105 48v42M125 48v42M145 48v42M55 100h90"/>',book:'<path d="M55 22h85v116H55q-14-8 0-16h85M55 22q-14 0-14 14v94M65 22v100M80 50h40M80 62h28"/><circle cx="100" cy="88" r="10"/>',star:'<circle cx="100" cy="76" r="40"/><ellipse cx="100" cy="76" rx="78" ry="18" transform="rotate(-30 100 76)"/><path d="M155 15v20m-10-10h20M32 109v16m-8-8h16"/>',coffee:'<path d="M55 25h90l-33 56H88zM85 84l-25 47h90l-30-47M65 43h70M76 60h47M75 110h60"/><path d="M94 14q-8-9 2-14"/>'};
function el(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}
function safeURL(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:null;}catch{return null;}}
// Sample search links, not endorsements or exact product matches.
const sampleLinks={a:['https://market.yandex.ru/search?text=механическая+клавиатура','https://www.ozon.ru/search/?text=механическая+клавиатура'],b:['https://www.ozon.ru/search/?text=Искусство+программирования','https://www.wildberries.ru/catalog/0/search.aspx?search=Искусство%20программирования'],c:['https://www.planetarium-moscow.ru/'],d:['https://market.yandex.ru/search?text=пуровер','https://www.wildberries.ru/catalog/0/search.aspx?search=пуровер']};
function giftLinks(gift){return Array.isArray(gift.links)?gift.links:gift.url?[gift.url]:(sampleLinks[gift.id]||[]);}
function linkService(value){
 const url=safeURL(value);if(!url)return null;
 const host=new URL(url).hostname.toLowerCase();const matches=domain=>host===domain||host.endsWith('.'+domain);
 if(matches('market.yandex.ru')||matches('market.yandex.com')||matches('market.yandex.kz'))return {url,label:'Yandex Market',symbol:'M',kind:'market'};
 if(matches('wildberries.ru')||matches('wildberries.by')||matches('wildberries.kz')||matches('wildberries.am')||matches('wildberries.kg'))return {url,label:'Wildberries',symbol:'WB',kind:'wb'};
 if(matches('ozon.ru')||matches('ozon.com')||matches('ozon.by')||matches('ozon.kz'))return {url,label:'Ozon',symbol:'Ozon',kind:'ozon'};
 return {url,label:host,symbol:null,kind:'web'};
}
const photoSets=Object.fromEntries(['keys','book','star','coffee'].map(kind=>[kind,(kind==='keys'||kind==='coffee'?[2,1]:[1,2]).map(n=>'assets/photos/'+kind+'-'+n+'.webp')]));
function render(){
 const root=$('#items');root.replaceChildren();
 for(const gift of items){
  const card=el('article',undefined,'gift');
  const figure=el('div',undefined,'drawing');
  const photos=Array.isArray(gift.photos)?gift.photos:(photoSets[gift.kind]||[]);
  if(photos.length){
   let index=0;const img=document.createElement('img');img.className='product-photo';img.loading='lazy';img.decoding='async';
   const controls=el('div',undefined,'gallery-controls');
   const update=()=>{img.src=photos[index];img.alt=gift.title+' — photo '+(index+1);};
   const previous=el('button');previous.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m14 6-6 6 6 6"/></svg>';previous.type='button';previous.setAttribute('aria-label','Previous photo: '+gift.title);previous.onclick=()=>{index=(index+photos.length-1)%photos.length;update();};
   const next=el('button');next.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m10 6 6 6-6 6"/></svg>';next.type='button';next.setAttribute('aria-label','Next photo: '+gift.title);next.onclick=()=>{index=(index+1)%photos.length;update();};
   update();figure.append(img);if(photos.length>1){controls.append(previous,next);figure.append(controls);}
  }
  const content=el('div',undefined,'gift-content');content.append(el('h2',gift.title));
  if(gift.description)content.append(el('p',gift.description,'gift-description'));
  const links=el('div',undefined,'gift-links');const seen=new Set();
  for(const value of giftLinks(gift)){
   const service=linkService(value);if(!service||seen.has(service.url))continue;seen.add(service.url);
   const link=el('a',service.symbol||undefined,'link-badge '+service.kind);link.href=service.url;link.target='_blank';link.rel='noopener noreferrer';link.title=service.label+' — opens in a new tab';link.setAttribute('aria-label',link.title);
   if(service.kind!=='web'){const img=document.createElement('img');img.src='assets/'+service.kind+'.webp?v=3';img.alt='';img.width=34;img.height=34;img.decoding='async';link.replaceChildren(img);}
   if(!service.symbol)link.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><circle cx="12" cy="12" r="8"/><ellipse cx="12" cy="12" rx="3.5" ry="8"/><path d="M4 12h16M6 7.5h12M6 16.5h12"/></svg>';
   links.append(link);
  }
  if(links.childElementCount)content.append(links);
  const control=el('div',undefined,'reservation-control');const toggle=el('button',undefined,'reservation-switch');toggle.type='button';toggle.setAttribute('role','switch');toggle.setAttribute('aria-haspopup','dialog');toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-controls','reserve');toggle.setAttribute('aria-checked',String(!!gift.mark));toggle.setAttribute('aria-label','Reservation: '+gift.title);toggle.dataset.id=gift.id;
  toggle.append(el('span',undefined,'switch-thumb'));toggle.onclick=()=>openReservation(gift,toggle);
  control.append(toggle,el('span',gift.mark?'Reserved':'Available','reservation-status'));
  card.append(figure,content,control);root.append(card);
 }
 attachZoom();
}
let zoomPromise;
function attachZoom(){
 const images=[...document.querySelectorAll('.product-photo')];
 zoomPromise||(zoomPromise=import('./vendor/zoom.js').then(({default:mediumZoom})=>{
  const zoom=mediumZoom({background:'rgba(0, 0, 0, 0.7)',margin:innerWidth<868?25:50,scrollOffset:50});
  zoom.on('open',()=>{document.body.dataset.hcZoomActive='';});
  zoom.on('closed',()=>{delete document.body.dataset.hcZoomActive;});
  addEventListener('resize',()=>zoom.update({margin:innerWidth<868?25:50}));
  return zoom;
 }));
 zoomPromise.then(zoom=>{zoom.detach();images.forEach(img=>img.classList.add('hc-zoom-image'));if(images.length)zoom.attach(images);});
}
let anchor=null;
function positionPopover(){
 if(!anchor||$('#reserve').hidden)return;
 const box=anchor.getBoundingClientRect(), pop=$('#reserve');
 const width=pop.offsetWidth,height=pop.offsetHeight;
 const left=Math.max(12,Math.min(innerWidth-width-12,box.left+box.width/2-width/2));
 const above=box.top-height-12>=12;
 pop.style.left=left+'px';pop.style.top=(above?box.top-height-12:box.bottom+12)+'px';
 pop.classList.toggle('below',!above);pop.style.setProperty('--arrow-left',Math.max(14,Math.min(width-14,box.left+box.width/2-left))+'px');
}
function closePopover(restoreFocus=false){$('#reserve').hidden=true;if(anchor){anchor.setAttribute('aria-expanded','false');if(restoreFocus)anchor.focus();}}
function openReservation(gift,toggle){
 if(anchor===toggle&&!$('#reserve').hidden){closePopover(true);return;}
 closePopover();anchor=toggle;anchor.setAttribute('aria-expanded','true');
 selected=gift.id;expectedMark=gift.mark;$('#reserve-form').reset();$('#name-error').textContent='';$('#name').removeAttribute('aria-invalid');$('#name').setCustomValidity('');
 $('#reservation-heading').textContent=gift.mark?'Release gift':'Reserve gift';
 $('#name-hint').textContent=gift.mark?'Use the same name.':'Remember your name to release.';
 $('#reserve').hidden=false;positionPopover();$('#name').focus({preventScroll:true});
}
$('#reserve-form').onsubmit=event=>{
 event.preventDefault();const input=$('#name');const name=input.value.trim();
 if(!name){$('#name-error').textContent='Please enter a name.';return;}
 const gift=items.find(x=>x.id===selected);if(!gift||gift.mark!==expectedMark){$('#name-error').textContent='Reservation changed. Close and try again.';return;}
 if(gift.mark&&gift.mark!==name){$('#name-error').textContent='Name doesn’t match. Try again.';input.setAttribute('aria-invalid','true');return;}
 const previous=gift.mark;gift.mark=gift.mark?'':name;
 try{localStorage.setItem('wishlist-design-v1',JSON.stringify(items));}catch{gift.mark=previous;$('#name-error').textContent='Unable to save. Please allow browser storage and try again.';return;}
 closePopover();render();const toggle=[...document.querySelectorAll('.reservation-switch')].find(x=>x.dataset.id===selected);toggle?.focus();
};
$('#name').oninput=()=>{$('#name-error').textContent='';$('#name').removeAttribute('aria-invalid');};
document.addEventListener('pointerdown',event=>{if(!$('#reserve').hidden&&!$('#reserve').contains(event.target)&&!anchor?.contains(event.target))closePopover();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('#reserve').hidden){event.preventDefault();closePopover(true);}});
document.addEventListener('focusin',event=>{if(!$('#reserve').hidden&&!$('#reserve').contains(event.target)&&!anchor?.contains(event.target))closePopover();});
window.addEventListener('resize',positionPopover);window.addEventListener('scroll',positionPopover,true);
new ResizeObserver(positionPopover).observe($('#reserve'));

window.addEventListener('storage',event=>{if(event.key==='wishlist-design-v1'){try{const updated=JSON.parse(event.newValue);if(Array.isArray(updated)){closePopover();items=updated;render();}}catch{}}});
render();
