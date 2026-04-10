import { useEffect, useState } from "react";
import { fetchExchange } from "../api";
import type { ExchangeDetail as ExchangeDetailType } from "../types";

interface ExchangeDetailProps {
  id: string;
}

function groupToolsByPrefix(tools: Array<{ name: string }>): Record<string, string[]> {
  const groups: Record<string, string[]> = {};
  for (const tool of tools) {
    const parts = tool.name.split("_");
    const prefix = parts.length > 1 ? (parts[0] ?? "other") : "other";
    const list = groups[prefix] ?? [];
    list.push(tool.name);
    groups[prefix] = list;
  }
  return groups;
}

export function ExchangeDetail({ id }: ExchangeDetailProps) {
  const [detail, setDetail] = useState<ExchangeDetailType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchExchange(id)
      .then((data) => {
        if (!cancelled) {
          setDetail(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load exchange");
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) {
    return <div className="flex items-center justify-center p-8 text-zinc-500">Loading...</div>;
  }

  if (error) {
    return <div className="flex items-center justify-center p-8 text-red-400">{error}</div>;
  }

  if (!detail) return null;

  const { entry, request_ir, response_ir } = detail;
  const tools = (request_ir.tools ?? []) as Array<{ name: string }>;
  const toolGroups = groupToolsByPrefix(tools);

  return (
    <div className="space-y-6 overflow-y-auto p-4">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-white">
          {entry.model.replace(/^anthropic\//, "")}
        </h2>
        <p className="text-sm text-zinc-400">
          {entry.provider} &middot; {new Date(entry.ts).toLocaleString()}
        </p>
      </div>

      {/* Request stats */}
      <section>
        <h3 className="mb-2 text-sm font-medium text-zinc-300">Request</h3>
        <div className="grid grid-cols-3 gap-2 text-sm">
          <Stat label="System parts" value={entry.req.system_parts} />
          <Stat label="Tools" value={entry.req.tools_count} />
          <Stat label="Messages" value={entry.req.messages_count} />
          <Stat label="Total size" value={`${(entry.req.total_chars / 1024).toFixed(1)}KB`} />
        </div>
      </section>

      {/* Tools */}
      {tools.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-medium text-zinc-300">Tools ({tools.length})</h3>
          <div className="space-y-2">
            {Object.entries(toolGroups).map(([prefix, names]) => (
              <div key={prefix}>
                <span className="text-xs font-medium text-zinc-500">{prefix}</span>
                <div className="mt-0.5 flex flex-wrap gap-1">
                  {names.map((name) => (
                    <span
                      key={name}
                      className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-300"
                    >
                      {name}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Response stats */}
      {entry.res && (
        <section>
          <h3 className="mb-2 text-sm font-medium text-zinc-300">Response</h3>
          <div className="grid grid-cols-3 gap-2 text-sm">
            {entry.res.stop_reason && <Stat label="Stop reason" value={entry.res.stop_reason} />}
            <Stat label="Input tokens" value={entry.res.input_tokens} />
            <Stat label="Output tokens" value={entry.res.output_tokens} />
            {entry.res.cache_read_input_tokens > 0 && (
              <Stat label="Cache read" value={entry.res.cache_read_input_tokens} />
            )}
            {entry.res.tool_calls > 0 && <Stat label="Tool calls" value={entry.res.tool_calls} />}
          </div>
        </section>
      )}

      {/* Raw IR */}
      <details className="group">
        <summary className="cursor-pointer text-sm font-medium text-zinc-400 hover:text-zinc-200">
          Request IR
        </summary>
        <pre className="mt-2 max-h-96 overflow-auto rounded bg-zinc-900 p-3 text-xs text-zinc-300">
          {JSON.stringify(request_ir, null, 2)}
        </pre>
      </details>

      {response_ir && (
        <details className="group">
          <summary className="cursor-pointer text-sm font-medium text-zinc-400 hover:text-zinc-200">
            Response IR
          </summary>
          <pre className="mt-2 max-h-96 overflow-auto rounded bg-zinc-900 p-3 text-xs text-zinc-300">
            {JSON.stringify(response_ir, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded bg-zinc-800/50 px-2.5 py-1.5">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="font-mono text-zinc-200">{value}</div>
    </div>
  );
}
