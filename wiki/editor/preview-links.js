export function resolvePreviewLinks(html, refs, path) {
  const template = document.createElement('template'); template.innerHTML = html;
  for (const link of template.content.querySelectorAll('a[href]')) {
    const ref = refs.get(link.getAttribute('href'));
    if (!ref) continue;
    const [target, fragment] = ref.target.split('#');
    const base = target.startsWith('/') ? target : '/' + path.split('/').slice(0,-1).concat(target).join('/');
    link.setAttribute('href', target ? base.replace(/(?:_index|index)?\.md$/, '').replace(/\/$/, '') + '/' + (fragment ? '#' + fragment : '') : '#' + fragment);
  }
  return template.innerHTML;
}
