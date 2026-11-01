'use strict';
const frames = [...document.querySelectorAll('.preview iframe')];
const resize = new ResizeObserver(entries => {
  for (const entry of entries) entry.target.querySelector('iframe').style.transform = `scale(${entry.contentRect.width / 1280})`;
});
for (const frame of frames) resize.observe(frame.parentElement);
for (const button of document.querySelectorAll('[data-scene]')) button.addEventListener('click', () => {
  const scene = button.dataset.scene;
  for (const other of document.querySelectorAll('[data-scene]')) other.setAttribute('aria-pressed', String(other === button));
  for (const frame of frames) frame.src = `${frame.getAttribute('src').split('?')[0]}?scene=${scene}`;
  for (const link of document.querySelectorAll('.variant-link')) link.href = `${link.getAttribute('href').split('?')[0]}?scene=${scene}`;
});
