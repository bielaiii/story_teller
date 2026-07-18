interface Props {
  name:
    | "plus" | "edit" | "trash" | "close" | "restore" | "search" | "person" | "book"
    | "settings" | "undo" | "redo" | "arrow" | "bold" | "italic" | "heading" | "bullet"
    | "numbered" | "quote" | "code" | "link" | "up" | "down" | "replace" | "preview"
    | "expand" | "collapse" | "save" | "help" | "filter" | "tag" | "more" | "sidebar" | "timeline";
}

const paths: Record<Props["name"], React.ReactNode> = {
  plus: <path d="M12 5v14M5 12h14" />,
  edit: <><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></>,
  trash: <><path d="M4 7h16M9 7V4h6v3M7 7l1 14h8l1-14" /><path d="M10 11v6M14 11v6" /></>,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  restore: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></>,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
  person: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
  book: <><path d="M4 5a3 3 0 0 1 3-3h5v18H7a3 3 0 0 0-3 3Z" /><path d="M20 5a3 3 0 0 0-3-3h-5v18h5a3 3 0 0 1 3 3Z" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a7 7 0 0 0-1.7-1L14.5 3h-5L9 6.1a7 7 0 0 0-1.7 1l-2.4-1-2 3.4L5 11a7 7 0 0 0 0 2l-2.1 1.5 2 3.4 2.4-1a7 7 0 0 0 1.7 1l.5 3.1h5l.5-3.1a7 7 0 0 0 1.7-1l2.4 1 2-3.4L19 13a7 7 0 0 0 0-1Z" /></>,
  undo: <><path d="M9 7 4 12l5 5" /><path d="M5 12h8a6 6 0 0 1 6 6" /></>,
  redo: <><path d="m15 7 5 5-5 5" /><path d="M19 12h-8a6 6 0 0 0-6 6" /></>,
  arrow: <path d="m9 18 6-6-6-6" />,
  bold: <><path d="M7 4h6a4 4 0 0 1 0 8H7Z" /><path d="M7 12h7a4 4 0 0 1 0 8H7Z" /></>,
  italic: <><path d="M10 4h8M6 20h8M14 4l-4 16" /></>,
  heading: <><path d="M5 5v14M15 5v14M5 12h10" /><path d="m18 9 2-2v10" /></>,
  bullet: <><circle cx="5" cy="7" r="1" fill="currentColor" stroke="none" /><circle cx="5" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="5" cy="17" r="1" fill="currentColor" stroke="none" /><path d="M9 7h10M9 12h10M9 17h10" /></>,
  numbered: <><path d="M4 6h2v4M4 10h3M4 14c2-1 3 0 3 1 0 2-3 2-3 4h3" /><path d="M10 7h9M10 12h9M10 17h9" /></>,
  quote: <><path d="M5 7h5v5H6a5 5 0 0 1-2 4M14 7h5v5h-4a5 5 0 0 1-2 4" /></>,
  code: <><path d="m8 8-4 4 4 4M16 8l4 4-4 4M14 5l-4 14" /></>,
  link: <><path d="M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1.1 1.1" /><path d="M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1.1-1.1" /></>,
  up: <path d="m6 15 6-6 6 6" />,
  down: <path d="m6 9 6 6 6-6" />,
  replace: <><path d="M4 7h13l-3-3M20 17H7l3 3" /><path d="m17 4 3 3-3 3M7 14l-3 3 3 3" /></>,
  preview: <><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" /><circle cx="12" cy="12" r="2.5" /></>,
  expand: <><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5" /><path d="m3 8 6-6M21 8l-6-6M3 16l6 6M21 16l-6 6" /></>,
  collapse: <><path d="M9 9H4V4M15 9h5V4M9 15H4v5M15 15h5v5" /><path d="M4 4l6 6M20 4l-6 6M4 20l6-6M20 20l-6-6" /></>,
  save: <><path d="M5 4h12l2 2v14H5Z" /><path d="M8 4v6h8V4M8 20v-6h8v6" /></>,
  help: <><circle cx="12" cy="12" r="9" /><path d="M9.8 9a2.4 2.4 0 1 1 3.5 2.1c-.9.5-1.3 1-1.3 2M12 17h.01" /></>,
  filter: <><path d="M4 6h16M7 12h10M10 18h4" /><circle cx="8" cy="6" r="1.5" fill="currentColor" stroke="none" /><circle cx="15" cy="12" r="1.5" fill="currentColor" stroke="none" /><circle cx="12" cy="18" r="1.5" fill="currentColor" stroke="none" /></>,
  tag: <><path d="M20 13 13 20l-9-9V4h7Z" /><circle cx="8.5" cy="8.5" r="1.3" /></>,
  more: <><circle cx="5" cy="12" r="1.3" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" /><circle cx="19" cy="12" r="1.3" fill="currentColor" stroke="none" /></>,
  sidebar: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16M12 8h6M12 12h6M12 16h4" /></>,
  timeline: <><path d="M8 3v18M8 8h4a4 4 0 0 1 4 4v1" /><circle cx="8" cy="6" r="2" /><circle cx="8" cy="18" r="2" /><circle cx="16" cy="15" r="2" /></>,
};

export function Icon({ name }: Props) {
  return <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
