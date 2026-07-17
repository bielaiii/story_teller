import { useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  acceptCompletion,
  autocompletion,
  completionStatus,
  type Completion,
  type CompletionContext,
} from "@codemirror/autocomplete";
import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
  redo,
  redoDepth,
  undo,
  undoDepth,
} from "@codemirror/commands";
import { markdown } from "@codemirror/lang-markdown";
import { EditorState, type Extension } from "@codemirror/state";
import { EditorView, highlightActiveLine, keymap, placeholder } from "@codemirror/view";
import { openSearchPanel, searchKeymap } from "@codemirror/search";
import MarkdownIt from "markdown-it";
import DOMPurify from "dompurify";
import { pinyin } from "pinyin-pro";
import type { Character, Entry } from "../api/types";
import { Icon } from "../components/Icon";

export interface PickedReference {
  entityId: string;
  kind: "character" | "entry";
  label: string;
}

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSave: () => void;
  characters: Character[];
  entries: Entry[];
  onReference?: (reference: PickedReference) => void;
  sourceEntityId?: string;
  label?: string;
  autoFocus?: boolean;
}

export interface ReferenceCandidate {
  entityId: string;
  kind: "character" | "entry";
  label: string;
  detail: string;
  terms: string[];
}

export interface ReferenceQuery {
  trigger: "@" | "/";
  query: string;
  from: number;
  to: number;
}

const renderer = new MarkdownIt({ html: false, linkify: true, breaks: false });

function searchText(value: string): string {
  const full = pinyin(value, { toneType: "none", type: "array" }).join("").toLowerCase();
  const initials = pinyin(value, { pattern: "first", toneType: "none", type: "array" }).join("").toLowerCase();
  return `${value.toLowerCase()} ${full} ${initials}`;
}

function score(candidate: ReferenceCandidate, query: string): number {
  const needle = query.toLowerCase();
  if (!needle) return 1;
  let best = -1;
  for (const term of candidate.terms) {
    const haystack = searchText(term);
    const index = haystack.indexOf(needle);
    if (index >= 0) best = Math.max(best, 1000 - index * 10 - term.length);
  }
  return best;
}

/** Finds an active reference query without treating the trailing slash in a URL as a command. */
export function referenceQueryAt(value: string, position = value.length): ReferenceQuery | null {
  const prefix = value.slice(0, position);
  const match = /[@/][\p{L}\p{N}_-]*$/u.exec(prefix);
  if (!match) return null;
  const trigger = match[0][0] as "@" | "/";
  const from = position - match[0].length;
  if (trigger === "/") {
    const before = prefix.slice(0, from);
    if (/(?:https?|ftp):\/?$/i.test(before) || before.endsWith("/")) return null;
  }
  return { trigger, query: match[0].slice(1), from, to: position };
}

export function filterReferenceCandidates(
  candidates: ReferenceCandidate[],
  context: ReferenceQuery,
  limit = 12,
): ReferenceCandidate[] {
  const kind = context.trigger === "@" ? "character" : "entry";
  return candidates
    .filter((candidate) => candidate.kind === kind)
    .map((candidate) => ({ candidate, rank: score(candidate, context.query) }))
    .filter((item) => item.rank >= 0)
    .sort((left, right) => right.rank - left.rank || left.candidate.label.localeCompare(right.candidate.label, "zh-CN"))
    .slice(0, limit)
    .map((item) => item.candidate);
}

function referencePinyin(candidate: ReferenceCandidate): string {
  const source = candidate.terms[0] || candidate.label;
  return pinyin(source, { toneType: "none", type: "array" }).join(" ");
}

function selectedLineRange(view: EditorView) {
  const selection = view.state.selection.main;
  const first = view.state.doc.lineAt(selection.from);
  const lastPosition = selection.to > selection.from && view.state.doc.lineAt(selection.to).from === selection.to
    ? selection.to - 1
    : selection.to;
  const last = view.state.doc.lineAt(Math.max(selection.from, lastPosition));
  return { from: first.from, to: last.to, selection };
}

function replaceSelectedLines(view: EditorView, transform: (lines: string[]) => string[]) {
  const { from, to } = selectedLineRange(view);
  const replacement = transform(view.state.sliceDoc(from, to).split("\n")).join("\n");
  view.dispatch({
    changes: { from, to, insert: replacement },
    selection: { anchor: from, head: from + replacement.length },
    scrollIntoView: true,
  });
  view.focus();
}

function toggleWrap(view: EditorView, before: string, after = before, fallback = "文字") {
  const range = view.state.selection.main;
  const selected = view.state.sliceDoc(range.from, range.to);
  if (selected.startsWith(before) && selected.endsWith(after) && selected.length >= before.length + after.length) {
    const content = selected.slice(before.length, selected.length - after.length);
    view.dispatch({ changes: { from: range.from, to: range.to, insert: content }, selection: { anchor: range.from, head: range.from + content.length } });
  } else if (
    range.from >= before.length
    && range.to + after.length <= view.state.doc.length
    && view.state.sliceDoc(range.from - before.length, range.from) === before
    && view.state.sliceDoc(range.to, range.to + after.length) === after
  ) {
    view.dispatch({
      changes: [
        { from: range.to, to: range.to + after.length, insert: "" },
        { from: range.from - before.length, to: range.from, insert: "" },
      ],
      selection: { anchor: range.from - before.length, head: range.to - before.length },
    });
  } else {
    const content = selected || fallback;
    view.dispatch({
      changes: { from: range.from, to: range.to, insert: `${before}${content}${after}` },
      selection: { anchor: range.from + before.length, head: range.from + before.length + content.length },
      scrollIntoView: true,
    });
  }
  view.focus();
}

function toggleLinePrefix(
  view: EditorView,
  matcher: RegExp,
  add: (line: string, index: number) => string,
) {
  replaceSelectedLines(view, (lines) => {
    const content = lines.filter((line) => line.trim());
    const remove = content.length > 0 && content.every((line) => matcher.test(line));
    return lines.map((line, index) => !line.trim() ? line : remove ? line.replace(matcher, "$1") : add(line, index));
  });
}

function setHeading(view: EditorView, level: number) {
  const prefix = `${"#".repeat(level)} `;
  replaceSelectedLines(view, (lines) => {
    const content = lines.filter((line) => line.trim());
    const remove = content.length > 0 && content.every((line) => line.startsWith(prefix));
    return lines.map((line) => {
      if (!line.trim()) return line;
      const plain = line.replace(/^#{1,6}\s+/, "");
      return remove ? plain : `${prefix}${plain}`;
    });
  });
}

function insertLink(view: EditorView) {
  const range = view.state.selection.main;
  const selected = view.state.sliceDoc(range.from, range.to) || "链接文字";
  const replacement = `[${selected}](https://)`;
  const urlFrom = range.from + selected.length + 3;
  view.dispatch({
    changes: { from: range.from, to: range.to, insert: replacement },
    selection: { anchor: urlFrom, head: urlFrom + 8 },
    scrollIntoView: true,
  });
  view.focus();
}

function headingsIn(view: EditorView) {
  const headings: Array<{ line: number; from: number; title: string; level: number }> = [];
  for (let number = 1; number <= view.state.doc.lines; number += 1) {
    const line = view.state.doc.line(number);
    const match = /^(#{1,6})\s+(.+)$/.exec(line.text);
    if (match) headings.push({ line: number, from: line.from, title: match[2].trim(), level: match[1].length });
  }
  return headings;
}

function jumpHeading(view: EditorView, direction: -1 | 1) {
  const headings = headingsIn(view);
  if (!headings.length) return false;
  const caret = view.state.selection.main.head;
  let target = direction > 0 ? headings.find((heading) => heading.from > caret) : undefined;
  if (direction < 0) {
    for (let index = headings.length - 1; index >= 0; index -= 1) {
      if (headings[index].from < caret) { target = headings[index]; break; }
    }
  }
  target ||= direction > 0 ? headings[0] : headings[headings.length - 1];
  view.dispatch({ selection: { anchor: target.from }, scrollIntoView: true });
  view.focus();
  return true;
}

function ToolButton({
  label,
  icon,
  action,
  pressed,
  disabled,
  primary,
}: {
  label: string;
  icon: Parameters<typeof Icon>[0]["name"];
  action: () => void;
  pressed?: boolean;
  disabled?: boolean;
  primary?: boolean;
}) {
  return <button
    type="button"
    className={primary ? "is-primary" : undefined}
    title={label}
    aria-label={label}
    aria-pressed={pressed}
    disabled={disabled}
    onClick={action}
  ><Icon name={icon} /></button>;
}

export function MarkdownEditor({
  value,
  onChange,
  onSave,
  characters,
  entries,
  onReference,
  sourceEntityId,
  label = "正文",
  autoFocus = false,
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const referenceCommandRef = useRef<HTMLElement>(null);
  const moreToolsRef = useRef<HTMLSpanElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const saveRef = useRef(onSave);
  const changeRef = useRef(onChange);
  const pickRef = useRef(onReference);
  const candidatesRef = useRef<ReferenceCandidate[]>([]);
  const syncingRef = useRef<"editor" | "preview" | null>(null);
  const commandSelectionRef = useRef({ from: 0, to: 0 });
  const [immersive, setImmersive] = useState(false);
  const [showPreview, setShowPreview] = useState(true);
  const [showOutline, setShowOutline] = useState(true);
  const [showMoreTools, setShowMoreTools] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [cursorLine, setCursorLine] = useState(1);
  const [historyState, setHistoryState] = useState({ undo: false, redo: false });
  const [announcement, setAnnouncement] = useState("");
  const [referenceCommand, setReferenceCommand] = useState<{
    trigger: "@" | "/";
    query: string;
    activeIndex: number;
  } | null>(null);

  saveRef.current = onSave;
  changeRef.current = onChange;
  pickRef.current = onReference;
  candidatesRef.current = [
    ...characters.map((item) => ({
      entityId: item.entityId,
      kind: "character" as const,
      label: item.name,
      detail: `人物 · ${item.characterScope}`,
      terms: [item.name, ...item.aliases],
    })),
    ...entries.map((item) => ({
      entityId: item.entityId,
      kind: "entry" as const,
      label: item.name,
      detail: `${item.type}${item.subtype ? ` · ${item.subtype}` : ""}`,
      terms: [item.name, ...item.aliases],
    })),
  ].filter((item) => item.entityId !== sourceEntityId);

  const commandResults = referenceCommand
    ? filterReferenceCandidates(candidatesRef.current, {
      trigger: referenceCommand.trigger,
      query: referenceCommand.query,
      from: 0,
      to: 0,
    })
    : [];
  const openReferenceCommand = (trigger: "@" | "/") => {
    const view = viewRef.current;
    if (!view) return;
    const selection = view.state.selection.main;
    commandSelectionRef.current = { from: selection.from, to: selection.to };
    setReferenceCommand({ trigger, query: "", activeIndex: 0 });
  };
  const closeReferenceCommand = () => {
    setReferenceCommand(null);
    requestAnimationFrame(() => viewRef.current?.focus());
  };
  const insertCommandResult = (index: number) => {
    const candidate = commandResults[index];
    const view = viewRef.current;
    if (!candidate || !view) return;
    const range = commandSelectionRef.current;
    view.dispatch({
      changes: { from: range.from, to: range.to, insert: candidate.label },
      selection: { anchor: range.from + candidate.label.length },
      scrollIntoView: true,
    });
    pickRef.current?.({ entityId: candidate.entityId, kind: candidate.kind, label: candidate.label });
    setAnnouncement(`已插入${candidate.kind === "character" ? "人物" : "设定"}：${candidate.label}`);
    closeReferenceCommand();
  };

  const completionSource = (context: CompletionContext) => {
    if (context.state.readOnly) return null;
    const reference = referenceQueryAt(context.state.doc.toString(), context.pos);
    if (!reference || reference.to !== context.pos) return null;
    const matches = filterReferenceCandidates(candidatesRef.current, reference);
    const options: Completion[] = matches.map((candidate) => ({
      label: candidate.label,
      detail: `${candidate.detail} · ${referencePinyin(candidate)}`,
      type: candidate.kind === "character" ? "variable" : "property",
      apply: (view, _completion, from, to) => {
        const triggerFrom = Math.max(0, from - 1);
        view.dispatch({
          changes: { from: triggerFrom, to, insert: candidate.label },
          selection: { anchor: triggerFrom + candidate.label.length },
        });
        pickRef.current?.({ entityId: candidate.entityId, kind: candidate.kind, label: candidate.label });
        setAnnouncement(`已插入${candidate.kind === "character" ? "人物" : "设定"}：${candidate.label}`);
      },
    }));
    // CodeMirror tracks `validFor` from `from`, so keep the trigger outside the
    // completion range. This lets a popup opened by `@` or `/` stay active while
    // physical pinyin letters are inserted, while `apply` still replaces the
    // complete trigger + query.
    return { from: reference.from + 1, options, validFor: /^[\p{L}\p{N}_-]*$/u, filter: false };
  };

  useLayoutEffect(() => {
    if (!hostRef.current || viewRef.current) return;
    const extensions: Extension[] = [
      history(),
      markdown(),
      EditorView.lineWrapping,
      highlightActiveLine(),
      EditorView.theme({
        "&": { backgroundColor: "transparent", color: "var(--ink)" },
        ".cm-content": { caretColor: "var(--primary)" },
        ".cm-cursor": { borderLeftColor: "var(--primary)", borderLeftWidth: "2px" },
        ".cm-activeLine": { backgroundColor: "rgba(42, 157, 143, .055)" },
        ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": { backgroundColor: "rgba(63, 127, 193, .16)" },
      }),
      placeholder("从这里开始写……"),
      autocompletion({
        override: [completionSource],
        activateOnTyping: true,
        closeOnBlur: false,
        interactionDelay: 0,
      }),
      keymap.of([
        { key: "Mod-s", preventDefault: true, run: () => { saveRef.current(); return true; } },
        { key: "Mod-b", preventDefault: true, run: (view) => { toggleWrap(view, "**", "**", "加粗文字"); return true; } },
        { key: "Mod-i", preventDefault: true, run: (view) => { toggleWrap(view, "*", "*", "斜体文字"); return true; } },
        { key: "Mod-e", preventDefault: true, run: (view) => { toggleWrap(view, "`", "`", "代码"); return true; } },
        { key: "Mod-k", preventDefault: true, run: (view) => { insertLink(view); return true; } },
        { key: "Mod-h", preventDefault: true, run: (view) => openSearchPanel(view) },
        { key: "Mod-Alt-1", preventDefault: true, run: (view) => { setHeading(view, 1); return true; } },
        { key: "Mod-Alt-2", preventDefault: true, run: (view) => { setHeading(view, 2); return true; } },
        { key: "Mod-Alt-3", preventDefault: true, run: (view) => { setHeading(view, 3); return true; } },
        { key: "Mod-Shift-8", preventDefault: true, run: (view) => { toggleLinePrefix(view, /^(\s*)[-*+]\s+/, (line) => line.replace(/^(\s*)/, "$1- ")); return true; } },
        { key: "Mod-Shift-7", preventDefault: true, run: (view) => { toggleLinePrefix(view, /^(\s*)\d+[.)、]\s+/, (line, index) => line.replace(/^(\s*)/, `$1${index + 1}. `)); return true; } },
        { key: "Mod-Shift-q", preventDefault: true, run: (view) => { toggleLinePrefix(view, /^(\s*)>\s?/, (line) => line.replace(/^(\s*)/, "$1> ")); return true; } },
        { key: "Mod-Shift-p", preventDefault: true, run: () => { setShowPreview((current) => !current); return true; } },
        { key: "Mod-Shift-f", preventDefault: true, run: () => { setImmersive((current) => !current); return true; } },
        { key: "Alt-m", preventDefault: true, run: () => { openReferenceCommand("@"); return true; } },
        { key: "Alt-/", preventDefault: true, run: () => { openReferenceCommand("/"); return true; } },
        { key: "Alt-ArrowUp", preventDefault: true, run: (view) => jumpHeading(view, -1) },
        { key: "Alt-ArrowDown", preventDefault: true, run: (view) => jumpHeading(view, 1) },
        { key: "F1", preventDefault: true, run: () => { setShowHelp(true); return true; } },
        { key: "Space", run: (view) => completionStatus(view.state) === "active" && acceptCompletion(view) },
        indentWithTab,
        ...defaultKeymap,
        ...historyKeymap,
        ...searchKeymap,
      ]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) changeRef.current(update.state.doc.toString());
        if (update.docChanged || update.selectionSet) {
          const line = update.state.doc.lineAt(update.state.selection.main.head).number;
          setCursorLine((current) => current === line ? current : line);
          const nextHistory = { undo: undoDepth(update.state) > 0, redo: redoDepth(update.state) > 0 };
          setHistoryState((current) => current.undo === nextHistory.undo && current.redo === nextHistory.redo ? current : nextHistory);
        }
      }),
      EditorView.domEventHandlers({
        scroll: (_event, view) => {
          if (syncingRef.current === "preview" || !previewRef.current) return;
          syncingRef.current = "editor";
          const scroller = view.scrollDOM;
          const ratio = scroller.scrollTop / Math.max(1, scroller.scrollHeight - scroller.clientHeight);
          previewRef.current.scrollTop = ratio * Math.max(0, previewRef.current.scrollHeight - previewRef.current.clientHeight);
          requestAnimationFrame(() => { syncingRef.current = null; });
        },
      }),
    ];
    viewRef.current = new EditorView({
      state: EditorState.create({ doc: value, extensions }),
      parent: hostRef.current,
    });
    if (autoFocus) viewRef.current.focus();
    return () => {
      viewRef.current?.destroy();
      viewRef.current = null;
    };
    // Completion and callbacks read live refs, so remounting would unnecessarily lose editor history.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const view = viewRef.current;
    if (!view || view.state.doc.toString() === value) return;
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } });
  }, [value]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (showMoreTools) setShowMoreTools(false);
      else if (immersive && !showHelp) setImmersive(false);
    };
    // CodeMirror consumes Escape while closing completion/search UI. Listen in
    // capture phase so the same key can always leave the editor's immersive shell.
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [immersive, showHelp, showMoreTools]);

  useEffect(() => {
    if (!showMoreTools) return;
    const close = (event: PointerEvent) => {
      if (!moreToolsRef.current?.contains(event.target as Node)) setShowMoreTools(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [showMoreTools]);

  useEffect(() => { viewRef.current?.requestMeasure(); }, [immersive, showOutline, showPreview]);

  useEffect(() => {
    if (!referenceCommand) return;
    requestAnimationFrame(() => referenceCommandRef.current?.focus());
  }, [Boolean(referenceCommand)]);

  const deferredPreviewValue = useDeferredValue(value);
  const previewHtml = useMemo(
    () => DOMPurify.sanitize(renderer.render(deferredPreviewValue || "_正文预览会显示在这里。_")),
    [deferredPreviewValue],
  );
  const outline = useMemo(() => value.split("\n").map((line, index) => {
    const match = /^(#{1,6})\s+(.+)$/.exec(line);
    return match ? { line: index + 1, level: match[1].length, title: match[2] } : null;
  }).filter(Boolean) as Array<{ line: number; level: number; title: string }>, [value]);
  const activeHeadingLine = outline.filter((item) => item.line <= cursorLine).at(-1)?.line;
  const counts = useMemo(() => {
    const compact = value.trim();
    return {
      characters: compact.replace(/\s/g, "").length,
      paragraphs: compact ? compact.split(/\n\s*\n/).length : 0,
    };
  }, [value]);
  const primaryKey = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "⌘" : "Ctrl";

  const run = (action: (view: EditorView) => unknown) => {
    const view = viewRef.current;
    if (view) action(view);
  };
  const scrollToLine = (number: number) => {
    const view = viewRef.current;
    if (!view) return;
    const line = view.state.doc.line(Math.min(number, view.state.doc.lines));
    view.dispatch({ selection: { anchor: line.from }, scrollIntoView: true });
    view.focus();
  };
  const previewScroll = () => {
    const view = viewRef.current;
    const preview = previewRef.current;
    if (!view || !preview || syncingRef.current === "editor") return;
    syncingRef.current = "preview";
    const ratio = preview.scrollTop / Math.max(1, preview.scrollHeight - preview.clientHeight);
    view.scrollDOM.scrollTop = ratio * Math.max(0, view.scrollDOM.scrollHeight - view.scrollDOM.clientHeight);
    requestAnimationFrame(() => { syncingRef.current = null; });
  };

  return (
    <section className={`markdown-workspace${immersive ? " is-immersive" : ""}${showPreview ? "" : " preview-hidden"}${showOutline ? "" : " outline-hidden"}`}>
      <header className="editor-toolbar" aria-label="编辑器快捷工具">
        <div className="editor-toolbar-context"><span className="editor-label">{label}</span><small>第 {cursorLine} 行 · {counts.characters} 字 · {counts.paragraphs} 段</small></div>
        <div className="editor-tools" role="toolbar" onPointerDown={(event) => {
          if ((event.target as HTMLElement).closest("button")) event.preventDefault();
        }}>
          <span className="editor-tool-group" aria-label="撤销与恢复">
            <ToolButton label={`撤销（${primaryKey}+Z）`} icon="undo" disabled={!historyState.undo} action={() => run(undo)} />
            <ToolButton label={`重做（${primaryKey}+Shift+Z）`} icon="redo" disabled={!historyState.redo} action={() => run(redo)} />
          </span>
          <span className="editor-tool-group" aria-label="Markdown 格式">
            <ToolButton label={`加粗（${primaryKey}+B）`} icon="bold" action={() => run((view) => toggleWrap(view, "**", "**", "加粗文字"))} />
            <ToolButton label={`斜体（${primaryKey}+I）`} icon="italic" action={() => run((view) => toggleWrap(view, "*", "*", "斜体文字"))} />
            <ToolButton label={`二级标题（${primaryKey}+Alt+2）`} icon="heading" action={() => run((view) => setHeading(view, 2))} />
            <ToolButton label={`无序列表（${primaryKey}+Shift+8）`} icon="bullet" action={() => run((view) => toggleLinePrefix(view, /^(\s*)[-*+]\s+/, (line) => line.replace(/^(\s*)/, "$1- ")))} />
          </span>
          <span className="editor-tool-group" aria-label="智能引用">
            <ToolButton label="人物拼音检索（@ / Alt+M）" icon="person" action={() => openReferenceCommand("@")} />
            <ToolButton label="设定拼音检索（/ / Alt+/）" icon="book" action={() => openReferenceCommand("/")} />
          </span>
          <span className="editor-tool-group" aria-label="视图与保存">
            <ToolButton label="切换正文目录" icon="sidebar" pressed={showOutline} action={() => setShowOutline((current) => !current)} />
            <ToolButton label={`切换预览（${primaryKey}+Shift+P）`} icon="preview" pressed={showPreview} action={() => setShowPreview((current) => !current)} />
            <ToolButton label={immersive ? `退出沉浸模式（Esc / ${primaryKey}+Shift+F）` : `进入沉浸模式（${primaryKey}+Shift+F）`} icon={immersive ? "collapse" : "expand"} pressed={immersive} action={() => setImmersive((current) => !current)} />
            <span className="editor-more-tools" ref={moreToolsRef}>
              <ToolButton label="更多编辑工具" icon="more" pressed={showMoreTools} action={() => setShowMoreTools((current) => !current)} />
              {showMoreTools && <span className="editor-more-popover" role="toolbar" aria-label="更多编辑工具">
                <ToolButton label={`有序列表（${primaryKey}+Shift+7）`} icon="numbered" action={() => run((view) => toggleLinePrefix(view, /^(\s*)\d+[.)、]\s+/, (line, index) => line.replace(/^(\s*)/, `$1${index + 1}. `)))} />
                <ToolButton label={`引用（${primaryKey}+Shift+Q）`} icon="quote" action={() => run((view) => toggleLinePrefix(view, /^(\s*)>\s?/, (line) => line.replace(/^(\s*)/, "$1> ")))} />
                <ToolButton label={`行内代码（${primaryKey}+E）`} icon="code" action={() => run((view) => toggleWrap(view, "`", "`", "代码"))} />
                <ToolButton label={`链接（${primaryKey}+K）`} icon="link" action={() => run(insertLink)} />
                <ToolButton label="上一个标题（Alt+↑）" icon="up" action={() => run((view) => jumpHeading(view, -1))} />
                <ToolButton label="下一个标题（Alt+↓）" icon="down" action={() => run((view) => jumpHeading(view, 1))} />
                <ToolButton label={`查找与替换（${primaryKey}+F / ${primaryKey}+H）`} icon="replace" action={() => run(openSearchPanel)} />
                <ToolButton label="快捷键帮助（F1）" icon="help" action={() => setShowHelp(true)} />
              </span>}
            </span>
            <ToolButton label={`保存（${primaryKey}+S）`} icon="save" primary action={onSave} />
          </span>
        </div>
      </header>
      <div className="editor-body">
        <aside className="editor-outline" aria-label="正文目录">
          <strong>目录</strong>
          {outline.length ? outline.map((item) => (
            <button
              key={`${item.line}-${item.title}`}
              className={activeHeadingLine === item.line ? "is-active" : undefined}
              style={{ paddingLeft: `${(item.level - 1) * 10 + 8}px` }}
              onClick={() => scrollToLine(item.line)}
            >{item.title}</button>
          )) : <small>使用 Markdown 标题后会显示目录</small>}
        </aside>
        <section className="editor-pane editor-source-pane"><header><span>源码</span><small>Markdown</small></header><div className="codemirror-host" ref={hostRef} /></section>
        <section className="editor-pane editor-preview-pane"><header><span>预览</span><small>同步滚动</small></header><article
            className="markdown-preview prose"
            ref={previewRef}
            onScroll={previewScroll}
            dangerouslySetInnerHTML={{ __html: previewHtml }}
          /></section>
      </div>
      {referenceCommand && <div className="reference-command-backdrop" role="presentation" onMouseDown={(event) => {
        if (event.target === event.currentTarget) closeReferenceCommand();
      }}>
        <section
          className="reference-command"
          ref={referenceCommandRef}
          role="dialog"
          aria-modal="true"
          aria-label={referenceCommand.trigger === "@" ? "人物拼音检索" : "设定拼音检索"}
          tabIndex={-1}
          onKeyDown={(event) => {
            const physicalLetter = /^Key([A-Z])$/.exec(event.code)?.[1].toLowerCase();
            if (physicalLetter && !event.metaKey && !event.ctrlKey && !event.altKey) {
              event.preventDefault();
              setReferenceCommand((current) => current ? { ...current, query: current.query + physicalLetter, activeIndex: 0 } : current);
            } else if (event.key === "Backspace") {
              event.preventDefault();
              setReferenceCommand((current) => current ? { ...current, query: current.query.slice(0, -1), activeIndex: 0 } : current);
            } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              const direction = event.key === "ArrowDown" ? 1 : -1;
              setReferenceCommand((current) => current ? {
                ...current,
                activeIndex: commandResults.length
                  ? (current.activeIndex + direction + commandResults.length) % commandResults.length
                  : 0,
              } : current);
            } else if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              insertCommandResult(Math.min(referenceCommand.activeIndex, Math.max(0, commandResults.length - 1)));
            } else if (event.key === "Escape") {
              event.preventDefault();
              event.stopPropagation();
              closeReferenceCommand();
            }
          }}
        >
          <header><div><small>Physical Pinyin Search</small><h3>{referenceCommand.trigger === "@" ? "选择人物" : "选择设定"}</h3></div><button type="button" className="icon-button" aria-label="关闭引用检索" onClick={closeReferenceCommand}><Icon name="close" /></button></header>
          <div className="reference-command-query"><kbd>{referenceCommand.trigger}</kbd><strong>{referenceCommand.query || "直接输入拼音或首字母"}</strong><small>不会触发正文输入法</small></div>
          <div className="reference-command-options" role="listbox" aria-label="引用候选">
            {commandResults.map((candidate, index) => <button
              type="button"
              role="option"
              aria-selected={referenceCommand.activeIndex === index}
              className={referenceCommand.activeIndex === index ? "is-active" : undefined}
              key={candidate.entityId}
              onMouseEnter={() => setReferenceCommand((current) => current ? { ...current, activeIndex: index } : current)}
              onClick={() => insertCommandResult(index)}
            ><Icon name={candidate.kind === "character" ? "person" : "book"} /><span><strong>{candidate.label}</strong><small>{candidate.detail} · {referencePinyin(candidate)}</small></span></button>)}
            {!commandResults.length && <p>没有匹配项，按退格继续修改。</p>}
          </div>
          <footer><kbd>↑↓</kbd><span>选择</span><kbd>Enter / Space</kbd><span>插入</span><kbd>Esc</kbd><span>关闭</span></footer>
        </section>
      </div>}
      {showHelp && <div className="editor-help-backdrop" role="presentation" onMouseDown={(event) => {
        if (event.target === event.currentTarget) setShowHelp(false);
      }}>
        <section className="editor-help-dialog" role="dialog" aria-modal="true" aria-label="编辑器快捷键">
          <header><div><small>Editor Shortcuts</small><h3>编辑器快捷键</h3></div><button type="button" className="icon-button" aria-label="关闭快捷键帮助" onClick={() => setShowHelp(false)}><Icon name="close" /></button></header>
          <p>格式命令作用于当前选区；再次执行同一格式可以取消。正文中输入 <kbd>@</kbd> 或 <kbd>/</kbd> 使用原生输入法检索；工具栏与 Alt 快捷键会打开不触发输入法的物理拼音检索。</p>
          <div className="editor-shortcut-grid">
            <kbd>{primaryKey}+B / I / E / K</kbd><span>加粗 / 斜体 / 行内代码 / 链接</span>
            <kbd>{primaryKey}+Alt+1 / 2 / 3</kbd><span>一级 / 二级 / 三级标题</span>
            <kbd>{primaryKey}+Shift+8 / 7 / Q</kbd><span>无序列表 / 有序列表 / 引用</span>
            <kbd>Alt+↑ / Alt+↓</kbd><span>上一个 / 下一个标题</span>
            <kbd>{primaryKey}+F / H</kbd><span>查找 / 查找替换</span>
            <kbd>@ /</kbd><span>正文内人物 / 设定智能引用，支持中文、全拼和首字母</span>
            <kbd>Alt+M / Alt+/</kbd><span>人物 / 设定物理拼音检索，不改变正文输入状态</span>
            <kbd>{primaryKey}+Shift+P / F</kbd><span>切换预览 / 进入沉浸模式</span>
            <kbd>{primaryKey}+S</kbd><span>原位保存，不关闭编辑器</span>
            <kbd>Enter / Tab / 空格</kbd><span>插入当前智能提示</span>
            <kbd>Esc</kbd><span>关闭提示或退出沉浸模式</span>
          </div>
        </section>
      </div>}
      <p className="sr-only" aria-live="polite">{announcement}</p>
    </section>
  );
}
