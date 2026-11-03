import { describe, expect, it } from "vitest";

import { describeLocation, formatBytes, formatDecimal, formatInteger, formatPages } from "./format";

describe("format", () => {
  it("formats page ranges", () => {
    expect(formatPages(3, 3)).toBe("p. 3");
    expect(formatPages(3, 5)).toBe("pp. 3–5");
  });

  it("formats sizes in B, KB and MB", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(48_213)).toBe("47 KB");
    expect(formatBytes(1.5 * 1024 * 1024)).toBe("1,5 MB");
  });

  it("uses Spanish number formatting and a dash for missing values", () => {
    expect(formatInteger(12_345)).toBe("12.345");
    expect(formatDecimal(0.4567)).toBe("0,46");
    expect(formatInteger(null)).toBe("—");
    expect(formatDecimal(null)).toBe("—");
  });

  it("describes where a fragment comes from, skipping an unknown section", () => {
    expect(describeLocation("Marea Hogar", 2, 3, 4, "Artículo 4. Daños por agua")).toBe(
      "Marea Hogar · v2 · pp. 3–4 · Artículo 4. Daños por agua",
    );
    expect(describeLocation("Marea Hogar", 1, 2, 2, null)).toBe("Marea Hogar · v1 · p. 2");
  });
});
