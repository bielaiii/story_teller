import { useEffect, useRef } from "react";

/** Makes save work from metadata fields without competing with CodeMirror's own keymap. */
export function useEditorSaveShortcut(save: () => void | Promise<void>) {
  const saveRef = useRef(save);
  saveRef.current = save;

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.key.toLowerCase() !== "s" || !(event.metaKey || event.ctrlKey) || event.altKey) return;
      if (document.querySelector('[role="alertdialog"]')) return;
      event.preventDefault();
      void saveRef.current();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}
