'use strict';
// Offline visual demo: no fetch, telemetry, cookie, credential storage or backend.
const query = new URLSearchParams(location.search);
const scenes = ['lake', 'forest'];
let scene = query.get('scene') || 'lake';
if (scene === 'random') scene = scenes[crypto.getRandomValues(new Uint32Array(1))[0] % scenes.length];
if (scenes.includes(scene)) document.documentElement.dataset.scene = scene;
const form = document.querySelector('#login-form');
const username = document.querySelector('#username');
const password = document.querySelector('#password');
const code = document.querySelector('#code');
const feedback = document.querySelector('.feedback');
const label = document.querySelector('.action-label');
const back = document.querySelector('.back');
const title = document.querySelector('h1');
const originalTitle = title.textContent;
let stage = 'credentials';
document.querySelector('.reveal').addEventListener('click', (event) => {
  const button = event.currentTarget;
  const visible = password.type === 'password';
  password.type = visible ? 'text' : 'password';
  button.setAttribute('aria-pressed', String(visible));
  button.setAttribute('aria-label', visible ? 'Hide password' : 'Show password');
});
function reset() {
  stage = 'credentials'; title.textContent = originalTitle;
  document.querySelector('.credentials').hidden = false;
  document.querySelector('.mfa').hidden = true;
  back.hidden = true; label.textContent = 'Sign in'; feedback.textContent = '';
  form.classList.remove('success'); password.value = ''; code.value = '';
  username.removeAttribute('aria-invalid'); password.removeAttribute('aria-invalid'); code.removeAttribute('aria-invalid');
  username.focus({preventScroll:true});
}
back.addEventListener('click', reset);
document.querySelector('.help').addEventListener('click', () => {
  feedback.textContent = 'Prototype: sign-in help will appear here. Nothing is sent.';
});
form.addEventListener('submit', (event) => {
  event.preventDefault(); feedback.textContent = '';
  if (stage === 'complete') { reset(); return; }
  if (stage === 'credentials') {
    const missing = !username.value.trim() ? username : !password.value ? password : null;
    if (missing) {
      missing.setAttribute('aria-invalid', 'true'); missing.focus({preventScroll:true});
      feedback.textContent = 'Enter a test username and password.'; return;
    }
    // Do not retain even a demo password beyond the first stage.
    password.value = ''; stage = 'mfa'; title.textContent = 'Verify your identity';
    document.querySelector('.credentials').hidden = true;
    document.querySelector('.mfa').hidden = false;
    back.hidden = false; label.textContent = 'Verify'; code.focus({preventScroll:true});
  } else {
    if (!/^\d{6}$/.test(code.value)) {
      code.setAttribute('aria-invalid', 'true'); feedback.textContent = 'Enter any 6 digits to continue the prototype.';
      code.focus({preventScroll:true}); return;
    }
    stage = 'complete'; code.value = ''; title.textContent = 'Verification complete';
    document.querySelector('.mfa').hidden = true; form.classList.add('success');
    feedback.textContent = 'This is a prototype. No data was sent.';
    label.textContent = 'Start over'; back.hidden = true;
  }
});
for (const input of [username, password, code]) input.addEventListener('input', () => input.removeAttribute('aria-invalid'));
