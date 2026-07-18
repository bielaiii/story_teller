import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RenderedMarkdown } from "./RenderedMarkdown";

describe("RenderedMarkdown", () => {
  it("renders preview markdown instead of exposing source markers", () => {
    const { container } = render(<RenderedMarkdown source={"### 转折\n\n**线索**已经出现。"} />);
    expect(screen.getByRole("heading", { name: "转折" })).toBeVisible();
    expect(screen.getByText("线索").tagName).toBe("STRONG");
    expect(container).not.toHaveTextContent("###");
    expect(container).not.toHaveTextContent("**");
  });
});
