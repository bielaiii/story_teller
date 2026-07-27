import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RenderedMarkdown } from "./RenderedMarkdown";

describe("RenderedMarkdown tables", () => {
  it("renders Markdown table headers and cells as a semantic table", () => {
    render(<RenderedMarkdown source={"| 人物 | 关系 |\n| --- | --- |\n| 沈清妙 | 盟友 |"} />);

    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "人物" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "关系" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "沈清妙" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "盟友" })).toBeInTheDocument();
  });
});
