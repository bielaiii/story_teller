import { useMemo } from "react";
import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";

const renderer = new MarkdownIt({ html: false, linkify: true, breaks: false });

export interface MarkdownOutlineItem {
  id: string;
  level: number;
  title: string;
}

export function useMarkdownArticle(body: string, headingPrefix = "reader-heading") {
  const html = useMemo(
    () => DOMPurify.sanitize(renderer.render(body || "_还没有正文。_")),
    [body],
  );
  const outline = useMemo(() => body.split("\n").map((line, index) => {
    const match = /^(#{1,6})\s+(.+)$/.exec(line);
    return match ? { id: `${headingPrefix}-${index}`, level: match[1].length, title: match[2] } : null;
  }).filter(Boolean) as MarkdownOutlineItem[], [body, headingPrefix]);
  const renderedHtml = useMemo(() => {
    let index = 0;
    return html.replace(/<h([1-6])>(.*?)<\/h\1>/g, (_match, level, content) => {
      const id = outline[index]?.id || `${headingPrefix}-${index}`;
      index += 1;
      return `<h${level} id="${id}">${content}</h${level}>`;
    });
  }, [headingPrefix, html, outline]);
  return { outline, renderedHtml };
}

export async function copyArticleText(text: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
  } catch {
    // Clipboard permissions can be denied even on localhost; the focused fallback still works after a click.
  }

  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  field.style.position = "fixed";
  field.style.opacity = "0";
  document.body.append(field);
  field.select();
  const copied = typeof document.execCommand === "function" && document.execCommand("copy");
  field.remove();
  if (!copied) throw new Error("copy failed");
}
