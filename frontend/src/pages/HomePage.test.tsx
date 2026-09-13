import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FAKE_SCOREBOARD } from "../dev/fakeFixtures";
import { HomePage } from "./HomePage";

const meta = { generated_at: "2099-01-01T00:00:00Z", stale: false, source: "live" };

function mockApi(routes: Record<string, unknown>) {
  const fetchMock = vi.fn(async (url: string) => {
    const key = Object.keys(routes).find((k) => url.includes(k));
    return new Response(JSON.stringify({ data: key ? routes[key] : null, meta }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("HomePage", () => {
  it("shows the live scoreboard with the pending card while games are live", async () => {
    const pending = { ...FAKE_SCOREBOARD.pending!, polled_at: "2099-01-01T20:00:00Z", timeouts_uncertain: true };
    const fetchMock = mockApi({ "/scoreboard/live": { ...FAKE_SCOREBOARD, pending } });
    render(<MemoryRouter><HomePage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("On fourth down now")).toBeTruthy());
    expect(screen.getByText(/Timeouts may be off/)).toBeTruthy();
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/scoreboard/latest"))).toBe(false);
  });

  it("falls back to the latest week when no games are live", async () => {
    const week = { ...FAKE_SCOREBOARD, games_live: 0, pending: null, season: 2099, week: 1,
      season_type: "regular", is_complete: true, games_graded: 3, wp_lost_per_game: 0.011,
      decisions_total: 4, games: [] };
    mockApi({ "/scoreboard/live": { ...FAKE_SCOREBOARD, games_live: 0, pending: null }, "/scoreboard/latest": week });
    render(<MemoryRouter><HomePage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("Week 1 · 2099")).toBeTruthy());
    expect(screen.queryByText("On fourth down now")).toBeNull();
  });
});
