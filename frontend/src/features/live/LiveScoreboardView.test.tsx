import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { FAKE_SCOREBOARD } from "../../dev/fakeFixtures";
import { LiveScoreboardView } from "./LiveScoreboardView";

const view = (props: Parameters<typeof LiveScoreboardView>[0]) =>
  render(
    <MemoryRouter>
      <LiveScoreboardView {...props} />
    </MemoryRouter>,
  );

afterEach(cleanup);

describe("LiveScoreboardView", () => {
  it("shows the pending card, infeasible options, and signed deltas", () => {
    view({ state: "ready", data: FAKE_SCOREBOARD });
    expect(screen.getByText("On fourth down now")).toBeTruthy();
    expect(screen.getAllByText("not an option").length).toBeGreaterThan(0);
    expect(screen.getByText("−11.1%")).toBeTruthy();
    expect(document.getElementById("play-fake-2")).toBeTruthy();
  });

  it("keeps a pending slot when no game is on fourth down", () => {
    view({ state: "ready", data: { ...FAKE_SCOREBOARD, pending: null } });
    expect(screen.queryByText("On fourth down now")).toBeNull();
    expect(screen.getByText(/No game is sitting on fourth down/)).toBeTruthy();
  });

  it("filters to mistakes and explains an empty filter", () => {
    view({ state: "ready", data: FAKE_SCOREBOARD });
    fireEvent.click(screen.getByRole("button", { name: "Mistakes only" }));
    expect(document.querySelectorAll("article[id^=play-]").length).toBe(1);
    cleanup();
    const noMistakes = FAKE_SCOREBOARD.decisions.filter((d) => d.verdict !== "mistake");
    view({ state: "ready", data: { ...FAKE_SCOREBOARD, decisions: noMistakes } });
    fireEvent.click(screen.getByRole("button", { name: "Mistakes only" }));
    expect(screen.getByText(/No fourth down today was graded a mistake/)).toBeTruthy();
  });

  it("renders loading and error states without data", () => {
    view({ state: "loading" });
    expect(screen.getByText("Loading…")).toBeTruthy();
    cleanup();
    view({ state: "error" });
    expect(screen.getByText(/couldn.t load/)).toBeTruthy();
  });
});
