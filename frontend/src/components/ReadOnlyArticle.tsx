import { useEffect, useRef, useState } from "react";
import { Icon } from "./Icon";
import { copyArticleText, useMarkdownArticle } from "./MarkdownArticle";

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
  const proseRef = useRef<HTMLElement>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const { outline, renderedHtml } = useMarkdownArticle(body);
  useEffect(() => {
    if (copyState === "idle") return;
    const timer = window.setTimeout(() => setCopyState("idle"), 2400);
    return () => window.clearTimeout(timer);
  }, [copyState]);
  const copyBody = async () => {
    try {
      await copyArticleText(proseRef.current?.innerText?.trim() || body || "还没有正文。");
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
  };
  return <div className="dialog-backdrop reader-backdrop" onClick={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <article className="reader-dialog" role="dialog" aria-modal="true" aria-label={`阅读${title}`}>
      <header><div><small>{eyebrow}</small><h2>{title}</h2>{summary && <p>{summary}</p>}</div><div className="reader-header-actions"><span className={`reader-copy-feedback is-${copyState}`} role="status" aria-live="polite">{copyState === "copied" ? "已复制" : copyState === "error" ? "复制失败" : ""}</span><button className={`icon-button reader-copy-action${copyState === "copied" ? " is-copied" : ""}`} aria-label={copyState === "copied" ? "正文已复制" : "复制正文"} title={copyState === "copied" ? "已复制" : "复制正文"} onClick={() => void copyBody()}><Icon name={copyState === "copied" ? "check" : "clipboard"} /></button><button className="icon-button" aria-label="关闭阅读" title="关闭" onClick={onClose}><Icon name="close" /></button></div></header>
      <div className={`reader-body${outline.length ? "" : " without-outline"}`}>
        {outline.length > 0 && <aside aria-label="文章目录"><strong>目录</strong>{outline.map((item) => <a key={item.id} style={{ paddingLeft: `${(item.level - 1) * 10 + 8}px` }} href={`#${item.id}`}>{item.title}</a>)}</aside>}
        <section ref={proseRef} className="reader-prose prose" dangerouslySetInnerHTML={{ __html: renderedHtml }} />
      </div>
    </article>
  </div>;
}
