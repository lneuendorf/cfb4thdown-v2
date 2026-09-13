import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FAKE_AWAY, FAKE_HOME } from "../dev/fakeFixtures";
import type { PuntIndex } from "../lib/types";
import { PuntIndexPage } from "./PuntIndexPage";

const INDEX: PuntIndex = {
  subject: "coach",
  metric: "wp_lost",
  season_from: 2099,
  season_to: 2099,
  conference: null,
  min_games: 6,
  returning: false,
  conferences: ["Fake"],
  unattributed_fourth_downs: 11,
  rows: [
    { rank: 1, id: "7001", name: "Coach Fixture", team: FAKE_HOME, value: 0.111, games: 11, fourth_downs: 111,
      go_recommendations: 55, went_for_it: 11, wp_lost_total: 1.221, seasons: [2099], sample_warning: false },
    { rank: null, id: "7002", name: "Coach Mock", team: FAKE_AWAY, value: 0.222, games: 2, fourth_downs: 22,
      go_recommendations: 11, went_for_it: 1, wp_lost_total: 0.444, seasons: [2099], sample_warning: true },
  ],
};

let lastUrl = "";
function Spy() {
  const location = useLocation();
  lastUrl = location.search;
  return null;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("PuntIndexPage", () => {
  it("ranks rows, greys small samples, and keeps filters in the URL", async () => {
    const fetchMock = vi.fn(async (_url: string) =>
      new Response(JSON.stringify({ data: INDEX, meta: { generated_at: "2099-01-01T00:00:00Z", stale: false, source: "cache" } })),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter initialEntries={["/punt-index"]}>
        <Routes>
          <Route path="/punt-index" element={<><PuntIndexPage /><Spy /></>} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("Coach Fixture")).toBeTruthy());
    expect(screen.getByText("−11.1%")).toBeTruthy();
    expect(screen.getByText("—")).toBeTruthy(); // unranked sample-warning row
    expect(screen.getByText(/Under review/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Teams" }));
    await waitFor(() => expect(lastUrl).toContain("subject=team"));
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("subject=team");
  });
});
