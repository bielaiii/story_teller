import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReadOnlyArticle } from "./ReadOnlyArticle";

describe("ReadOnlyArticle outline", () => {
  it("hides the outline column when the article has no Markdown headings", () => {
    const { container } = render(
      <ReadOnlyArticle
        title="无目录文章"
        eyebrow="剧情线 · 第 5 章"
        body={"第一段正文。\n\n第二段正文。"}
        onClose={vi.fn()}
      />,
    );

    expect(container.querySelector(".reader-body")).toHaveClass("without-outline");
    expect(screen.queryByRole("complementary", { name: "文章目录" })).toBeNull();
    expect(screen.queryByText("正文没有 Markdown 标题")).toBeNull();
  });

  it("shows the outline column when Markdown headings exist", () => {
    const { container } = render(
      <ReadOnlyArticle
        title="有目录文章"
        eyebrow="灵感碎片"
        body={"# 第一节\n正文。\n\n## 第二节\n更多正文。"}
        onClose={vi.fn()}
      />,
    );

    expect(container.querySelector(".reader-body")).not.toHaveClass("without-outline");
    expect(screen.getByRole("complementary", { name: "文章目录" })).toHaveTextContent("第一节");
    expect(screen.getByRole("link", { name: "第二节" })).toHaveAttribute("href", "#reader-heading-3");
  });

  it("closes only when the surrounding backdrop is clicked", () => {
    const onClose = vi.fn();
    const { container } = render(
      <ReadOnlyArticle
        title="遮罩关闭测试"
        eyebrow="灵感碎片"
        body="正文内容。"
        onClose={onClose}
      />,
    );

    fireEvent.click(screen.getByText("正文内容。"));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(container.querySelector(".reader-backdrop")!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
