import { Link } from "react-router-dom";

/**
 * Rankings are strong claims. Until the outside review in docs/roadmap.md ("Review gate") is
 * done, pages that rank coaches or teams say so.
 */
export function ReviewNotice() {
  return (
    <p className="rounded-card border border-line bg-panel px-4 py-3 text-body text-muted">
      Under review. The model recommends going for it far more often than coaches do, and an outside
      review of those recommendations is still in progress. Treat these rankings as model output.{" "}
      <Link to="/methodology#limitations" className="text-text underline decoration-line underline-offset-4">
        Why
      </Link>
    </p>
  );
}
