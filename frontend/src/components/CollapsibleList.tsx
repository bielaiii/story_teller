import { useEffect, useState, type Key, type ReactNode } from "react";
import { Icon } from "./Icon";

interface Props<T> {
  items: T[];
  itemKey: (item: T) => Key;
  renderItem: (item: T) => ReactNode;
  label: string;
  resetKey?: Key | null;
  className?: string;
  initialCount?: number;
  emptyText?: string;
}

export function CollapsibleList<T>({
  items,
  itemKey,
  renderItem,
  label,
  resetKey,
  className = "",
  initialCount = 3,
  emptyText = "还没有关联内容",
}: Props<T>) {
  const [expanded, setExpanded] = useState(false);
  useEffect(() => setExpanded(false), [resetKey]);
  const canCollapse = items.length > initialCount;
  const visible = expanded ? items : items.slice(0, initialCount);

  return <div className="collapsible-list" data-expanded={expanded || undefined}>
    <div className={className}>{visible.map((item) => <div className="collapsible-list-item" key={itemKey(item)}>{renderItem(item)}</div>)}</div>
    {!items.length && <p className="empty-copy">{emptyText}</p>}
    {canCollapse && <footer className="collapsible-list-control">
      <small>{expanded ? `共 ${items.length} 项` : `另有 ${items.length - initialCount} 项`}</small>
      <button className="icon-button" type="button" aria-label={expanded ? `收起${label}，只显示前 ${initialCount} 项` : `展开全部${label}，共 ${items.length} 项`} title={expanded ? "收起" : "展开全部"} aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}><Icon name={expanded ? "up" : "down"} /></button>
    </footer>}
  </div>;
}
