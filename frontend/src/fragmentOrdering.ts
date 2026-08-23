import type { Fragment } from "./api/types";

export function fragmentRecency(item: Fragment): number | undefined {
  return item.updatedAt ?? item.createdAt;
}

export function compareFragmentsByRecency(left: Fragment, right: Fragment): number {
  const leftUpdated = fragmentRecency(left);
  const rightUpdated = fragmentRecency(right);
  if (leftUpdated === undefined && rightUpdated === undefined) return 0;
  if (leftUpdated === undefined) return 1;
  if (rightUpdated === undefined) return -1;
  return rightUpdated - leftUpdated
    || (right.createdAt ?? 0) - (left.createdAt ?? 0)
    || right.id.localeCompare(left.id, "en", { numeric: true });
}
