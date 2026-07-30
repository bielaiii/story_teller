import { useMemo } from "react";
import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";
import { Icon } from "./Icon";

const renderer = new MarkdownIt({ html: false, linkify: true, breaks: false });

export function ReadOnlyArticle({
  title,
  eyebrow,
  summary,
  body,
  onClose,
}: {
  title: string;
  eyebrow: string;
  summary?: string;
  body: string;
  onClose: () => void;
}) {
  const html = useMemo(() => DOMPurify.sanitize(renderer.render(body || "_还没有正文。_")), [body]);
  const outline = useMemo(() => body.split("\n").map((line, index) => {
    const match = /^(#{1,6})\s+(.+)$/.exec(line);
    return match ? { id: `reader-heading-${index}`, level: match[1].length, title: match[2] } : null;
  }).filter(Boolean) as Array<{ id: string; level: number; title: string }>, [body]);
  const renderedHtml = useMemo(() => {
    let index = 0;
    return html.replace(/<h([1-6])>(.*?)<\/h\1>/g, (_match, level, content) => {
      const id = outline[index]?.id || `reader-heading-${index}`;
      index += 1;
      return `<h${level} id="${id}">${content}</h${level}>`;
    });
  }, [html, outline]);
  return <div className="dialog-backdrop reader-backdrop" onClick={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <article className="reader-dialog" role="dialog" aria-modal="true" aria-label={`阅读${title}`}>
      <header><div><small>{eyebrow}</small><h2>{title}</h2>{summary && <p>{summary}</p>}</div><button className="icon-button" aria-label="关闭阅读" title="关闭" onClick={onClose}><Icon name="close" /></button></header>
      <div className={`reader-body${outline.length ? "" : " without-outline"}`}>
        {outline.length > 0 && <aside aria-label="文章目录"><strong>目录</strong>{outline.map((item) => <a key={item.id} style={{ paddingLeft: `${(item.level - 1) * 10 + 8}px` }} href={`#${item.id}`}>{item.title}</a>)}</aside>}
        <section className="reader-prose prose" dangerouslySetInnerHTML={{ __html: renderedHtml }} />
      </div>
    </article>
  </div>;
}
