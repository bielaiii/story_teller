import { Icon } from "./Icon";
import { useEffect, useState, type ReactNode } from "react";

interface Props {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  confirmDisabled?: boolean;
  children?: ReactNode;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}

export function ConfirmDialog({ open, title, message, confirmLabel = "确认", danger = false, confirmDisabled = false, children, onConfirm, onCancel }: Props) {
  const [pending, setPending] = useState(false);
  useEffect(() => {
    if (open) setPending(false);
  }, [open]);
  if (!open) return null;
  const confirm = async () => {
    if (pending || confirmDisabled) return;
    setPending(true);
    try { await onConfirm(); }
    finally { setPending(false); }
  };
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !pending && onCancel()}>
      <section className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-busy={pending}>
        <header><h3 id="confirm-title">{title}</h3><button className="icon-button" disabled={pending} onClick={onCancel} aria-label="关闭" title="关闭"><Icon name="close" /></button></header>
        <p>{message}</p>
        {children}
        <footer>
          <button className="text-action" disabled={pending} onClick={onCancel}>继续编辑</button>
          <button className={`primary-action${danger ? " is-danger" : ""}`} disabled={confirmDisabled || pending} onClick={confirm}>{pending ? "处理中…" : confirmLabel}</button>
        </footer>
      </section>
    </div>
  );
}
