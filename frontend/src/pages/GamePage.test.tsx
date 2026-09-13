import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FAKE_AWAY, FAKE_DECISIONS, FAKE_HOME } from "../dev/fakeFixtures";
import type { GameDetail } from "../lib/types";
import { GamePage } from "./GamePage";

const GAME: GameDetail = {
  game: {
    id: "999000001",
    season: 2099,
    week: 1,
    season_type: "regular",
    start_date: "2099-09-05T18:00:00Z",
    status: "final",
    neutral_site: false,
    home: FAKE_HOME,
    away: FAKE_AWAY,
    home_score: 22,
    away_score: 11,
    grading_status: "graded",
    fourth_downs: 2,
    wp_lost: 0.111,
  },
  grading: { status: "graded", message: null },
  wp_series: [],
  decisions: FAKE_DECISIONS.slice(0, 2),
  totals: { home: { fourth_downs: 2, wp_delta: -0.111 }, away: { fourth_downs: 0, wp_delta: 0 } },
};

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/game/:gameId" element={<GamePage />} />
      </Routes>
    </MemoryRouter>,
  );

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("GamePage", () => {
  it("renders the score, totals and decisions with anchors", async () => {
    mockFetch(200, { data: GAME, meta: { generated_at: "2099-01-01T00:00:00Z", stale: false, source: "cache" } });
    renderAt("/game/999000001");
    await waitFor(() => expect(screen.getByText("MKT at FXS")).toBeTruthy());
    expect(document.getElementById("play-fake-2")).toBeTruthy();
    expect(screen.getByText("FXS WP surrendered")).toBeTruthy();
    expect(screen.getAllByText("−11.1%").length).toBeGreaterThan(0);
  });

  it("explains an ungraded game instead of looking empty", async () => {
    const ungraded: GameDetail = {
      ...GAME,
      grading: { status: "failed_quality_gate", message: "Not graded: fake reason." },
      decisions: [],
    };
    mockFetch(200, { data: ungraded, meta: { generated_at: "2099-01-01T00:00:00Z", stale: false, source: "cache" } });
    renderAt("/game/999000001");
    await waitFor(() => expect(screen.getByText("Not graded: fake reason.")).toBeTruthy());
    expect(screen.getByText(/appear here once the game is graded/)).toBeTruthy();
  });

  it("shows not found for a missing game", async () => {
    mockFetch(404, { error: { code: "GAME_NOT_FOUND", message: "No game with that id." } });
    renderAt("/game/1");
    await waitFor(() => expect(screen.getByText("Game not found")).toBeTruthy());
  });
});
