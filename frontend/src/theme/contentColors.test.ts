import { describe, expect, it } from "vitest";
import { avatarBackground, avatarGradient, CONTENT_COLOR_PALETTE, randomContentColor } from "./contentColors";

describe("content colors", () => {
  it("chooses automatic colors only from the shared palette", () => {
    expect(CONTENT_COLOR_PALETTE).toContain(randomContentColor() as typeof CONTENT_COLOR_PALETTE[number]);
  });

  it("builds one consistent avatar gradient and preserves an explicit custom gradient", () => {
    expect(avatarGradient("#4f6fae")).toMatch(/^linear-gradient\(145deg,/);
    expect(avatarBackground({ color: "#4f6fae", gradient: "radial-gradient(red, blue)" })).toBe("radial-gradient(red, blue)");
  });
});
