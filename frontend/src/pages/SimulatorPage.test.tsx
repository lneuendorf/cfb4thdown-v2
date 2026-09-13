import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SimulateResult } from "../lib/types";
import { SimulatorPage } from "./SimulatorPage";

const RESULT: SimulateResult = {
  recommendation: "go",
  confidence: "clear",
  margin: 0.111,
  wp_go: 0.555,
  wp_field_goal: null,
  wp_punt: 0.444,
  p_convert: 0.666,
  p_fg_make: null,
  punt_opponent_yards_to_goal: 88,
  inputs: {
    distance: 2, yards_to_goal: 40, offense_score: 17, defense_score: 21, period: 4, clock_seconds: 360,
    offense_timeouts: 3, defense_timeouts: 3, spread: 0, home: "neutral", offense_elo: 1500, defense_elo: 1500,
  },
  defaults: {},
  model_versions: { win_probability: "9.9.9" },
  historical: {
    similar_situations: 0, went_for_it: null, punted: null, kicked_field_goal: null, model_said_go: null,
    conversion_rate: null,
    criteria: { distance: [2, 2], yards_to_goal: [35, 45], score_diff: [-8, -4], period: 4, scope: "fake" },
    examples: [],
  },
};

let search = "";
function Spy() {
  search = useLocation().search;
  return null;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SimulatorPage", () => {
  it("opens on defaults, shows infeasible options, and encodes inputs in the URL", async () => {
    const fetchMock = vi.fn(async (_url: string) =>
      new Response(JSON.stringify({ data: RESULT, meta: { generated_at: "2099-01-01T00:00:00Z", stale: false, source: "model" } })),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter initialEntries={["/simulator"]}>
        <Routes>
          <Route path="/simulator" element={<><SimulatorPage /><Spy /></>} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getAllByText("55.5%").length).toBeGreaterThan(0));
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("distance=2&yards_to_goal=40");
    expect(screen.getAllByText("not an option").length).toBeGreaterThan(0);
    expect(screen.getByText(/No graded fourth down since 2013/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Increase Distance" }));
    await waitFor(() => expect(search).toContain("distance=3"));

    // A half-typed clock stays in the box and never reaches the URL.
    const clock = screen.getByLabelText("Clock remaining in the quarter") as HTMLInputElement;
    fireEvent.change(clock, { target: { value: "4:3" } });
    expect(clock.value).toBe("4:3");
    expect(search).not.toContain("clock");
    fireEvent.change(clock, { target: { value: "4:30" } });
    await waitFor(() => expect(search).toContain("clock=4%3A30"));
  });
});
