import { useState } from "react";
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
  return (
    <section className="editor-settings-section">
      <button
        className="settings-toggle"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <Icon name="settings" />
        <span>{label}</span>
        <small>{open ? "收起" : "展开"}</small>
      </button>
      {open && <div className="editor-settings">{children}</div>}
    </section>
  );
}
