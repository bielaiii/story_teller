import { useEffect } from "react";
import { useUiStore } from "../state/ui";

export function TransientNotice() {
  const notice = useUiStore((state) => state.notice);
  const dismiss = useUiStore((state) => state.dismissNotice);

  useEffect(() => {
    if (!notice || notice.tone === "progress") return;
    const timer = window.setTimeout(() => dismiss(notice.id), notice.tone === "error" ? 5000 : 3000);
    return () => window.clearTimeout(timer);
  }, [dismiss, notice]);

  if (!notice) return null;
  return (
    <div
      className={`transient-notice is-${notice.tone}`}
      role={notice.tone === "error" ? "alert" : "status"}
      aria-live={notice.tone === "error" ? "assertive" : "polite"}
    >
      <span aria-hidden="true">{notice.tone === "progress" ? "…" : notice.tone === "success" ? "✓" : "!"}</span>
      <strong>{notice.message}</strong>
    </div>
  );
}
