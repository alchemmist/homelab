'use strict';
// Local visual mockup only: no network calls, storage, real sessions or tokens.
(() => {
  const query = new URLSearchParams(location.search);
  const scenes = ['lake', 'forest'];
  let scene = query.get('scene') || 'lake';
  if (scene === 'random') scene = scenes[crypto.getRandomValues(new Uint32Array(1))[0] % scenes.length];
  if (!scenes.includes(scene)) scene = 'lake';
  document.documentElement.dataset.scene = scene;
  let locale = query.get('lang') === 'ru' ? 'ru' : 'en';
  const russian = {
    'Sign in': 'Вход', 'Username': 'Логин', 'Password': 'Пароль',
    'Authentication code': 'Код из приложения',
    'Enter any 6 digits. This is a prototype.': 'Введите любые 6 цифр. Это прототип.',
    'Need help signing in?': 'Нужна помощь со входом?', 'Back': 'Назад',
    'Show password': 'Показать пароль', 'Hide password': 'Скрыть пароль',
    'Verify your identity': 'Подтверждение входа', 'Verify code': 'Подтвердить код',
    'Enter a test username and password.': 'Введите тестовые логин и пароль.',
    'Enter any 6 digits to continue the prototype.': 'Для продолжения введите любые 6 цифр.',
    'Prototype: sign-in help will appear here. Nothing is sent.': 'Прототип: здесь будет помощь со входом. Данные не отправляются.',
    'Page tools': 'Инструменты страницы', 'Select language': 'Выбрать язык', 'Language': 'Язык',
    'Open flow inspector': 'Открыть инспектор потока', 'Close flow inspector': 'Закрыть инспектор потока',
    'Flow inspector': 'Инспектор потока',
    'Prototype data. Not a live authentication flow.': 'Демонстрационные данные, не действующий поток авторизации.',
    'Next stage': 'Следующий этап', 'Stage name': 'Название этапа', 'Stage kind': 'Тип этапа',
    'Stage object': 'Объект этапа', 'Plan history': 'История планов',
    'Current plan context': 'Контекст текущего плана', 'Application': 'Приложение',
    'Session ID': 'Идентификатор сессии', 'Show context': 'Показать контекст', 'Show stages': 'Показать этапы',
    'Copy': 'Копировать', 'Copied': 'Скопировано', 'Select text to copy': 'Выделите текст для копирования',
    'Completed': 'Завершён', 'Current': 'Текущий', 'Pending': 'Ожидает',
    'Plan snapshots': 'Снимки планов', 'Identification Stage': 'Этап идентификации',
    'Password Stage': 'Этап пароля', 'Authenticator Validation Stage': 'Проверка второго фактора',
    'Consent Stage': 'Этап согласия', 'OAuth Fulfillment Stage': 'Завершение OAuth',
    'Resolve the account.': 'Определение учётной записи.',
    'Validate the password.': 'Проверка пароля.',
    'Verify the authentication code.': 'Проверка кода второго фактора.',
    'Review application permissions.': 'Подтверждение разрешений приложения.',
    'Return to the application.': 'Возврат в приложение.',
    'Stage details': 'Данные этапа', 'Plan': 'План', 'Sign-in plan': 'План входа', 'Verification plan': 'План подтверждения',
    'Authorization plan': 'План авторизации', 'Redirect preview': 'Предпросмотр перехода',
    'Credentials': 'Учётные данные', 'Authentication code verification': 'Проверка кода',
    'OAuth fulfillment': 'Завершение OAuth', 'Local preview complete': 'Локальный просмотр завершён',
    'Redirecting to Argo CD': 'Переход в Argo CD',
    'You’re about to sign in to Argo CD.': 'Вы собираетесь войти в Argo CD.',
    'The application requests access to:': 'Приложение запрашивает доступ:',
    'Email address': 'Адрес электронной почты', 'General profile information': 'Данные профиля',
    'Not you?': 'Это не вы?', 'Continue': 'Продолжить', 'Back to sign in': 'Вернуться ко входу',
    'Back to consent': 'Назад к разрешениям',
    'Prototype only. No permission was granted and no redirect was made.': 'Это прототип. Разрешения не выданы, переход не выполнялся.'
  };
  const tr = key => locale === 'ru' ? (russian[key] || key) : key;
  const pageKind = document.body.dataset.flowPage;
  let phase = pageKind === 'consent' ? 'consent' : 'credentials';
  const form = document.querySelector('#login-form');
  const password = document.querySelector('#password');
  const username = document.querySelector('#username');
  const code = document.querySelector('#code');
  const reveal = document.querySelector('.reveal');
  const feedback = document.querySelector('.feedback');
  const dialog = document.querySelector('#flow-inspector');
  const inspectorTrigger = document.querySelector('.inspector-trigger');
  const localeTrigger = document.querySelector('.locale-trigger');
  const options = document.querySelector('#language-options');
  let feedbackKey = '';
  const plans = [{name: 'Sign-in plan', stages: ['Identification Stage', 'Password Stage', 'Authenticator Validation Stage']}];
  if (pageKind === 'consent') {
    plans.push({name: 'Verification plan', stages: ['Authenticator Validation Stage', 'Consent Stage']});
    plans.push({name: 'Authorization plan', stages: ['Consent Stage', 'OAuth Fulfillment Stage']});
  }
  function text(element, key) {
    element.dataset.i18n = key;
    element.textContent = tr(key);
  }
  function siblingURL(file) {
    const url = new URL(file, location.href);
    url.search = new URLSearchParams({scene, lang: locale}).toString();
    if (dialog.open) url.searchParams.set('inspector', '1');
    return url.href;
  }
  function updateReveal() {
    if (!reveal) return;
    const visible = password.type === 'text';
    reveal.setAttribute('aria-pressed', String(visible));
    reveal.setAttribute('aria-label', tr(visible ? 'Hide password' : 'Show password'));
  }
  // Reuse the Wiki's Chroma token classes/palette. Build DOM nodes, never HTML from JSON.
  function renderJSON(target, value) {
    const source = JSON.stringify(value, null, 2);
    const tokens = /"(?:\\.|[^"\\])*"(?=\s*:)|"(?:\\.|[^"\\])*"|\b(?:true|false|null)\b|-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b|[{}[\],:]/g;
    target.replaceChildren(); let position = 0;
    for (const match of source.matchAll(tokens)) {
      target.append(document.createTextNode(source.slice(position, match.index)));
      const token = document.createElement('span');
      token.className = match[0].startsWith('"')
        ? (/^\s*:/.test(source.slice(match.index + match[0].length)) ? 'nt' : 's2')
        : /^(true|false|null)$/.test(match[0]) ? 'kc' : /^-?\d/.test(match[0]) ? 'mi' : 'p';
      token.textContent = match[0]; target.append(token); position = match.index + match[0].length;
    }
    target.append(document.createTextNode(source.slice(position)));
  }
  function codeBlock(value, id) {
    const wrapper = document.createElement('div'); wrapper.className = 'code-block hc-content';
    const toolbar = document.createElement('div'); toolbar.className = 'code-toolbar';
    const language = document.createElement('span'); language.textContent = 'JSON';
    const copy = document.createElement('button'); copy.type = 'button';
    copy.dataset.copyTarget = id; copy.dataset.i18n = 'Copy'; copy.textContent = tr('Copy');
    toolbar.append(language, copy);
    const pre = document.createElement('pre'); pre.className = 'chroma';
    const code = document.createElement('code'); code.id = id;
    renderJSON(code, value); pre.append(code); wrapper.append(toolbar, pre); return wrapper;
  }
  function updateInspector() {
    const stages = [
      ['Identification Stage', 'Resolve the account.', 'authentik.stages.identification.IdentificationStage'],
      ['Password Stage', 'Validate the password.', 'authentik.stages.password.PasswordStage'],
      ['Authenticator Validation Stage', 'Verify the authentication code.', 'authentik.stages.authenticator_validate.AuthenticatorValidateStage'],
      ['Consent Stage', 'Review application permissions.', 'authentik.stages.consent.ConsentStage'],
      ['OAuth Fulfillment Stage', 'Return to the application.', 'authentik.providers.oauth2.views.authorize.OAuthFulfillmentStage']
    ];
    const current = {credentials: 1, mfa: 2, consent: 3, redirect: 5}[phase];
    // All statuses are local preview states; completion never means a real grant.
    const next = phase === 'redirect'
      ? ['Local preview complete', '', 'prototype.NoRedirect']
      : stages[Math.min(current + 1, stages.length - 1)];
    document.querySelector('#inspector-stage-name').textContent = phase === 'redirect' ? tr('Local preview complete') : tr(next[0]);
    document.querySelector('#inspector-stage-kind').textContent = phase === 'redirect' ? 'prototype.NoRedirect' : next[2];
    renderJSON(document.querySelector('#inspector-stage-object'), {
      pk: 'prototype-stage', name: next[0], verboseName: next[2], preview: true
    });
    renderJSON(document.querySelector('#inspector-context'), {
      application: 'Argo CD', scopes: ['email', 'profile'], phase,
      session_id: 'prototype-session', preview: true
    });
    const history = document.querySelector('#plan-history'); history.replaceChildren();
    stages.forEach((stage, index) => {
      const status = index < current ? 'completed' : index === current ? 'current' : 'pending';
      const item = document.createElement('li'); item.className = 'pipeline-node'; item.dataset.status = status;
      if (status === 'current') item.setAttribute('aria-current', 'step');
      const marker = document.createElement('span'); marker.className = 'pipeline-marker'; marker.setAttribute('aria-hidden', 'true');
      marker.textContent = status === 'completed' ? '✓' : status === 'current' ? '●' : String(index + 1);
      const body = document.createElement('details'); body.className = 'pipeline-card';
      const header = document.createElement('div'); header.className = 'pipeline-heading';
      const title = document.createElement('p'); title.className = 'plan-title'; title.textContent = tr(stage[0]);
      const badge = document.createElement('span'); badge.className = 'stage-badge';
      badge.textContent = tr({completed: 'Completed', current: 'Current', pending: 'Pending'}[status]);
      header.append(title, badge);
      const description = document.createElement('p'); description.className = 'plan-stage'; description.textContent = tr(stage[1]);
      const summary = document.createElement('summary'); summary.append(header, description);
      body.append(summary, codeBlock({name: stage[0], kind: stage[2], status, preview: true}, `pipeline-json-${index}`));
      item.append(marker, body); history.append(item);
    });
    let snapshots = document.querySelector('#plan-snapshots');
    if (!snapshots) {
      snapshots = document.createElement('details'); snapshots.id = 'plan-snapshots'; snapshots.className = 'plan-snapshots';
      history.after(snapshots);
    }
    snapshots.replaceChildren();
    const summary = document.createElement('summary'); summary.textContent = `${tr('Plan snapshots')} · ${plans.length}`;
    snapshots.append(summary);
    plans.forEach((plan, index) => {
      const title = document.createElement('p'); title.className = 'snapshot-title';
      title.textContent = `${tr('Plan')} ${String(index + 1).padStart(2, '0')} · ${tr(plan.name)}`;
      snapshots.append(title, codeBlock({stages: plan.stages, preview: true}, `snapshot-json-${index}`));
    });
  }
  function applyLocale() {
    document.documentElement.lang = locale;
    for (const el of document.querySelectorAll('[data-i18n]')) el.textContent = tr(el.dataset.i18n);
    for (const el of document.querySelectorAll('[data-i18n-label]')) el.setAttribute('aria-label', tr(el.dataset.i18nLabel));
    for (const el of document.querySelectorAll('[data-i18n-placeholder]')) el.placeholder = tr(el.dataset.i18nPlaceholder);
    document.querySelector('.current-language').textContent = locale === 'ru' ? 'Русский' : 'English';
    for (const button of document.querySelectorAll('[data-locale]')) button.setAttribute('aria-pressed', String(button.dataset.locale === locale));
    for (const link of document.querySelectorAll('.signin-link')) link.href = siblingURL('05-typewriter.html');
    if (feedback) feedback.textContent = tr(feedbackKey);
    document.title = pageKind === 'consent' ? `${tr('Redirecting to Argo CD')} — Socrat / prototype` : `${tr('Sign in')} — Socrat / prototype`;
    updateReveal(); updateInspector();
  }
  function closeLanguages(restoreFocus = false) {
    options.hidden = true; localeTrigger.setAttribute('aria-expanded', 'false');
    if (restoreFocus) localeTrigger.focus({preventScroll: true});
  }
  localeTrigger.addEventListener('click', () => {
    options.hidden = !options.hidden;
    localeTrigger.setAttribute('aria-expanded', String(!options.hidden));
  });
  localeTrigger.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown') {
      event.preventDefault(); options.hidden = false;
      localeTrigger.setAttribute('aria-expanded', 'true'); options.querySelector('button').focus();
    }
  });
  options.addEventListener('keydown', event => {
    const buttons = [...options.querySelectorAll('button')];
    const index = buttons.indexOf(document.activeElement);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault(); buttons[(index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length].focus();
    }
  });
  for (const button of options.querySelectorAll('[data-locale]')) button.addEventListener('click', () => {
    locale = button.dataset.locale; applyLocale(); closeLanguages(true);
  });
  document.addEventListener('click', event => {
    if (!event.target.closest('.locale-picker')) closeLanguages();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !options.hidden) { closeLanguages(true); event.preventDefault(); }
  });
  let inspectorMotion = [];
  let inspectorTransition = 0;
  let inspectorClosing = false;
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  async function setInspectorOpen(open) {
    if (open ? dialog.open && !inspectorClosing : !dialog.open || inspectorClosing) return;
    const revision = ++inspectorTransition;
    const moving = [...document.querySelectorAll('.stage > .glass, .flow-tools')];
    const before = moving.map(element => element.getBoundingClientRect());
    const panelBefore = dialog.open ? dialog.getBoundingClientRect() : null;
    inspectorMotion.forEach(animation => animation.cancel());
    inspectorClosing = !open;
    if (open) {
      closeLanguages(); updateInspector(); dialog.show();
      inspectorTrigger.focus({preventScroll: true});
      inspectorTrigger.setAttribute('aria-expanded', 'true');
      for (const link of document.querySelectorAll('.signin-link')) link.href = siblingURL('05-typewriter.html');
    }
    document.body.classList.toggle('inspector-layout-open', open);
    const after = moving.map(element => element.getBoundingClientRect());
    const panelAfter = dialog.getBoundingClientRect();
    const panelStart = panelBefore
      ? `translate(${panelBefore.left - panelAfter.left}px, ${panelBefore.top - panelAfter.top}px)`
      : 'translateX(100%)';
    if (!reducedMotion.matches) {
      const timing = {duration: 180, easing: 'cubic-bezier(.2,.65,.3,1)'};
      // FLIP keeps the card at its visible position while the final layout is applied.
      // Both transforms start in this frame and share exactly the same timing.
      const panel = dialog.animate([
        {transform: panelStart},
        {transform: open ? 'translateX(0)' : 'translateX(100%)'}
      ], {...timing, fill: 'forwards'});
      const shifts = moving.map((element, index) => element.animate([
        {transform: `translate(${before[index].left - after[index].left}px, ${before[index].top - after[index].top}px)`},
        {transform: 'translate(0, 0)'}
      ], timing));
      inspectorMotion = [panel, ...shifts];
      await Promise.allSettled(inspectorMotion.map(animation => animation.finished));
    }
    if (revision !== inspectorTransition) return;
    if (!open) dialog.close();
    inspectorMotion.forEach(animation => animation.cancel());
    inspectorMotion = [];
    inspectorClosing = false;
  }
  reducedMotion.addEventListener('change', () => {
    if (reducedMotion.matches) inspectorMotion.forEach(animation => animation.finish());
  });
  inspectorTrigger.addEventListener('click', () => setInspectorOpen(!dialog.open || inspectorClosing));
  dialog.addEventListener('cancel', event => {
    event.preventDefault(); setInspectorOpen(false);
  });
  dialog.addEventListener('click', async event => {
    const button = event.target.closest('[data-copy-target]');
    if (!button) return;
    try {
      await navigator.clipboard.writeText(document.getElementById(button.dataset.copyTarget).textContent);
      button.textContent = tr('Copied');
    } catch {
      button.textContent = tr('Select text to copy');
    }
  });
  document.querySelector('.inspector-close').addEventListener('click', () => setInspectorOpen(false));
  // Non-modal: Tab is free to move between the inspector and the login form.
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !event.defaultPrevented && dialog.open) {
      event.preventDefault(); setInspectorOpen(false);
    }
  });
  dialog.addEventListener('close', () => {
    // A queued close event may arrive after the drawer has already reopened.
    if (dialog.open) return;
    ++inspectorTransition;
    inspectorMotion.forEach(animation => animation.cancel());
    inspectorMotion = [];
    inspectorClosing = false;
    document.body.classList.remove('inspector-layout-open');
    inspectorTrigger.setAttribute('aria-expanded', 'false');
    for (const link of document.querySelectorAll('.signin-link')) link.href = siblingURL('05-typewriter.html');
    // Closing diagnostics must not steal focus from a field being edited.
    if (dialog.contains(document.activeElement) || document.activeElement === document.body) {
      inspectorTrigger.focus({preventScroll: true});
    }
  });
  if (form) {
    function showFeedback(key, kind = 'error') {
      feedbackKey = key; feedback.textContent = tr(key); feedback.dataset.kind = kind;
    }
    function reset() {
      phase = 'credentials'; password.value = ''; password.type = 'password'; code.value = '';
      document.querySelector('.credentials').hidden = false; document.querySelector('.mfa').hidden = true;
      document.querySelector('.back').hidden = true;
      text(document.querySelector('h1'), 'Sign in'); text(document.querySelector('.action-label'), 'Sign in');
      showFeedback('');
      for (const input of [username, password, code]) input.removeAttribute('aria-invalid');
      updateReveal(); updateInspector(); username.focus({preventScroll: true});
    }
    reveal.addEventListener('click', () => {
      password.type = password.type === 'password' ? 'text' : 'password'; updateReveal();
    });
    document.querySelector('.back').addEventListener('click', reset);
    document.querySelector('.help').addEventListener('click', () => showFeedback('Prototype: sign-in help will appear here. Nothing is sent.', 'info'));
    for (const input of [username, password, code]) input.addEventListener('input', () => input.removeAttribute('aria-invalid'));
    form.addEventListener('submit', event => {
      event.preventDefault(); showFeedback('');
      if (phase === 'credentials') {
        const missing = !username.value.trim() ? username : !password.value ? password : null;
        if (missing) {
          missing.setAttribute('aria-invalid', 'true'); missing.focus({preventScroll: true});
          showFeedback('Enter a test username and password.'); return;
        }
        password.value = ''; password.type = 'password'; updateReveal(); phase = 'mfa';
        text(document.querySelector('h1'), 'Verify your identity'); text(document.querySelector('.action-label'), 'Verify code');
        document.querySelector('.credentials').hidden = true; document.querySelector('.mfa').hidden = false;
        document.querySelector('.back').hidden = false;
        plans.push({name: 'Verification plan', stages: ['Authenticator Validation Stage', 'Consent Stage']});
        updateInspector(); code.focus({preventScroll: true});
      } else if (phase === 'mfa') {
        if (!/^\d{6}$/.test(code.value)) {
          code.setAttribute('aria-invalid', 'true'); code.focus({preventScroll: true});
          showFeedback('Enter any 6 digits to continue the prototype.'); return;
        }
        code.value = ''; username.value = ''; password.value = '';
        location.href = siblingURL('05-consent.html');
      }
    });
  } else {
    const proceed = document.querySelector('.consent-continue');
    proceed.addEventListener('click', () => {
      const preview = phase === 'consent'; phase = preview ? 'redirect' : 'consent';
      document.querySelector('.consent-content').hidden = preview;
      document.querySelector('.consent-result').hidden = !preview;
      text(proceed.querySelector('[data-i18n]'), preview ? 'Back to consent' : 'Continue');
      if (preview) plans.push({name: 'Redirect preview', stages: ['Local preview complete — no external navigation']});
      updateInspector();
    });
  }
  applyLocale();
  if (query.get('inspector') === '1') setInspectorOpen(true);
})();
