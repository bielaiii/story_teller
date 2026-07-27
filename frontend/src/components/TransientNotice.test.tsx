import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useUiStore } from "../state/ui";
import { TransientNotice } from "./TransientNotice";

describe("TransientNotice", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    useUiStore.setState({ notice: null });
  });

  it("shows save progress and replaces it with a temporary success notice", () => {
    vi.useFakeTimers();
    render(<TransientNotice />);

    act(() => useUiStore.getState().showNotice("正在保存…", "progress"));
    expect(screen.getByRole("status")).toHaveTextContent("正在保存…");

    act(() => useUiStore.getState().showNotice("保存成功", "success"));
    expect(screen.getByRole("status")).toHaveTextContent("保存成功");

    act(() => vi.advanceTimersByTime(3000));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("keeps an error visible long enough to read", () => {
    vi.useFakeTimers();
    render(<TransientNotice />);

    act(() => useUiStore.getState().showNotice("保存失败：请求超时", "error"));
    expect(screen.getByRole("alert")).toHaveTextContent("请求超时");

    act(() => vi.advanceTimersByTime(4999));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
