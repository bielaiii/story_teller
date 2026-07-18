import { useMemo } from "react";
import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";

const renderer = new MarkdownIt({ html: false, linkify: true, breaks: false });

export function RenderedMarkdown({ source, className = "" }: { source: string; className?: string }) {
  const html = useMemo(() => DOMPurify.sanitize(renderer.render(source)), [source]);
  return <div className={`rendered-markdown prose ${className}`.trim()} dangerouslySetInnerHTML={{ __html: html }} />;
}
