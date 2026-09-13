import { Link } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";

export const NotFoundPage = () => (
  <div>
    <PageHeader eyebrow="404" title="Not found">
      There&rsquo;s no page at this address.
    </PageHeader>
    <Link to="/" className="inline-flex min-h-[40px] items-center text-body underline decoration-line underline-offset-4">
      Back to the scoreboard
    </Link>
  </div>
);
