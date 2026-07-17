interface Props {
  page: number;
  totalPages: number;
  onChange: (page: number) => void;
}

export function Pagination({ page, totalPages, onChange }: Props) {
  if (totalPages <= 1) return null;
  const visible = Array.from({ length: totalPages }, (_, index) => index + 1).filter((value) => (
    value === 1 || value === totalPages || Math.abs(value - page) <= 2
  ));
  return <nav className="pagination-bar" aria-label="分页">
    <button type="button" disabled={page === 1} onClick={() => onChange(page - 1)}>上一页</button>
    <div>{visible.map((value, index) => <span key={value}>
      {index > 0 && visible[index - 1] !== value - 1 && <i aria-hidden="true">…</i>}
      <button type="button" className={value === page ? "is-active" : ""} aria-current={value === page ? "page" : undefined} onClick={() => onChange(value)}>{value}</button>
    </span>)}</div>
    <button type="button" disabled={page === totalPages} onClick={() => onChange(page + 1)}>下一页</button>
  </nav>;
}
