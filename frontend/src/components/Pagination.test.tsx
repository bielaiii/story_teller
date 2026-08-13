import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Pagination } from "./Pagination";

afterEach(cleanup);

describe("Pagination", () => {
  it("supports jumping to the first and last page", () => {
    const onChange = vi.fn();
    render(<Pagination page={3} totalPages={7} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "首页" }));
    fireEvent.click(screen.getByRole("button", { name: "末页" }));
    fireEvent.click(screen.getByRole("button", { name: "上一页" }));
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));

    expect(onChange.mock.calls).toEqual([[1], [7], [2], [4]]);
  });

  it("disables boundary controls on the first and last page", () => {
    const { rerender } = render(<Pagination page={1} totalPages={4} onChange={() => undefined} />);

    expect(screen.getByRole("button", { name: "首页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "末页" })).not.toBeDisabled();

    rerender(<Pagination page={4} totalPages={4} onChange={() => undefined} />);

    expect(screen.getByRole("button", { name: "首页" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "末页" })).toBeDisabled();
  });

  it("does not render for a single page", () => {
    const { container } = render(<Pagination page={1} totalPages={1} onChange={() => undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
