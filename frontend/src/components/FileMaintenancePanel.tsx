import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useProjectMutation, useRuntime } from "../api/runtime";
import { Icon } from "./Icon";

const date = (value: number | null) => value ? new Date(value * 1000).toLocaleString() : "尚未完成";

export function FileMaintenancePanel() {
  const { api, project, meta, writable } = useRuntime();
  const supported = Boolean(meta?.features?.includes("reading-copies-v1") && meta.features.includes("sqlite-backups-v1"));
  const mutation = useProjectMutation();
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const query = useQuery({
    queryKey: ["file-maintenance", project],
    queryFn: () => api.fileMaintenance(),
    enabled: supported,
    refetchInterval: (q) => q.state.data?.pending.length ? 1000 : 10_000,
    retry: false,
  });
  if (!supported) return null;
  const data = query.data;
  const busy = submitting || Boolean(data?.pending.length);
  const generate = async (kind: "reading" | "backups") => {
    setSubmitting(true);
    try {
      await api.generateFiles(kind);
      setMessage(kind === "reading" ? "已安排生成，完成后会更新下方状态。" : "已安排完整备份。");
      await query.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "请求失败");
    } finally { setSubmitting(false); }
  };
  const configure = async (enabled: boolean) => {
    try {
      await mutation.mutateAsync({ path: "/maintenance/reading", method: "PUT", payload: { enabled } });
      await query.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "设置失败");
    }
  };
  return <section className="file-maintenance" aria-label="自动 Markdown 与备份">
    <h3>自动 Markdown 与备份</h3>
    <p>设定、人物、碎片、篇章会生成到服务所在电脑。副本供阅读与检索，修改不会写回应用。</p>
    <label className="file-maintenance-toggle">
      <input type="checkbox" checked={data?.reading.enabled ?? true}
        disabled={!data || !writable || mutation.isPending || query.isError}
        onChange={(event) => void configure(event.target.checked)} />
      自动生成阅读副本（每 60 秒合并更新）
    </label>
    {data && <>
      <p>服务器目录：<code>{data.reading.directory}</code></p>
      <p role="status">上次生成：{date(data.reading.lastSuccessAt)} · {busy ? "后台处理中" :
        data.reading.status === "ready" ? "已生成" : data.reading.status === "failed" ? "生成失败" : data.reading.enabled ? "等待生成" : "自动生成已暂停"}</p>
      {data.reading.lastError && <p role="alert">{data.reading.lastError}</p>}
      <button type="button" className="text-action" disabled={!writable || busy || query.isError}
        onClick={() => void generate("reading")}><Icon name="save" />立即生成 Markdown</button>
      <h4>完整数据库备份</h4>
      <p>有变化时每 24 小时自动备份，保留最近 7 份；手动备份不会自动清理。</p>
      <p>服务器目录：<code>{data.backups.directory}</code></p>
      <button type="button" className="text-action" disabled={!writable || busy || query.isError}
        onClick={() => void generate("backups")}><Icon name="save" />立即备份</button>
      <ul aria-label="数据库备份">{data.backups.items.map((item) => <li key={item.filename}>
        {date(item.createdAt)} · {({ daily: "自动", manual: "手动", migration: "升级前" } as Record<string, string>)[item.kind] || item.kind}
        {" · "}版本 {item.revision}<br /><code>{item.filename}</code>
      </li>)}</ul>
      {Object.entries(data.errors).map(([kind, error]) => <p key={kind} role="alert">{error}</p>)}
    </>}
    {query.isError && <p role="alert">服务暂时不可用，无法确认生成与备份状态。</p>}
    {message && <p role="status">{message}</p>}
  </section>;
}
