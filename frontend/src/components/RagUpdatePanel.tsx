import { useState } from "react";
import { useRuntime } from "../api/runtime";
import type { RagRebuildResult } from "../api/types";
import { Icon } from "./Icon";

export function RagUpdatePanel({ onMessage }: { onMessage: (value: string) => void }) {
  const { api, meta, writable } = useRuntime();
  const [updating, setUpdating] = useState(false);
  const [result, setResult] = useState<RagRebuildResult | null>(null);
  const supported = Boolean(
    writable
    && meta?.features.includes("rag-rebuild-v1")
    && meta.routes.ragRebuild,
  );

  const rebuild = async () => {
    if (!supported || updating) return;
    setUpdating(true);
    onMessage("正在从最新内容更新 RAG…");
    try {
      const value = await api.rebuildRag();
      setResult(value);
      onMessage(`RAG 已更新：${value.documents} 个文档，${value.chunks} 个文本块`);
    } catch (error) {
      onMessage(error instanceof Error ? `RAG 更新失败：${error.message}` : "RAG 更新失败");
    } finally {
      setUpdating(false);
    }
  };

  return <section className="recovery-panel rag-update-panel">
    <header><div><small>AI Search</small><h3>RAG 索引</h3></div><span className={`rag-state${result ? " is-ready" : ""}`}>{result ? "已同步" : "按需更新"}</span></header>
    <div className="rag-update-body">
      <div><strong>更新 AI 检索内容</strong><p>从当前 story.db 重新生成 RAG 索引，供 OpenCode 和其他 MCP 客户端检索。</p>{result && <small>版本 {result.sourceRevision} · {result.documents} 个文档 · {result.chunks} 个文本块 · Embedding {result.embeddingStatus}</small>}{!supported && <small>当前本地服务不支持更新 RAG，请更新并重启 Story Teller。</small>}</div>
      <button type="button" className="rag-update-button" disabled={!supported || updating} onClick={() => void rebuild()}><Icon name="replace" />{updating ? "正在更新…" : "更新 RAG"}</button>
    </div>
  </section>;
}
