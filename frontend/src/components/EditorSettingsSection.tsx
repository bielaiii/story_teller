import { useEffect, useId, useState } from "react";
import { Icon } from "./Icon";

export function EditorSettingsSection({
  label,
  children,
  defaultOpen = false,
}: {
  label: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);
  return (
    <section className={`editor-settings-section${open ? " is-open" : ""}`}>
      <button
        className="settings-toggle"
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((value) => !value)}
      >
        <Icon name="settings" />
        <span>{label}</span>
      </button>
      {open && <>
        <button className="editor-settings-scrim" type="button" aria-label={`关闭${label}`} onClick={() => setOpen(false)} />
        <section className="editor-settings-popover" role="dialog" aria-modal="false" aria-labelledby={titleId}>
          <header><div><small>Floating Panel</small><h3 id={titleId}>{label}</h3></div><button className="icon-button" type="button" aria-label={`关闭${label}`} onClick={() => setOpen(false)}><Icon name="close" /></button></header>
          <div className="editor-settings">{children}</div>
        </section>
      </>}
    </section>
  );
}
