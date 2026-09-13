/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "true" to include /dev routes in a build (e.g. a preview deployment). */
  readonly VITE_DEV_ROUTES?: string;
  /** Origin of the FastAPI service in production, e.g. https://api.example.com. */
  readonly VITE_API_BASE?: string;
}
