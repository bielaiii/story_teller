import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FilterChips } from "./FilterChips";

describe("FilterChips", () => {
  it("keeps an expanded icon-triggered list beside its icon", () => {
    render(
      <FilterChips
        label="标签"
        values={["回归篇", "复仇篇", "终局篇"]}
        selected={["回归篇", "复仇篇", "终局篇"]}
        onChange={vi.fn()}
        collapsible
        inlineExpanded
        defaultExpanded={false}
      />,
    );
    const toggle = screen.getByLabelText("展开标签");
    const details = toggle.closest("details");
    expect(details).toHaveClass("is-inline-expanded");

    fireEvent.click(toggle);
    expect(details).toHaveAttribute("open");
    expect(details?.querySelector(":scope > .filter-chips")).toBeTruthy();
  });
});
