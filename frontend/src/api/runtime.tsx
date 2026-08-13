import { createContext, useContext, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { applyDelta } from "./delta";
import { ApiError, loadStaticSnapshot, projectFromLocation, StoryApi } from "./client";
import { canRetryAgainstLatest, entityRevision, isContentCreatePath, mutationTargetId } from "./mutationConflict";
import type { MetaResponse, MutationDelta, ProjectSnapshot } from "./types";
import { useUiStore } from "../state/ui";

interface RuntimeValue {
  project: string;
  api: StoryApi;
  meta: MetaResponse | null;
  snapshot: ProjectSnapshot;
  writable: boolean;
}

const RuntimeContext = createContext<RuntimeValue | null>(null);

export function RuntimeProvider({ children }: { children: React.ReactNode }) {
  const requestedProject = projectFromLocation();
  const api = useMemo(() => new StoryApi(requestedProject), [requestedProject]);
  const metaQuery = useQuery({
    queryKey: ["meta", requestedProject],
    queryFn: async () => {
      try {
        return await api.meta();
      } catch {
        return null;
      }
    },
    staleTime: 30_000,
  });
  const resolvedProject = metaQuery.data?.project || requestedProject;
  const snapshotQuery = useQuery({
    queryKey: ["snapshot", resolvedProject || "static"],
    enabled: metaQuery.isSuccess,
    queryFn: () => metaQuery.data?.writable ? api.snapshot() : loadStaticSnapshot(),
    staleTime: Number.POSITIVE_INFINITY,
  });

  if (metaQuery.isPending || snapshotQuery.isPending) {
    return <div className="app-loading"><span className="loading-mark" /><p>正在打开写作空间…</p></div>;
  }
  if (snapshotQuery.error || !snapshotQuery.data) {
    const message = snapshotQuery.error instanceof Error ? snapshotQuery.error.message : "无法读取项目数据";
    return <div className="app-error"><h1>项目没有打开</h1><p>{message}</p><small>请确认本地服务已启动，或静态快照已经生成。</small></div>;
  }
  const project = snapshotQuery.data.project.id;
  const value: RuntimeValue = {
    project,
    api,
    meta: metaQuery.data || null,
    snapshot: snapshotQuery.data,
    writable: Boolean(
      (metaQuery.data?.contentWritable ?? metaQuery.data?.writable)
      && !snapshotQuery.data.readonly
    ),
  };
  return <RuntimeContext.Provider value={value}>{children}</RuntimeContext.Provider>;
}

export function useRuntime() {
  const value = useContext(RuntimeContext);
  if (!value) throw new Error("RuntimeProvider is missing");
  return value;
}

export function useProjectMutation() {
  const { api, project, snapshot } = useRuntime();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ path, method, payload }: {
      path: string;
      method: "POST" | "PATCH" | "PUT" | "DELETE";
      payload: Record<string, unknown>;
    }) => {
      if (method !== "DELETE") useUiStore.getState().showNotice("正在保存…", "progress");
      const submitted = queryClient.getQueryData<ProjectSnapshot>(["snapshot", project]) || snapshot;
      const targetId = mutationTargetId(path);
      const targetRevision = targetId ? entityRevision(submitted, targetId) : null;
      const requestPayload = targetRevision === null ? payload : { ...payload, entityRevision: targetRevision };
      try {
        return await api.mutate(path, method, { ...requestPayload, baseRevision: submitted.project.revision });
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 409) throw error;
        if (path.endsWith("/imports/markdown/apply")) throw error;
        const latest = await api.snapshot();
        const canRetry = canRetryAgainstLatest(path, submitted, latest)
          || (method === "POST" && isContentCreatePath(path));
        if (!canRetry) throw error;
        queryClient.setQueryData(["snapshot", project], latest);
        return api.mutate(path, method, { ...requestPayload, baseRevision: latest.project.revision });
      }
    },
    onSuccess: (delta: MutationDelta, variables) => {
      queryClient.setQueryData<ProjectSnapshot>(["snapshot", project], (current) => current ? applyDelta(current, delta) : current);
      void queryClient.invalidateQueries({ queryKey: ["trash", project] });
      void queryClient.invalidateQueries({ queryKey: ["operations", project] });
      if (variables.method !== "DELETE") useUiStore.getState().showNotice("保存成功", "success");
    },
    onError: (error, variables) => {
      if (variables.method !== "DELETE") {
        if (error instanceof ApiError && error.code === "api_unavailable") {
          useUiStore.getState().showNotice("服务正在重启，草稿已保存，正在等待恢复…", "progress");
          void api.waitForRecovery().then(() => {
            useUiStore.getState().showNotice("服务已恢复，可以继续保存", "success");
          });
          return;
        }
        useUiStore.getState().showNotice(error instanceof Error ? `保存失败：${error.message}` : "保存失败，请重试", "error");
      }
    },
  });
}
