import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

const PRIMARY = [
  // "Live" until live grading ships (roadmap Phase 6); sitemap: "Scoreboard" out of a slate.
  { to: "/", label: "Scoreboard", end: true },
  { to: "/games", label: "Games" },
  { to: "/week", label: "Week" },
  { to: "/punt-index", label: "Punt Index" },
];

const SECONDARY = [
  { to: "/simulator", label: "Simulator" },
  { to: "/methodology", label: "Methodology" },
];

// Amber marks the active nav item; it is the header's only amber.
const navClass = ({ isActive }: { isActive: boolean }) =>
  `inline-flex min-h-[40px] items-center whitespace-nowrap px-[6px] text-body sm:px-2 ${isActive ? "text-bulb" : "text-muted hover:text-text"}`;

/** Shell: optional ticker slot, sticky header, page outlet. */
export function Layout({ ticker }: { ticker?: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setMenuOpen(false), [location.pathname]);

  return (
    <div className="min-h-screen bg-field">
      {ticker}
      <header className="sticky top-0 z-10 border-b border-line bg-deep">
        <div className="mx-auto flex max-w-5xl items-center gap-1 px-4 sm:gap-2">
          <Link
            to="/"
            className="hidden min-h-[40px] shrink-0 items-center font-mono text-meta uppercase tracking-wide text-text sm:mr-2 sm:inline-flex"
          >
            cfb4thdown
          </Link>
          <nav
            aria-label="Main"
            className="flex min-w-0 flex-1 items-center overflow-x-auto"
          >
            {PRIMARY.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={navClass}
              >
                {item.label}
              </NavLink>
            ))}
            <span className="hidden md:contents">
              {SECONDARY.map((item) => (
                <NavLink key={item.to} to={item.to} className={navClass}>
                  {item.label}
                </NavLink>
              ))}
            </span>
          </nav>
          <button
            type="button"
            className="inline-flex min-h-[40px] min-w-[40px] items-center justify-center font-mono text-meta text-muted md:hidden"
            aria-expanded={menuOpen}
            aria-controls="more-nav"
            onClick={() => setMenuOpen((o) => !o)}
          >
            {menuOpen ? "Close" : "More"}
          </button>
        </div>
        {menuOpen && (
          <nav
            id="more-nav"
            aria-label="More"
            className="border-t border-line px-4 py-2 md:hidden"
          >
            {SECONDARY.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={(s) => `flex ${navClass(s)}`}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>
      <main className="mx-auto max-w-5xl px-4 pb-16">
        <Outlet />
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-5xl flex-wrap gap-x-4 gap-y-1 px-4 py-6 text-meta text-muted">
          {/* The wordmark lives here on phones, where the header keeps its width for nav. */}
          <Link to="/" className="font-mono uppercase tracking-wide text-text sm:hidden">
            cfb4thdown
          </Link>
          <span>Recommendations are model output, not certainties.</span>
          <Link
            to="/methodology"
            className="underline decoration-line underline-offset-4 hover:text-text"
          >
            How the model works
          </Link>
        </div>
      </footer>
    </div>
  );
}
