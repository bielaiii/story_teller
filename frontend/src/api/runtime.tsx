import { createContext, useContext, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { applyDelta } from "./delta";
import { loadStaticSnapshot, projectFromLocation, StoryApi } from "./client";
import type { MetaResponse, MutationDelta, ProjectSnapshot } from "./types";

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
    writable: Boolean(metaQuery.data?.writable && !snapshotQuery.data.readonly),
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
    mutationFn: ({ path, method, payload }: {
      path: string;
      method: "POST" | "PATCH" | "PUT" | "DELETE";
      payload: Record<string, unknown>;
    }) => api.mutate(path, method, { ...payload, baseRevision: snapshot.project.revision }),
    onSuccess: (delta: MutationDelta) => {
      queryClient.setQueryData<ProjectSnapshot>(["snapshot", project], (current) => current ? applyDelta(current, delta) : current);
      void queryClient.invalidateQueries({ queryKey: ["trash", project] });
      void queryClient.invalidateQueries({ queryKey: ["operations", project] });
      void queryClient.invalidateQueries({ queryKey: ["diagnostics", project] });
    },
  });
}
