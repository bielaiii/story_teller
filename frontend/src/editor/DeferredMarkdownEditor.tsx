import { lazy, Suspense } from "react";
import type { ComponentProps } from "react";
import type { MarkdownEditor as MarkdownEditorComponent } from "./MarkdownEditor";

type Props = ComponentProps<typeof MarkdownEditorComponent>;

const editorModule = () => import("./MarkdownEditor");
const LazyMarkdownEditor = lazy(async () => ({ default: (await editorModule()).MarkdownEditor }));

export function preloadMarkdownEditor() {
  return editorModule();
}

export function DeferredMarkdownEditor(props: Props) {
  return <Suspense fallback={<div className="editor-loading-region" role="status"><span className="loading-mark" /><p>正在准备编辑器…</p></div>}><LazyMarkdownEditor {...props} /></Suspense>;
}
