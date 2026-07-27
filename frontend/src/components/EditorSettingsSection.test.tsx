import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { EditorSettingsSection } from "./EditorSettingsSection";

describe("EditorSettingsSection", () => {
  afterEach(cleanup);

  it("expands and collapses settings without changing the dialog grid child", () => {
    const { container } = render(
      <EditorSettingsSection label="剧情设置">
        <label><span>标题</span><input aria-label="标题" /></label>
      </EditorSettingsSection>,
    );
    const section = container.querySelector(".editor-settings-section");
    const toggle = screen.getByRole("button", { name: /剧情设置/ });

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("textbox", { name: "标题" })).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("textbox", { name: "标题" })).toBeVisible();
    expect(container.querySelector(".editor-settings-section")).toBe(section);

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("textbox", { name: "标题" })).not.toBeInTheDocument();
  });
});
