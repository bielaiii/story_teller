import { useQuery } from "@tanstack/react-query";
import type { StoryApi } from "../api/client";

/** Poll only this status region, keeping the writing workspace untouched. */
export function ExportStatus({ api, project, enabled }: { api: StoryApi; project: string; enabled: boolean }) {
  const query = useQuery({
    queryKey: ["exports", project],
    enabled,
    queryFn: () => api.exportStatus(),
    refetchInterval: (query) => query.state.data?.status === "pending" ? 1000 : false,
  });
  if (!enabled || !query.data || query.data.status === "ready") return null;
  const failed = query.data.status === "failed";
  return <div className={`export-status${failed ? " is-error" : ""}`} role="status" aria-live="polite">
    {query.isError
      ? "正文已保存，暂时无法确认导出状态"
      : failed
        ? `正文已保存，导出失败：${query.data.lastError || "请稍后重试"}。再次保存或重启可重试。`
        : "正文已保存，正在更新导出…"}
  </div>;
}
