import { useState } from "react";
import { Icon } from "./Icon";

interface Props {
  label: string;
  values: string[];
  selected: string[];
  onChange: (values: string[]) => void;
  collapsible?: boolean;
  hideLabel?: boolean;
  defaultExpanded?: boolean;
  trigger?: "icon" | "text";
  inlineExpanded?: boolean;
}

export function FilterChips({
  label,
  values,
  selected,
  onChange,
  collapsible = false,
  hideLabel = false,
  defaultExpanded = true,
  trigger = "icon",
  inlineExpanded = false,
}: Props) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const allSelected = values.length > 0 && selected.length === values.length;
  const toggle = (value: string) => {
    if (allSelected) {
      onChange([value]);
      return;
    }
    if (selected.includes(value)) {
      const next = selected.filter((item) => item !== value);
      onChange(next.length ? next : [...values]);
    } else {
      const next = [...selected, value];
      onChange(next.length === values.length ? [...values] : next);
    }
  };
  const content = <div className="filter-chips">{values.map((value) => (
    <button key={value} type="button" className={selected.includes(value) ? "is-active" : ""} aria-pressed={selected.includes(value)} onClick={() => toggle(value)}>{value}</button>
  ))}</div>;
  const rowLabel = <span className={`filter-label${hideLabel ? " is-icon-only" : ""}`}><Icon name={label === "标签" ? "tag" : "filter"} />{!hideLabel && <span>{label}</span>}</span>;
  if (collapsible) return <details className={`filter-details${hideLabel ? " has-icon-label" : ""}${trigger === "text" ? " is-text-trigger" : ""}${inlineExpanded ? " is-inline-expanded" : ""}`} open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}><summary aria-label={`${expanded ? "收起" : "展开"}${label}`} title={`${expanded ? "收起" : "展开"}${label}`} aria-expanded={expanded}>{trigger === "text" ? <span className="filter-collapse-copy"><strong>{label}筛选</strong><small>{allSelected ? `${values.length} 个标签` : `已选 ${selected.length}/${values.length}`}</small><Icon name="down" /></span> : <span className="filter-collapse-icon"><Icon name="tag" /></span>}</summary>{content}</details>;
  return <section className="filter-group">{rowLabel}{content}</section>;
}
