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
    'Plan': 'План', 'Sign-in plan': 'План входа', 'Verification plan': 'План подтверждения',
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
    return url.href;
  }
  function updateReveal() {
    if (!reveal) return;
    const visible = password.type === 'text';
    reveal.setAttribute('aria-pressed', String(visible));
    reveal.setAttribute('aria-label', tr(visible ? 'Hide password' : 'Show password'));
  }
  function updateInspector() {
    const next = {
      credentials: ['Credentials', 'authentik.stages.password.PasswordStage'],
      mfa: ['Authentication code verification', 'authentik.stages.authenticator_validate.AuthenticatorValidateStage'],
      consent: ['OAuth fulfillment', 'authentik.providers.oauth2.views.authorize.OAuthFulfillmentStage'],
      redirect: ['Local preview complete', 'prototype.NoRedirect']
    }[phase];
    document.querySelector('#inspector-stage-name').textContent = tr(next[0]);
    document.querySelector('#inspector-stage-kind').textContent = next[1];
    document.querySelector('#inspector-stage-object').textContent = JSON.stringify({
      pk: 'prototype-stage', name: next[0], verboseName: next[1], preview: true
    }, null, 2);
    document.querySelector('#inspector-context').textContent = JSON.stringify({
      application: 'Argo CD', scopes: ['email', 'profile'], phase,
      session_id: 'prototype-session', preview: true
    }, null, 2);
    const history = document.querySelector('#plan-history');
    history.replaceChildren();
    plans.forEach((plan, index) => {
      const item = document.createElement('li');
      const name = document.createElement('p'); name.className = 'plan-title';
      name.textContent = `${tr('Plan')} ${String(index + 1).padStart(2, '0')} · ${tr(plan.name)}`;
      const caption = document.createElement('p'); caption.className = 'plan-stage';
      caption.textContent = plan.stages.join(' → ');
      const details = document.createElement('details');
      const summary = document.createElement('summary'); summary.textContent = tr('Show stages');
      const pre = document.createElement('pre'); pre.textContent = JSON.stringify({stages: plan.stages, preview: true}, null, 2);
      details.append(summary, pre); item.append(name, caption, details); history.append(item);
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
  inspectorTrigger.addEventListener('click', () => {
    closeLanguages(); updateInspector(); dialog.showModal(); inspectorTrigger.setAttribute('aria-expanded', 'true');
  });
  document.querySelector('.inspector-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    inspectorTrigger.setAttribute('aria-expanded', 'false'); inspectorTrigger.focus({preventScroll: true});
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
})();
