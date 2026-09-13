import { describe, expect, it } from "vitest";
import { formatDelta, formatPeriod, formatRate, formatWp, situation } from "./format";

const OFF = { id: "90001", name: "Fixture State", abbreviation: "FXS" };
const DEF = { id: "90002", name: "Mock Tech", abbreviation: "MKT" };

describe("format", () => {
  it("rounds WP to one decimal and shows a dash for infeasible options", () => {
    expect(formatWp(0.11111)).toBe("11.1%");
    expect(formatWp(null)).toBe("—");
  });

  it("signs deltas with a true minus sign", () => {
    expect(formatDelta(-0.111)).toBe("−11.1%");
    expect(formatDelta(0.222)).toBe("+22.2%");
    expect(formatDelta(0)).toBe("0.0%");
    expect(formatDelta(-0.0001)).toBe("0.0%");
  });

  it("rounds rates to whole percents", () => {
    expect(formatRate(0.555)).toBe("56%");
  });

  it("labels periods", () => {
    expect(formatPeriod(4)).toBe("Q4");
    expect(formatPeriod(5)).toBe("OT");
  });

  it("describes field position from the offense's side", () => {
    expect(situation(4, 3, 80, OFF, DEF)).toBe("4th & 3 at FXS 20");
    expect(situation(4, 3, 30, OFF, DEF)).toBe("4th & 3 at MKT 30");
    expect(situation(4, 3, 50, OFF, DEF)).toBe("4th & 3 at 50");
    expect(situation(4, 3, 3, OFF, DEF)).toBe("4th & goal at MKT 3");
  });
});
