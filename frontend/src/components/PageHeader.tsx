import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  children,
  bank,
}: {
  eyebrow?: string;
  title: string;
  children?: ReactNode;
  /** A LightBank, only when the page has something to encode. */
  bank?: ReactNode;
}) {
  return (
    <header className="pb-6 pt-8">
      {bank && <div className="mb-4">{bank}</div>}
      {eyebrow && (
        <p className="font-mono text-label uppercase tracking-wide text-muted">
          {eyebrow}
        </p>
      )}
      <h1 className="mt-1 text-title font-medium uppercase">{title}</h1>
      {children && (
        <div className="mt-2 max-w-prose text-body text-muted">{children}</div>
      )}
    </header>
  );
}

export function SectionTitle({
  id,
  children,
}: {
  id?: string;
  children: ReactNode;
}) {
  return (
    <h2 id={id} className="scroll-mt-20 text-section font-medium">
      {children}
    </h2>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-card border border-line bg-panel px-4 py-3 text-body text-muted">
      {children}
    </p>
  );
}
