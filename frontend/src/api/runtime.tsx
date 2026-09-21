import { createContext, useContext, useEffect, useMemo, useRef } from "react";
import { replaceEqualDeep, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { applyDelta } from "./delta";
import { ApiError, loadStaticSnapshot, projectFromLocation, runtimeMode, StoryApi } from "./client";
import { canRetryAgainstLatest, entityRevision, isContentCreatePath, mutationTargetId } from "./mutationConflict";
import type { EntityDetail, MetaResponse, MutationDelta, ProjectSnapshot } from "./types";
import { useUiStore } from "../state/ui";
import { ExportStatus } from "../components/ExportStatus";

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
  const local = runtimeMode() === "local";
  const api = useMemo(() => new StoryApi(requestedProject), [requestedProject]);
  const metaQuery = useQuery({
    queryKey: ["meta", requestedProject],
    queryFn: () => local ? api.meta() : Promise.resolve(null),
    retry: false,
    refetchInterval: (query) => local && query.state.error ? 2_000 : false,
    staleTime: 30_000,
  });
  const resolvedProject = metaQuery.data?.project || requestedProject;
  const snapshotQuery = useQuery({
    queryKey: ["snapshot", resolvedProject || "static"],
    enabled: metaQuery.isSuccess,
    queryFn: () => local ? api.snapshot() : loadStaticSnapshot(),
    retry: false,
    refetchInterval: (query) => local && query.state.error ? 2_000 : false,
    staleTime: Number.POSITIVE_INFINITY,
    refetchOnWindowFocus: local ? "always" : false,
    refetchOnReconnect: local ? "always" : false,
    structuralSharing: (oldData, newData) => {
      const current = oldData as ProjectSnapshot | undefined;
      const incoming = newData as ProjectSnapshot;
      return current && current.project.revision > incoming.project.revision
        ? current : replaceEqualDeep(current, incoming);
    },
  });

  const refetchSnapshot = snapshotQuery.refetch;
  useEffect(() => {
    if (!local) return;
    const sync = () => { void refetchSnapshot({ cancelRefetch: false }); };
    window.addEventListener("focus", sync);
    return () => window.removeEventListener("focus", sync);
  }, [local, refetchSnapshot]);

  const connectionFailed = local && (metaQuery.isError || snapshotQuery.isError);
  const reconnect = async () => {
    const result = await metaQuery.refetch();
    if (!result.isError) await snapshotQuery.refetch();
  };
  if (!snapshotQuery.data) {
    if (connectionFailed || snapshotQuery.isError) {
      return <div className="app-error"><h1>{local ? "本地服务暂时不可用" : "无法读取静态项目"}</h1>
        <p>{local ? "正在尝试重新连接。浏览器草稿会保留，恢复后可继续编辑。" : "请确认静态项目快照已经生成。"}</p>
        <button onClick={reconnect}>重新连接</button></div>;
    }
    return <div className="app-loading"><span className="loading-mark" /><p>正在打开写作空间…</p></div>;
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
  return <RuntimeContext.Provider value={value}>
    {children}
    {connectionFailed && <aside className="connection-warning" role="status">本地服务连接中断，正在重连。当前页面和编辑内容已保留。
      <button onClick={reconnect}>立即重试</button></aside>}
    <ExportStatus api={api} project={project} enabled={Boolean(
      metaQuery.data?.writable && metaQuery.data.features?.includes("background-exports-v1")
    )} />
  </RuntimeContext.Provider>;
}

export function useRuntime() {
  const value = useContext(RuntimeContext);
  if (!value) throw new Error("RuntimeProvider is missing");
  return value;
}

export interface ProjectMutationInput {
  path: string;
  method: "POST" | "PATCH" | "PUT" | "DELETE";
  payload: Record<string, unknown>;
}

export function useProjectMutation() {
  const { api, project, snapshot } = useRuntime();
  const queryClient = useQueryClient();
  const savedRevisions = useRef(new Map<string, number>());
  return useMutation({
    mutationFn: async ({ path, method, payload }: ProjectMutationInput) => {
      if (method !== "DELETE") useUiStore.getState().showNotice("正在保存…", "progress");
      const submitted = queryClient.getQueryData<ProjectSnapshot>(["snapshot", project]) || snapshot;
      const targetId = mutationTargetId(path);
      // An open editor keeps its detail baseline when the project list syncs.
      const detail = targetId ? queryClient.getQueryData<EntityDetail>(["entity", project, targetId]) : undefined;
      const baselineRevision = detail ? Math.max(detail.revision, savedRevisions.current.get(targetId!) ?? detail.revision) : null;
      const targetRevision = typeof payload.entityRevision === "number" ? payload.entityRevision
        : baselineRevision ?? (targetId ? entityRevision(submitted, targetId) : null);
      const requestPayload = targetRevision === null ? payload : { ...payload, entityRevision: targetRevision };
      try {
        return await api.mutate(path, method, { ...requestPayload, baseRevision: submitted.project.revision });
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 409) throw error;
        if (path.endsWith("/imports/markdown/apply")) throw error;
        const latest = await api.snapshot();
        const canRetry = (canRetryAgainstLatest(path, submitted, latest)
          && (targetId === null || targetRevision === entityRevision(latest, targetId)))
          || (method === "POST" && isContentCreatePath(path));
        if (!canRetry) throw error;
        queryClient.setQueryData<ProjectSnapshot>(["snapshot", project], (current) =>
          current && current.project.revision > latest.project.revision ? current : latest);
        return api.mutate(path, method, { ...requestPayload, baseRevision: latest.project.revision });
      }
    },
    onSuccess: async (delta: MutationDelta, variables) => {
      const targetId = mutationTargetId(variables.path);
      for (const items of Object.values(delta.changed)) {
        for (const item of items || []) {
          if (item.entityId === targetId && typeof item.entityId === "string" && typeof item.revision === "number") {
            savedRevisions.current.set(item.entityId, Math.max(item.revision, savedRevisions.current.get(item.entityId) ?? 0));
          }
        }
      }
      const current = queryClient.getQueryData<ProjectSnapshot>(["snapshot", project]);
      if (!current || (delta.projectRevision > current.project.revision && delta.fromRevision !== current.project.revision)) {
        // The write has committed. A failed refresh must not report a failed save.
        await queryClient.invalidateQueries({ queryKey: ["snapshot", project] });
      } else {
        queryClient.setQueryData<ProjectSnapshot>(["snapshot", project], (value) => value ? applyDelta(value, delta) : value);
      }
      void queryClient.invalidateQueries({ queryKey: ["exports", project] });
      void queryClient.invalidateQueries({ queryKey: ["trash", project] });
      void queryClient.invalidateQueries({ queryKey: ["operations", project] });
      if (variables.method !== "DELETE") useUiStore.getState().showNotice("保存成功", "success");
    },
    onError: (error, variables) => {
      if (variables.method !== "DELETE") {
        if (error instanceof ApiError && error.code === "api_unavailable") {
          useUiStore.getState().showNotice("本地服务暂时不可用，请保留当前页面，正在等待恢复…", "progress");
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
