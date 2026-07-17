import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CollapsibleList } from "./CollapsibleList";

const items = ["一", "二", "三", "四", "五"];

describe("CollapsibleList", () => {
  it("shows three items by default and can expand and collapse", () => {
    render(<CollapsibleList items={items} itemKey={(item) => item} label="相关剧情" renderItem={(item) => <span>{item}</span>} />);
    expect(screen.getAllByText(/^[一二三]$/)).toHaveLength(3);
    expect(screen.queryByText("四")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开全部相关剧情，共 5 项" }));
    expect(screen.getByText("五")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "收起相关剧情，只显示前 3 项" }));
    expect(screen.queryByText("四")).not.toBeInTheDocument();
  });

  it("returns to the collapsed state when the selected entity changes", () => {
    const view = render(<CollapsibleList items={items} itemKey={(item) => item} resetKey="first" label="相关剧情" renderItem={(item) => <span>{item}</span>} />);
    fireEvent.click(within(view.container).getByRole("button", { name: "展开全部相关剧情，共 5 项" }));
    view.rerender(<CollapsibleList items={items} itemKey={(item) => item} resetKey="second" label="相关剧情" renderItem={(item) => <span>{item}</span>} />);
    expect(within(view.container).queryByText("四")).not.toBeInTheDocument();
  });
});
