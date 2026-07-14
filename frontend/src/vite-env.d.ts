/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Absolute origin of the Oracle API, e.g. http://192.168.1.2:8000. Leave unset
   * to call the API on the same origin as the page (via the dev proxy in
   * development, or a reverse proxy in production), which is the default.
   */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
