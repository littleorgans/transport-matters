/**
 * Canonical `TRANSPORT_MATTERS_*` env keys shared between the writer
 * (`backendProcess`) and the readers (`main`). Deriving each key from the prefix
 * keeps the writer and readers on one symbol and makes the littleorgans monorepo
 * rename a one-line change. Mirrors `api/src/transport_matters/env_keys.py`;
 * rename both together. See `NOTES/env-vars-transport-prefix.md`.
 */
const ENV_PREFIX = "TRANSPORT_MATTERS_";

export const ENV = {
  CWD: `${ENV_PREFIX}CWD`,
  PROXY_PORT: `${ENV_PREFIX}PROXY_PORT`,
  WEB_PORT: `${ENV_PREFIX}WEB_PORT`,
  DESKTOP_CLIENT: `${ENV_PREFIX}DESKTOP_CLIENT`,
  DESKTOP_ROUTE_URL: `${ENV_PREFIX}DESKTOP_ROUTE_URL`,
  DESKTOP_SMOKE_FILE: `${ENV_PREFIX}DESKTOP_SMOKE_FILE`,
  DESKTOP_PACKAGE_SMOKE: `${ENV_PREFIX}DESKTOP_PACKAGE_SMOKE`,
} as const;
