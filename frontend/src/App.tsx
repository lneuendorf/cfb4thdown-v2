import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { TickerBar } from "./components/TickerBar";
import { GamesPage } from "./pages/GamesPage";
import { HomePage } from "./pages/HomePage";
import { Methodology } from "./pages/Methodology";
import { NotFoundPage } from "./pages/NotFoundPage";
import { SimulatorPage } from "./pages/SimulatorPage";
import { PuntIndexDetailPage } from "./pages/PuntIndexDetailPage";
import { PuntIndexPage } from "./pages/PuntIndexPage";
import { WeekInReviewPage } from "./pages/WeekInReviewPage";

// The game page carries Recharts; load it on demand so other pages stay small.
const GamePage = lazy(() => import("./pages/GamePage").then((m) => ({ default: m.GamePage })));

// Dev pages (component gallery, live preview from ESPN fixtures). `import.meta.env.DEV` is
// statically false in production builds, so these chunks and fixtures are never emitted there.
const devEnabled = import.meta.env.DEV || import.meta.env.VITE_DEV_ROUTES === "true";
const ComponentsPage = devEnabled
  ? lazy(() => import("./dev/ComponentsPage").then((m) => ({ default: m.ComponentsPage })))
  : null;
const LivePreviewPage = devEnabled
  ? lazy(() => import("./dev/LivePreviewPage").then((m) => ({ default: m.LivePreviewPage })))
  : null;

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout ticker={<TickerBar />} />}>
          <Route index element={<HomePage />} />
          <Route path="games" element={<GamesPage />} />
          <Route
            path="game/:gameId"
            element={
              <Suspense>
                <GamePage />
              </Suspense>
            }
          />
          <Route path="week" element={<WeekInReviewPage />} />
          <Route path="week/:season/:week" element={<WeekInReviewPage />} />
          <Route path="punt-index" element={<PuntIndexPage />} />
          <Route path="punt-index/:subject/:id" element={<PuntIndexDetailPage />} />
          <Route path="simulator" element={<SimulatorPage />} />
          <Route path="methodology" element={<Methodology />} />
          {ComponentsPage && LivePreviewPage && (
            <>
              <Route path="dev/components" element={<Suspense><ComponentsPage /></Suspense>} />
              <Route path="dev/live" element={<Suspense><LivePreviewPage /></Suspense>} />
            </>
          )}
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
