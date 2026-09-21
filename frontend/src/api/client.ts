import type {
  EntityDetail,
  MergeConflictState,
  MergePreview,
  MergeFieldResolution,
  MetaResponse,
  MutationDelta,
  OperationItem,
  ProjectSnapshot,
  RagRebuildResult,
  TrashItem,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code = "request_failed",
  ) {
    super(message);
  }
}

export interface FileMaintenanceStatus {
  reading: { enabled: boolean; directory: string; status: string; lastError: string; lastSuccessAt: number | null; intervalSeconds: number };
  backups: { directory: string; items: Array<{ filename: string; createdAt: number; revision: number; kind: string; bytes: number }> };
  pending: string[];
  errors: Record<string, string>;
}

async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof body === "object" && body
      ? String((body as { error?: string; detail?: string }).error || (body as { detail?: string }).detail || response.statusText)
      : String(body || response.statusText);
    const code = typeof body === "object" && body && "code" in body ? String(body.code) : "request_failed";
    throw new ApiError(message, response.status, code);
  }
  return body as T;
}

export function workspaceFromLocation(): string {
  const match = window.location.pathname.match(/^\/w\/([^/]+)(?:\/|$)/);
  return match ? decodeURIComponent(match[1]) : "";
}

function localApiUrl(path: string): string {
  const workspace = workspaceFromLocation();
  return `${workspace ? `/w/${encodeURIComponent(workspace)}` : ""}${path}`;
}

export class StoryApi {
  private mutationToken = "";
  private refreshingMeta: Promise<MetaResponse> | null = null;
  private recoveryWatch: Promise<void> | null = null;

  constructor(public project: string) {}

  async meta(): Promise<MetaResponse> {
    const value = await parseResponse<MetaResponse>(
      await fetch(localApiUrl(`/api/v1/meta?project=${encodeURIComponent(this.project)}`), { cache: "no-store", signal: AbortSignal.timeout(5_000) }),
    );
    if (!value || typeof value !== "object" || typeof value.apiVersion !== "number") {
      throw new ApiError("当前地址没有可用的本地 Story Teller API", 503, "api_unavailable");
    }
    this.project = value.project || this.project;
    this.mutationToken = value.mutationToken;
    return value;
  }

  exportStatus(): Promise<{ status: string; lastError?: string; exportedRevision?: number }> {
    return fetch(localApiUrl(`/api/v1/projects/${encodeURIComponent(this.project)}/exports`), { cache: "no-store" })
      .then(parseResponse<{ status: string; lastError?: string; exportedRevision?: number }>);
  }

  fileMaintenance(): Promise<FileMaintenanceStatus> {
    return fetch(localApiUrl("/api/v1/projects/" + encodeURIComponent(this.project) + "/maintenance/files"),
      { cache: "no-store", signal: AbortSignal.timeout(5_000) }).then(parseResponse<FileMaintenanceStatus>);
  }

  generateFiles(kind: "reading" | "backups"): Promise<{ status: string }> {
    return this.authorizedRequest("/maintenance/" + kind, "POST");
  }

  snapshot(): Promise<ProjectSnapshot> {
    return fetch(localApiUrl(`/api/v1/projects/${encodeURIComponent(this.project)}/snapshot`), { cache: "no-store", signal: AbortSignal.timeout(15_000) })
      .then(parseResponse<ProjectSnapshot>);
  }

  detail<T>(entityId: string): Promise<EntityDetail<T>> {
    return fetch(localApiUrl(`/api/v1/projects/${encodeURIComponent(this.project)}/entities/${encodeURIComponent(entityId)}`))
      .then(parseResponse<EntityDetail<T>>);
  }

  trashDetail<T>(entityId: string): Promise<EntityDetail<T>> {
    return fetch(localApiUrl(`/api/v1/projects/${encodeURIComponent(this.project)}/trash/${encodeURIComponent(entityId)}`))
      .then(parseResponse<EntityDetail<T>>);
  }

  trash(): Promise<{ items: TrashItem[] }> {
    return fetch(localApiUrl(`/api/v1/projects/${encodeURIComponent(this.project)}/trash`), { cache: "no-store" })
      .then(parseResponse<{ items: TrashItem[] }>);
  }

  operations(): Promise<{ items: OperationItem[] }> {
    return fetch(localApiUrl(`/api/v1/projects/${encodeURIComponent(this.project)}/operations`), { cache: "no-store" })
      .then(parseResponse<{ items: OperationItem[] }>);
  }

  mergeConflicts(): Promise<MergeConflictState> {
    return fetch(
      localApiUrl(`/api/v1/projects/${encodeURIComponent(this.project)}/merge-conflicts`),
      { cache: "no-store" },
    ).then(parseResponse<MergeConflictState>);
  }

  private authorizedRequestOnce<T>(
    path: string,
    method: "POST" | "PUT",
    payload?: Record<string, unknown>,
    timeoutMs = 15_000,
  ): Promise<T> {
    return fetch(localApiUrl(`/api/v1/projects/${encodeURIComponent(this.project)}${path}`), {
      method,
      signal: AbortSignal.timeout(timeoutMs),
      headers: {
        "Content-Type": "application/json",
        "X-Story-Teller-Token": this.mutationToken,
      },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    }).then(parseResponse<T>);
  }

  private async authorizedRequest<T>(
    path: string,
    method: "POST" | "PUT",
    payload?: Record<string, unknown>,
    timeoutMs = 15_000,
    unavailableMessage = "本地服务暂时不可用，已经保存的合并选择不会丢失",
  ): Promise<T> {
    try {
      return await this.authorizedRequestOnce<T>(path, method, payload, timeoutMs);
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        await this.refreshMeta();
        return this.authorizedRequestOnce<T>(path, method, payload, timeoutMs);
      }
      if (error instanceof TypeError || (error instanceof DOMException && error.name === "TimeoutError")) {
        throw new ApiError(unavailableMessage, 0, "api_unavailable");
      }
      throw error;
    }
  }

  resolveMergeConflict(
    conflictId: string,
    resolutions: Record<string, MergeFieldResolution>,
  ): Promise<MergeConflictState> {
    return this.authorizedRequest<MergeConflictState>(
      `/merge-conflicts/${encodeURIComponent(conflictId)}`,
      "PUT",
      { resolutions },
    );
  }

  async previewMerge(sessionId: string): Promise<MergePreview> {
    try {
      const response = await fetch(localApiUrl(`/api/v1/projects/${encodeURIComponent(this.project)}/merge-conflicts/${encodeURIComponent(sessionId)}/preview`), { cache: "no-store", signal: AbortSignal.timeout(15_000) });
      return await parseResponse<MergePreview>(response);
    } catch (error) {
      if (error instanceof TypeError || (error instanceof DOMException && error.name === "TimeoutError")) {
        throw new ApiError("无法连接本地服务，合并选择已保存，请恢复服务后重新预览", 0, "api_unavailable");
      }
      throw error;
    }
  }

  finalizeMerge(sessionId: string, previewToken?: string): Promise<MutationDelta> {
    return this.authorizedRequest<MutationDelta>(
      `/merge-conflicts/${encodeURIComponent(sessionId)}/finalize`,
      "POST",
      previewToken ? { previewToken } : undefined,
    );
  }

  rebuildRag(): Promise<RagRebuildResult> {
    return this.authorizedRequest<RagRebuildResult>(
      "/rag/rebuild",
      "POST",
      undefined,
      120_000,
      "RAG 更新服务暂时不可用",
    );
  }

  private mutationRequest(
    path: string,
    method: "POST" | "PATCH" | "PUT" | "DELETE",
    payload: Record<string, unknown>,
  ): Promise<MutationDelta> {
    return fetch(localApiUrl(`/api/v1/projects/${encodeURIComponent(this.project)}${path}`), {
      method,
      signal: AbortSignal.timeout(15_000),
      headers: {
        "Content-Type": "application/json",
        "X-Story-Teller-Token": this.mutationToken,
      },
      body: JSON.stringify(payload),
    }).then(parseResponse<MutationDelta>);
  }

  private refreshMeta(): Promise<MetaResponse> {
    if (!this.refreshingMeta) {
      this.refreshingMeta = this.meta().finally(() => {
        this.refreshingMeta = null;
      });
    }
    return this.refreshingMeta;
  }

  waitForRecovery(pollInterval = 1_000): Promise<void> {
    if (!this.recoveryWatch) {
      this.recoveryWatch = (async () => {
        while (true) {
          try {
            const meta = await this.refreshMeta();
            if (meta.writable && meta.mutationToken) return;
          } catch {
            // The local process is expected to reject connections while restarting.
          }
          await new Promise((resolve) => window.setTimeout(resolve, pollInterval));
        }
      })().finally(() => {
        this.recoveryWatch = null;
      });
    }
    return this.recoveryWatch;
  }

  async mutate(
    path: string,
    method: "POST" | "PATCH" | "PUT" | "DELETE",
    payload: Record<string, unknown>,
  ): Promise<MutationDelta> {
    try {
      return await this.mutationRequest(path, method, payload);
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        await this.refreshMeta();
        return this.mutationRequest(path, method, payload);
      }
      if (error instanceof TypeError || (error instanceof DOMException && error.name === "TimeoutError")) {
        throw new ApiError(
          "本地服务暂时不可用，请保留当前页面，恢复后重试保存",
          0,
          "api_unavailable",
        );
      }
      throw error;
    }
  }

  markdownImportPreview(payload: Record<string, unknown>): Promise<{
    baseRevision: number;
    items: Array<Record<string, unknown>>;
    conflicts: Array<Record<string, unknown>>;
    requiresResolution: boolean;
    fileCount: number;
    fingerprint: string;
  }> {
    return this.authorizedRequest(`/imports/markdown/preview`, "POST", payload);
  }

  plotTitlePreview(): Promise<{
    items: Array<{ entityId: string; chapterNumber: number | null; currentTitle: string; candidateTitle: string; candidateSource: string; bodyPreview: string; stories: string[]; recommendedAction: string }>;
    count: number;
  }> {
    return fetch(localApiUrl(`/api/v1/projects/${encodeURIComponent(this.project)}/maintenance/plot-titles`), { cache: "no-store" })
      .then(parseResponse<{
        items: Array<{ entityId: string; chapterNumber: number | null; currentTitle: string; candidateTitle: string; candidateSource: string; bodyPreview: string; stories: string[]; recommendedAction: string }>;
        count: number;
      }>);
  }
}

export async function loadStaticSnapshot(): Promise<ProjectSnapshot> {
  const response = await fetch("./project.snapshot.json", { cache: "no-store" });
  const payload = await parseResponse<ProjectSnapshot | StaticJournal>(response);
  if (!("format" in payload) || payload.format !== "story-teller-export-journal") {
    return { ...payload as ProjectSnapshot, readonly: true };
  }
  if (payload.version !== 1 || payload.kind !== "static" || payload.patches.length > 64) {
    throw new Error("静态快照格式不受支持，请重新导出");
  }
  const read = async (path: string) => {
    if (!/^export-data\/[a-f0-9]{64}\.json$/.test(path)) throw new Error("静态快照路径无效");
    return fetch(`./${path}`, { cache: "force-cache" }).then(parseResponse<unknown>);
  };
  const [base, ...patches] = await Promise.all([payload.base, ...payload.patches].map(read));
  let snapshot = base as ProjectSnapshot;
  for (const raw of patches) {
    const patch = raw as StaticPatch;
    if (patch.fromRevision !== snapshot.project.revision || patch.project !== snapshot.project.id) {
      throw new Error("静态快照增量不连续，请重新导出");
    }
    const next = patch.static.summary;
    const collections = ["characters", "plots", "entries", "fragments", "relationships", "chapters"] as const;
    const updated = { ...next } as ProjectSnapshot;
    for (const collection of collections) {
      const previous = new Map(snapshot[collection].map(item => [item.entityId, item]));
      (updated[collection] as unknown[]) = next[collection].map(item => ({
        ...(previous.get(item.entityId) || item), ...patch.static.overrides[item.entityId], ...patch.static.details[item.entityId],
      }));
    }
    snapshot = updated;
  }
  if (snapshot.project.id !== payload.project.id || snapshot.project.revision !== payload.project.revision) {
    throw new Error("静态快照版本不匹配，请重新导出");
  }
  return { ...snapshot, readonly: true };
}

export function projectFromLocation(): string {
  return new URL(window.location.href).searchParams.get("project") || "";
}


export function runtimeMode(): "local" | "static" {
  return document.querySelector('meta[name="story-teller-mode"]')?.getAttribute("content") === "static"
    ? "static" : "local";
}

interface StaticJournal {
  format: "story-teller-export-journal";
  version: number;
  kind: string;
  project: ProjectSnapshot["project"];
  base: string;
  patches: string[];
}
interface StaticPatch {
  fromRevision: number;
  project: string;
  static: { summary: ProjectSnapshot; overrides: Record<string, Record<string, unknown>>; details: Record<string, Record<string, unknown>> };
}
