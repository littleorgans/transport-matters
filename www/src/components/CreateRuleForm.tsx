import { type FormEvent, useState } from "react";
import type { ActionType, CreateRuleBody } from "../types";

interface CreateRuleFormProps {
  onCreated: (body: CreateRuleBody) => Promise<void>;
}

const ACTIONS: ActionType[] = [
  "strip_tools",
  "strip_thinking",
  "strip_system_part",
  "truncate_system_part",
  "truncate_tool_result",
  "rewrite_tool_description",
];

const PARAM_EXAMPLES: Record<ActionType, string> = {
  strip_tools: '{"prefix": "mcp_"}',
  strip_thinking: "{}",
  strip_system_part: '{"index": 0}',
  truncate_system_part: '{"index": 0, "max_chars": 2000}',
  truncate_tool_result: '{"older_than_turns": 3, "max_chars": 2000}',
  rewrite_tool_description: '{"name": "bash", "new": "Execute shell"}',
};

const inputClass =
  "w-full rounded bg-zinc-800 border border-zinc-700 px-2 py-1.5 text-sm text-zinc-200 placeholder-zinc-500 focus:border-zinc-500 focus:outline-none";

export function CreateRuleForm({ onCreated }: CreateRuleFormProps) {
  const [name, setName] = useState("");
  const [action, setAction] = useState<ActionType>("strip_tools");
  const [paramsText, setParamsText] = useState(PARAM_EXAMPLES.strip_tools);
  const [isGlobal, setIsGlobal] = useState(true);
  const [sessionId, setSessionId] = useState("");
  const [deviceId, setDeviceId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [model, setModel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function handleActionChange(newAction: ActionType) {
    setAction(newAction);
    setParamsText(PARAM_EXAMPLES[newAction]);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    let params: Record<string, unknown>;
    try {
      params = JSON.parse(paramsText) as Record<string, unknown>;
    } catch {
      setError("Params must be valid JSON");
      return;
    }

    const body: CreateRuleBody = {
      name: name.trim(),
      action,
      params,
      scope: {
        global: isGlobal,
        session_id: isGlobal ? null : sessionId || null,
        device_id: isGlobal ? null : deviceId || null,
        account_id: isGlobal ? null : accountId || null,
        model: isGlobal ? null : model || null,
      },
    };

    setSubmitting(true);
    try {
      await onCreated(body);
      setName("");
      setParamsText(PARAM_EXAMPLES[action]);
      setIsGlobal(true);
      setSessionId("");
      setDeviceId("");
      setAccountId("");
      setModel("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create rule");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 border-t border-zinc-800 px-3 py-3">
      <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wide">New Rule</h3>

      <input
        type="text"
        placeholder="Rule name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        required
        className={inputClass}
      />

      <select
        value={action}
        onChange={(e) => handleActionChange(e.target.value as ActionType)}
        className={inputClass}
      >
        {ACTIONS.map((a) => (
          <option key={a} value={a}>
            {a}
          </option>
        ))}
      </select>

      <textarea
        value={paramsText}
        onChange={(e) => setParamsText(e.target.value)}
        placeholder={PARAM_EXAMPLES[action]}
        rows={3}
        className={`${inputClass} font-mono text-xs`}
      />

      <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
        <input
          type="checkbox"
          checked={isGlobal}
          onChange={(e) => setIsGlobal(e.target.checked)}
          className="accent-emerald-500"
        />
        Global scope
      </label>

      {!isGlobal && (
        <div className="grid grid-cols-2 gap-2">
          <input
            type="text"
            placeholder="session_id"
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            className={inputClass}
          />
          <input
            type="text"
            placeholder="device_id"
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
            className={inputClass}
          />
          <input
            type="text"
            placeholder="account_id"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            className={inputClass}
          />
          <input
            type="text"
            placeholder="model"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className={inputClass}
          />
        </div>
      )}

      {error && <p className="text-xs text-red-400">{error}</p>}

      <button
        type="submit"
        disabled={submitting || !name.trim()}
        className="w-full rounded bg-emerald-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
      >
        {submitting ? "Creating..." : "Create Rule"}
      </button>
    </form>
  );
}
