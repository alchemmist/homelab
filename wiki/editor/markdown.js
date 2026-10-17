import StarterKit from '@tiptap/starter-kit';
import { TableKit } from '@tiptap/extension-table';
import { Markdown } from '@tiptap/markdown';

export const extensions = () => [StarterKit.configure({link: {openOnClick: false, autolink: false}}), TableKit.configure({table: {resizable: false}}), Markdown];

export function prepareMarkdown(source) {
  const refs = new Map();
  const prepared = source.replace(/\]\((\{\{<\s*relref\s+"([^"]+)"\s*>\}\})\)/g, (_, original, target) => {
    const href = '/__wiki_relref__/' + refs.size;
    refs.set(href, {original, target});
    return '](' + href + ')';
  });
  const withoutCode = prepared.replace(/^(`{3,}|~{3,}).*\n[\s\S]*?^\1\s*$/gm, '').replace(/`[^`\n]*`/g, '');
  if (/\{\{[<%]|<\/?[A-Za-z][^>]*>|\$[^$\n]+\$|\$\$|\\\(|\\\[|!\[|\[\^[^\]]+\]|^\s*[-*+] \[[ xX]\]/m.test(withoutCode)) {
    throw new Error('Эта заметка содержит специальные вставки, которые редактор пока не поддерживает. Чтобы сохранить их без изменений, отредактируйте исходный Markdown через Git.');
  }
  return {prepared, refs};
}

export function restoreMarkdown(markdown, refs) {
  for (const [href, ref] of refs) markdown = markdown.split('](' + href + ')').join('](' + ref.original + ')');
  return markdown;
}

export function sourceBody(original, initialDocument, currentDocument, generated, refs) {
  return JSON.stringify(initialDocument) === JSON.stringify(currentDocument) ? original : restoreMarkdown(generated, refs);
}
