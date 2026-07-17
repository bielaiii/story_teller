import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { EditorView } from "@codemirror/view";
import type { Character, Entry } from "../api/types";
import {
  MarkdownEditor,
  filterReferenceCandidates,
  referenceQueryAt,
  type ReferenceCandidate,
} from "./MarkdownEditor";

afterEach(cleanup);

const candidates: ReferenceCandidate[] = [
  { entityId: "character:2", kind: "character", label: "陆沉舟", detail: "人物", terms: ["陆沉舟", "沉舟"] },
  { entityId: "entry:old-port", kind: "entry", label: "旧港", detail: "地点", terms: ["旧港", "旧码头"] },
];

const character = {
  entityId: "character:2", name: "陆沉舟", aliases: ["沉舟"], characterScope: "常驻人物",
} as Character;
const entry = {
  entityId: "entry:old-port", name: "旧港", aliases: ["旧码头"], type: "地点", subtype: "港口",
} as Entry;

describe("reference completion", () => {
  it("distinguishes commands from URLs and searches full pinyin or initials", () => {
    expect(referenceQueryAt("http://旧")).toBeNull();
    expect(referenceQueryAt("陆沉舟来到/jiugang")).toMatchObject({ trigger: "/", query: "jiugang" });
    expect(filterReferenceCandidates(candidates, referenceQueryAt("/jg")!)[0].label).toBe("旧港");
    expect(filterReferenceCandidates(candidates, referenceQueryAt("@luchenzhou")!)[0].label).toBe("陆沉舟");
    expect(filterReferenceCandidates(candidates, referenceQueryAt("@lcz")!)[0].label).toBe("陆沉舟");
  });

});

describe("MarkdownEditor shortcuts", () => {
  it("toggles formatting without losing the selection and exposes icon-only help", () => {
    const onChange = vi.fn();
    const { container } = render(<MarkdownEditor
      value="第一段"
      onChange={onChange}
      onSave={vi.fn()}
      characters={[character]}
      entries={[entry]}
    />);
    const editor = EditorView.findFromDOM(container.querySelector(".cm-editor") as HTMLElement)!;
    editor.dispatch({ selection: { anchor: 0, head: 3 } });
    fireEvent.click(screen.getByRole("button", { name: /加粗/ }));
    expect(onChange).toHaveBeenLastCalledWith("**第一段**");
    fireEvent.click(screen.getByRole("button", { name: /加粗/ }));
    expect(onChange).toHaveBeenLastCalledWith("第一段");

    const workspace = container.querySelector(".markdown-workspace")!;
    fireEvent.click(screen.getByRole("button", { name: "切换正文目录" }));
    expect(workspace).toHaveClass("outline-hidden");
    fireEvent.click(screen.getByRole("button", { name: "更多编辑工具" }));
    expect(screen.getByRole("button", { name: /有序列表/ }).querySelector("svg")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /快捷键帮助/ }));
    expect(screen.getByRole("dialog", { name: "编辑器快捷键" })).toHaveTextContent("全拼和首字母");
  });

  it("leaves composition input to CodeMirror instead of synthesizing duplicate characters", () => {
    const onChange = vi.fn();
    const { container } = render(<MarkdownEditor
      value="/"
      onChange={onChange}
      onSave={vi.fn()}
      characters={[character]}
      entries={[entry]}
    />);
    const editor = EditorView.findFromDOM(container.querySelector(".cm-editor") as HTMLElement)!;
    editor.dispatch({ selection: { anchor: 1 } });
    const composition = new InputEvent("beforeinput", {
      bubbles: true,
      cancelable: true,
      inputType: "insertCompositionText",
      data: "旧",
    });
    editor.contentDOM.dispatchEvent(composition);
    expect(composition.defaultPrevented).toBe(false);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("opens reference pickers from icon tools and excludes the source entity", async () => {
    const other = {
      ...character,
      entityId: "character:3",
      name: "苏眠",
      aliases: ["小眠"],
    } as Character;
    const { container } = render(<MarkdownEditor
      value=""
      onChange={vi.fn()}
      onSave={vi.fn()}
      characters={[character, other]}
      entries={[entry]}
      sourceEntityId="character:2"
    />);

    fireEvent.click(screen.getByRole("button", { name: /人物拼音检索/ }));
    const command = await screen.findByRole("dialog", { name: "人物拼音检索" });
    expect(command).toHaveTextContent("苏眠");
    expect(command).not.toHaveTextContent("陆沉舟");
  });

  it("captures physical pinyin in an independent command and inserts the selected reference", async () => {
    const onChange = vi.fn();
    const onReference = vi.fn();
    const { container } = render(<MarkdownEditor
      value=""
      onChange={onChange}
      onSave={vi.fn()}
      onReference={onReference}
      characters={[character]}
      entries={[entry]}
    />);
    fireEvent.click(screen.getByRole("button", { name: /人物拼音检索/ }));
    const command = await screen.findByRole("dialog", { name: "人物拼音检索" });
    fireEvent.keyDown(command, { key: "Process", code: "KeyL", keyCode: 229, isComposing: true });
    fireEvent.keyDown(command, { key: "Process", code: "KeyC", keyCode: 229, isComposing: true });
    fireEvent.keyDown(command, { key: "Process", code: "KeyZ", keyCode: 229, isComposing: true });
    expect(command).toHaveTextContent("lcz");
    expect(command).toHaveTextContent("陆沉舟");
    fireEvent.keyDown(command, { key: "Enter" });
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith("陆沉舟"));
    expect(onReference).toHaveBeenCalledWith({ entityId: "character:2", kind: "character", label: "陆沉舟" });
  });
});
