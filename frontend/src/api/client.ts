import type {
  EntityDetail,
  MergeConflictState,
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
      await fetch(localApiUrl(`/api/v1/meta?project=${encodeURIComponent(this.project)}`), { cache: "no-store" }),
    );
    if (!value || typeof value !== "object" || typeof value.apiVersion !== "number") {
      throw new ApiError("当前地址没有可用的本地 Story Teller API", 503, "api_unavailable");
    }
    this.project = value.project || this.project;
    this.mutationToken = value.mutationToken;
    return value;
  }

  snapshot(): Promise<ProjectSnapshot> {
    return fetch(localApiUrl(`/api/v1/projects/${encodeURIComponent(this.project)}/snapshot`), { cache: "no-store" })
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

  finalizeMerge(sessionId: string): Promise<MutationDelta> {
    return this.authorizedRequest<MutationDelta>(
      `/merge-conflicts/${encodeURIComponent(sessionId)}/finalize`,
      "POST",
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
          "本地服务正在重启，草稿已保存在浏览器中",
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
  const snapshot = await parseResponse<ProjectSnapshot>(response);
  return { ...snapshot, readonly: true };
}

export function projectFromLocation(): string {
  return new URL(window.location.href).searchParams.get("project") || "";
}
