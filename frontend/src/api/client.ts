import type {
  EntityDetail,
  MetaResponse,
  MutationDelta,
  OperationItem,
  ProjectSnapshot,
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

export class StoryApi {
  private mutationToken = "";
  private refreshingMeta: Promise<MetaResponse> | null = null;
  private recoveryWatch: Promise<void> | null = null;

  constructor(public project: string) {}

  async meta(): Promise<MetaResponse> {
    const value = await parseResponse<MetaResponse>(
      await fetch(`/api/v1/meta?project=${encodeURIComponent(this.project)}`, { cache: "no-store" }),
    );
    if (!value || typeof value !== "object" || typeof value.apiVersion !== "number") {
      throw new ApiError("当前地址没有可用的本地 Story Teller API", 503, "api_unavailable");
    }
    this.project = value.project || this.project;
    this.mutationToken = value.mutationToken;
    return value;
  }

  snapshot(): Promise<ProjectSnapshot> {
    return fetch(`/api/v1/projects/${encodeURIComponent(this.project)}/snapshot`, { cache: "no-store" })
      .then(parseResponse<ProjectSnapshot>);
  }

  detail<T>(entityId: string): Promise<EntityDetail<T>> {
    return fetch(`/api/v1/projects/${encodeURIComponent(this.project)}/entities/${encodeURIComponent(entityId)}`)
      .then(parseResponse<EntityDetail<T>>);
  }

  trashDetail<T>(entityId: string): Promise<EntityDetail<T>> {
    return fetch(`/api/v1/projects/${encodeURIComponent(this.project)}/trash/${encodeURIComponent(entityId)}`)
      .then(parseResponse<EntityDetail<T>>);
  }

  trash(): Promise<{ items: TrashItem[] }> {
    return fetch(`/api/v1/projects/${encodeURIComponent(this.project)}/trash`, { cache: "no-store" })
      .then(parseResponse<{ items: TrashItem[] }>);
  }

  operations(): Promise<{ items: OperationItem[] }> {
    return fetch(`/api/v1/projects/${encodeURIComponent(this.project)}/operations`, { cache: "no-store" })
      .then(parseResponse<{ items: OperationItem[] }>);
  }

  private mutationRequest(
    path: string,
    method: "POST" | "PATCH" | "PUT" | "DELETE",
    payload: Record<string, unknown>,
  ): Promise<MutationDelta> {
    return fetch(`/api/v1/projects/${encodeURIComponent(this.project)}${path}`, {
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
}

export async function loadStaticSnapshot(): Promise<ProjectSnapshot> {
  const response = await fetch("./project.snapshot.json", { cache: "no-store" });
  const snapshot = await parseResponse<ProjectSnapshot>(response);
  return { ...snapshot, readonly: true };
}

export function projectFromLocation(): string {
  return new URL(window.location.href).searchParams.get("project") || "";
}
