import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";
import type { Plot } from "../api/types";
import { useRuntime } from "../api/runtime";
import { useUiStore } from "../state/ui";
import { Icon } from "./Icon";

const renderer = new MarkdownIt({ html: false, linkify: true, breaks: false });

interface Props {
  plot: Plot;
  previous?: Plot;
  next?: Plot;
  onBack: () => void;
  onNavigate: (plotId: string) => void;
  onEdit?: () => void;
}

export function StoryReader({ plot, previous, next, onBack, onNavigate, onEdit }: Props) {
  const { api, project, snapshot } = useRuntime();
  const bodyRef = useRef<HTMLElement>(null);
  const [progress, setProgress] = useState(0);
  const detail = useQuery({
    queryKey: ["entity", project, plot.entityId],
    queryFn: () => api.detail<Plot>(plot.entityId),
    enabled: !snapshot.readonly,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const body = detail.data?.data.body || plot.body || plot.bodyPreview || "_还没有正文。_";
  const outline = useMemo(() => body.split("\n").map((line, index) => {
    const match = /^(#{1,6})\s+(.+)$/.exec(line);
    return match ? { id: `story-heading-${index}`, level: match[1].length, title: match[2] } : null;
  }).filter(Boolean) as Array<{ id: string; level: number; title: string }>, [body]);
  const renderedHtml = useMemo(() => {
    let index = 0;
    const html = DOMPurify.sanitize(renderer.render(body));
    return html.replace(/<h([1-6])>(.*?)<\/h\1>/g, (_match, level, content) => {
      const id = outline[index]?.id || `story-heading-${index}`;
      index += 1;
      return `<h${level} id="${id}">${content}</h${level}>`;
    });
  }, [body, outline]);
  const chapter = snapshot.chapters.find((item) => item.entityId === plot.chapterId)?.label || "未安排篇章";
  const people = plot.people.map((id) => snapshot.characters.find((item) => item.entityId === id)).filter(Boolean);
  const entries = plot.entries.map((id) => snapshot.entries.find((item) => item.entityId === id)).filter(Boolean);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [plot.entityId]);
  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const element = bodyRef.current;
      if (!element) return;
      const rect = element.getBoundingClientRect();
      const top = rect.top + window.scrollY;
      const end = Math.max(top, rect.bottom + window.scrollY - window.innerHeight + 150);
      const atEnd = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2;
      const ratio = atEnd ? 1 : end <= top ? Number(window.scrollY >= top) : (window.scrollY - top + 120) / (end - top);
      setProgress(Math.round(Math.max(0, Math.min(1, ratio)) * 100));
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    update();
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [body]);

  return <section className="workspace-page story-reader-page" aria-label={`阅读${plot.title}`} style={{ "--accent": plot.accent } as React.CSSProperties}>
    <aside className="story-reader-rail" aria-label="剧情阅读辅助信息">
      {outline.length > 0 && <section className="story-reader-rail-section"><small>Contents</small><h2>本章目录</h2><nav aria-label="本章目录">{outline.map((item) => <a key={item.id} className={`level-${item.level}`} href={`#${item.id}`} onClick={(event) => {
        event.preventDefault();
        const target = document.getElementById(item.id);
        if (!target) return;
        const top = target.getBoundingClientRect().top + window.scrollY - 82;
        window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
      }}>{item.title}</a>)}</nav></section>}
      <section className="story-reader-rail-section"><small>Cast</small><h2>出场人物</h2><div className="story-reader-reference-list">{people.length ? people.map((person) => person && <button key={person.entityId} type="button" onClick={() => { useUiStore.getState().selectCharacter(person.entityId); useUiStore.getState().navigate("characters"); }}><span className="avatar" style={{ background: person.gradient || person.color }}>{person.name.slice(0, 1)}</span><span><strong>{person.name}</strong><small>{person.group || "未分组"}</small></span><Icon name="arrow" /></button>) : <p>还没有配置出场人物。</p>}</div></section>
      {entries.length > 0 && <section className="story-reader-rail-section"><small>Entries</small><h2>关联设定</h2><div className="story-reader-reference-list">{entries.map((entry) => entry && <button key={entry.entityId} type="button" onClick={() => { useUiStore.getState().selectEntry(entry.entityId); useUiStore.getState().navigate("entries"); }}><span className="story-reader-entry-symbol" style={{ "--entry-color": entry.accent } as React.CSSProperties}>{entry.name.slice(0, 2)}</span><span><strong>{entry.name}</strong><small>{entry.type}{entry.area ? ` · ${entry.area}` : ""}</small></span><Icon name="arrow" /></button>)}</div></section>}
    </aside>

    <article className="story-reader-article">
      <header>
        <div><small>{chapter} · 第 {plot.sequence} 篇</small><h1>{plot.title}</h1>{plot.summary && <p>{plot.summary}</p>}</div>
        {onEdit && <button className="icon-button" type="button" aria-label={`编辑${plot.title}`} title="编辑剧情" onClick={onEdit}><Icon name="edit" /></button>}
        <div className="story-reader-badges"><span className="story-reader-status">{plot.status || "未标记状态"}</span>{plot.tags.map((tag) => <span key={tag} style={{ borderColor: plot.accent, color: plot.accent }}>{tag}</span>)}{plot.key && <span>重点剧情</span>}{plot.climax && <span>高潮剧情</span>}</div>
      </header>
      {detail.isPending && !plot.body && <p className="story-reader-loading">正在读取完整正文…</p>}
      <section ref={bodyRef} className="story-reader-prose prose" dangerouslySetInnerHTML={{ __html: renderedHtml }} />
    </article>

    <aside className="story-reader-tools" aria-label="阅读导航">
      <header><small>阅读导航</small><strong>{chapter} · 第 {plot.sequence} 篇</strong></header>
      <button className="story-reader-back" type="button" onClick={onBack}><Icon name="arrow" /><span>返回剧情列表</span></button>
      <div className="story-reader-chapter-nav">
        <button type="button" disabled={!previous} onClick={() => previous && onNavigate(previous.entityId)}><span>上一篇</span><strong>{previous?.title || "没有上一篇"}</strong></button>
        <button type="button" disabled={!next} onClick={() => next && onNavigate(next.entityId)}><span>下一篇</span><strong>{next?.title || "没有下一篇"}</strong></button>
      </div>
      <div className="story-reader-progress" role="progressbar" aria-label={`阅读进度 ${progress}%`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
        <span>阅读进度</span><i style={{ "--progress": `${progress}%` } as React.CSSProperties}><b style={{ height: `${progress}%` }} /><strong>{progress}%</strong><strong className="is-inverted" aria-hidden="true">{progress}%</strong></i>
      </div>
    </aside>
  </section>;
}
