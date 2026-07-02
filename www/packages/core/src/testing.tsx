/**
 * Shared test harness for the core transport seam. Exported as
 * `@tm/core/testing` so host, shell, and both products can mock the API
 * transport without reaching into any product package. Test-only: nothing
 * in production code may import this module.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { type ApiTransport, resetApiTransport, setApiTransport } from "./transport";

export function renderWithQuery(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

export function installMockTransport(
  handler: (path: string, init?: RequestInit) => Response | Promise<Response>,
): void {
  const transport: ApiTransport = {
    request(path, init) {
      return Promise.resolve(init === undefined ? handler(path) : handler(path, init));
    },
  };
  setApiTransport(transport);
}

export function restoreTransport(): void {
  resetApiTransport();
}

export function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}
