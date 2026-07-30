import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { applyDelta } from "../api/delta";
import { ApiError } from "../api/client";
import { useRuntime } from "../api/runtime";
import type {
  MergeConflictField,
  MergeConflictItem,
  MergeConflictState,
  MergeFieldResolution,
  ProjectSnapshot,
} from "../api/types";
import { Icon } from "./Icon";

type ResolutionDraft = Record<string, MergeFieldResolution>;

function initialDraft(item: MergeConflictItem | undefined): ResolutionDraft {
  if (!item) return {};
  return Object.fromEntries(
    item.fields
      .filter((field) => field.resolution)
      .map((field) => [field.name, { ...field.resolution! }]),
  );
}

function valueText(value: unknown): string {
  if (value === null || value === undefined) return "不存在（这一侧已删除）";
  if (typeof value === "string") return value || "空内容";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "object" && value && "binary" in value) {
    const bytes = Number((value as { bytes?: number }).bytes || 0);
    return `二进制附件（${bytes.toLocaleString()} 字节）`;
  }
  return JSON.stringify(value, null, 2);
}

function ValuePreview({ value, kind }: { value: unknown; kind: MergeConflictField["kind"] }) {
  return (
    <pre className={`merge-value-preview is-${kind}`}>{valueText(value)}</pre>
  );
}

function ChoiceCard({
  label,
  description,
  selected,
  value,
  kind,
  onChoose,
}: {
  label: string;
  description: string;
  selected: boolean;
  value: unknown;
  kind: MergeConflictField["kind"];
  onChoose: () => void;
}) {
  return (
    <button
      type="button"
      className={`merge-choice${selected ? " is-selected" : ""}`}
      aria-pressed={selected}
      onClick={onChoose}
    >
      <span className="merge-choice-heading">
        <span className="merge-radio" aria-hidden="true"><span /></span>
        <span><strong>{label}</strong><small>{description}</small></span>
      </span>
      <ValuePreview value={value} kind={kind} />
    </button>
  );
}

export function MergeConflictGate() {
  const { api, meta, project } = useRuntime();
  const queryClient = useQueryClient();
  const required = Boolean(meta?.mergeRequired);
  const query = useQuery({
    queryKey: ["merge-conflicts", project],
    queryFn: () => api.mergeConflicts(),
    enabled: required,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const state = query.data;
  const [selectedId, setSelectedId] = useState("");
  const selected = useMemo(
    () => state?.items.find((item) => item.id === selectedId) || state?.items[0],
    [selectedId, state],
  );
  const [draft, setDraft] = useState<ResolutionDraft>({});
  const [error, setError] = useState("");

  useEffect(() => {
    if (selected && selected.id !== selectedId) setSelectedId(selected.id);
  }, [selected, selectedId]);

  useEffect(() => {
    setDraft(initialDraft(selected));
    setError("");
  }, [selected?.id, selected?.status]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!selected) throw new Error("没有可保存的合并项");
      const missing = selected.fields.find((field) => !draft[field.name]);
      if (missing) throw new Error(`请先选择“${missing.label}”保留哪个版本`);
      return api.resolveMergeConflict(selected.id, draft);
    },
    onSuccess: (next) => {
      queryClient.setQueryData(["merge-conflicts", project], next);
      const nextItem = next.items.find((item) => item.status === "open")
        || next.items.find((item) => item.id === selected?.id)
        || next.items[0];
      if (nextItem) setSelectedId(nextItem.id);
      setError("");
    },
    onError: (caught) => {
      setError(caught instanceof Error ? caught.message : "保存选择失败");
    },
  });

  const finalizeMutation = useMutation({
    mutationFn: async () => {
      if (!state?.session) throw new Error("没有可完成的合并会话");
      return api.finalizeMerge(state.session.id);
    },
    onSuccess: async (delta) => {
      queryClient.setQueryData<ProjectSnapshot>(
        ["snapshot", project],
        (current) => current ? applyDelta(current, delta) : current,
      );
      const nextMerge = await api.mergeConflicts();
      queryClient.setQueryData<MergeConflictState>(["merge-conflicts", project], nextMerge);
      setSelectedId(nextMerge.items[0]?.id || "");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["meta"] }),
        queryClient.invalidateQueries({ queryKey: ["snapshot", project] }),
        queryClient.invalidateQueries({ queryKey: ["operations", project] }),
        queryClient.invalidateQueries({ queryKey: ["trash", project] }),
      ]);
      setError("");
    },
    onError: (caught) => {
      const message = caught instanceof ApiError || caught instanceof Error
        ? caught.message
        : "完成合并失败";
      setError(message);
    },
  });

  if (!required) return null;

  if (query.isPending || !state) {
    return (
      <div className="merge-gate-backdrop">
        <section className="merge-gate-loading" role="alertdialog" aria-modal="true">
          <span className="loading-mark" />
          <h2>正在准备内容合并…</h2>
          <p>写作内容保持锁定，确认完成前不会发生新的修改。</p>
        </section>
      </div>
    );
  }

  if (query.error || !state.session) {
    return (
      <div className="merge-gate-backdrop">
        <section className="merge-gate-loading" role="alertdialog" aria-modal="true">
          <Icon name="warning" />
          <h2>无法读取待合并内容</h2>
          <p>{query.error instanceof Error ? query.error.message : "请确认本地服务仍在运行。"}</p>
          <button className="primary-action" type="button" onClick={() => void query.refetch()}>
            重新读取
          </button>
        </section>
      </div>
    );
  }

  const allResolved = state.session.totalFields > 0
    && state.session.resolvedFields === state.session.totalFields;
  const progress = state.session.totalFields
    ? Math.round((state.session.resolvedFields / state.session.totalFields) * 100)
    : 0;

  return (
    <div className="merge-gate-backdrop">
      <section
        className="merge-gate"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="merge-gate-title"
        aria-describedby="merge-gate-description"
      >
        <header className="merge-gate-header">
          <div className="merge-gate-mark"><Icon name="restore" /></div>
          <div>
            <small>检测到两台电脑都修改了内容</small>
            <h2 id="merge-gate-title">完成内容合并后继续写作</h2>
            <p id="merge-gate-description">
              无冲突的修改已经自动合入。下面只列出需要你判断的部分，完成前写作功能会保持锁定。
            </p>
          </div>
          <div className="merge-progress" aria-label={`合并进度 ${progress}%`}>
            <strong>{state.session.resolvedFields}/{state.session.totalFields}</strong>
            <span><i style={{ width: `${progress}%` }} /></span>
            <small>已选择</small>
          </div>
        </header>

        <div className="merge-gate-body">
          <aside className="merge-conflict-list" aria-label="待合并项目">
            <header><strong>需要确认</strong><small>{state.items.length} 项</small></header>
            <div>
              {state.items.map((item, index) => (
                <button
                  type="button"
                  key={item.id}
                  className={`${selected?.id === item.id ? "is-active" : ""}${item.status === "resolved" ? " is-resolved" : ""}`}
                  onClick={() => setSelectedId(item.id)}
                >
                  <span>{item.status === "resolved" ? <Icon name="check" /> : index + 1}</span>
                  <span><strong>{item.title}</strong><small>{item.fields.map((field) => field.label).join("、")}</small></span>
                </button>
              ))}
            </div>
          </aside>

          <main className="merge-conflict-detail">
            {selected && (
              <>
                <header>
                  <div><small>正在确认</small><h3>{selected.title}</h3></div>
                  {selected.status === "resolved" && <span className="merge-resolved-label"><Icon name="check" />已选择</span>}
                </header>
                <div className="merge-fields">
                  {selected.fields.map((field) => {
                    const resolution = draft[field.name];
                    return (
                      <section className="merge-field" key={field.name}>
                        <header>
                          <div><strong>{field.label}</strong><small>选择要保留的版本</small></div>
                          <details>
                            <summary>查看共同版本</summary>
                            <ValuePreview value={field.base} kind={field.kind} />
                          </details>
                        </header>
                        <div className="merge-choice-grid">
                          <ChoiceCard
                            label="保留当前电脑"
                            description="拉取更新前，这台电脑里的内容"
                            selected={resolution?.choice === "ours"}
                            value={field.ours}
                            kind={field.kind}
                            onChoose={() => setDraft((current) => ({
                              ...current,
                              [field.name]: { choice: "ours" },
                            }))}
                          />
                          <ChoiceCard
                            label="采用远程更新"
                            description="另一台电脑提交的内容"
                            selected={resolution?.choice === "theirs"}
                            value={field.theirs}
                            kind={field.kind}
                            onChoose={() => setDraft((current) => ({
                              ...current,
                              [field.name]: { choice: "theirs" },
                            }))}
                          />
                        </div>
                        {field.manualAllowed && (
                          <div className={`merge-manual${resolution?.choice === "manual" ? " is-selected" : ""}`}>
                            <button
                              type="button"
                              aria-pressed={resolution?.choice === "manual"}
                              onClick={() => setDraft((current) => ({
                                ...current,
                                [field.name]: {
                                  choice: "manual",
                                  value: current[field.name]?.choice === "manual"
                                    ? current[field.name].value
                                    : valueText(field.ours) === "空内容" ? "" : String(field.ours ?? ""),
                                },
                              }))}
                            >
                              <span className="merge-radio" aria-hidden="true"><span /></span>
                              <span><strong>自己合并</strong><small>需要同时保留两边内容时使用</small></span>
                            </button>
                            {resolution?.choice === "manual" && (
                              <textarea
                                aria-label={`手动合并${field.label}`}
                                value={resolution.value || ""}
                                onChange={(event) => setDraft((current) => ({
                                  ...current,
                                  [field.name]: { choice: "manual", value: event.target.value },
                                }))}
                              />
                            )}
                          </div>
                        )}
                      </section>
                    );
                  })}
                </div>
              </>
            )}
          </main>
        </div>

        <footer className="merge-gate-footer">
          <div>
            {error
              ? <p className="merge-error" role="alert">{error}</p>
              : <p><Icon name="info" />所有选择都会先经过数据库完整性检查，不会直接覆盖未确认内容。</p>}
          </div>
          <button
            className="text-action merge-save-action"
            type="button"
            disabled={!selected || saveMutation.isPending || finalizeMutation.isPending}
            onClick={() => void saveMutation.mutateAsync()}
          >
            {saveMutation.isPending ? "正在保存…" : selected?.status === "resolved" ? "更新这项选择" : "保存这项选择"}
          </button>
          <button
            className="primary-action"
            type="button"
            disabled={!allResolved || saveMutation.isPending || finalizeMutation.isPending}
            onClick={() => void finalizeMutation.mutateAsync()}
          >
            {finalizeMutation.isPending ? "正在验证并合入…" : "完成合并，进入工作台"}
          </button>
        </footer>
      </section>
    </div>
  );
}
