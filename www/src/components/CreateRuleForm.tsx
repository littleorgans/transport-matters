import { type FormEvent, useReducer } from "react";
import type { ActionType, CreateRuleBody } from "../types";
import { Toggle } from "./Toggle";

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

export interface FormState {
  name: string;
  action: ActionType;
  paramsText: string;
  isGlobal: boolean;
  sessionId: string;
  deviceId: string;
  accountId: string;
  model: string;
  error: string | null;
  submitting: boolean;
}

export type FormAction =
  | { type: "setName"; value: string }
  | { type: "setAction"; value: ActionType }
  | { type: "setParamsText"; value: string }
  | { type: "setIsGlobal"; value: boolean }
  | { type: "setSessionId"; value: string }
  | { type: "setDeviceId"; value: string }
  | { type: "setAccountId"; value: string }
  | { type: "setModel"; value: string }
  | { type: "setError"; value: string | null }
  | { type: "setSubmitting"; value: boolean }
  | { type: "reset" };

export const initialFormState: FormState = {
  name: "",
  action: "strip_tools",
  paramsText: PARAM_EXAMPLES.strip_tools,
  isGlobal: true,
  sessionId: "",
  deviceId: "",
  accountId: "",
  model: "",
  error: null,
  submitting: false,
};

export function formReducer(state: FormState, action: FormAction): FormState {
  switch (action.type) {
    case "setName":
      return { ...state, name: action.value };
    case "setAction":
      return { ...state, action: action.value, paramsText: PARAM_EXAMPLES[action.value] };
    case "setParamsText":
      return { ...state, paramsText: action.value };
    case "setIsGlobal":
      return { ...state, isGlobal: action.value };
    case "setSessionId":
      return { ...state, sessionId: action.value };
    case "setDeviceId":
      return { ...state, deviceId: action.value };
    case "setAccountId":
      return { ...state, accountId: action.value };
    case "setModel":
      return { ...state, model: action.value };
    case "setError":
      return { ...state, error: action.value };
    case "setSubmitting":
      return { ...state, submitting: action.value };
    case "reset":
      return initialFormState;
  }
}

const inputClass =
  "w-full bg-canvas border border-edge px-3 py-2 text-[11px] text-txt placeholder-txt-3 focus:border-sky/50 focus:outline-none transition-colors";

export function CreateRuleForm({ onCreated }: CreateRuleFormProps) {
  const [state, dispatch] = useReducer(formReducer, initialFormState);
  const {
    name,
    action,
    paramsText,
    isGlobal,
    sessionId,
    deviceId,
    accountId,
    model,
    error,
    submitting,
  } = state;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    dispatch({ type: "setError", value: null });

    let params: Record<string, unknown>;
    try {
      params = JSON.parse(paramsText) as Record<string, unknown>;
    } catch {
      dispatch({ type: "setError", value: "Params must be valid JSON" });
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

    dispatch({ type: "setSubmitting", value: true });
    try {
      await onCreated(body);
      dispatch({ type: "reset" });
    } catch (err: unknown) {
      dispatch({
        type: "setError",
        value: err instanceof Error ? err.message : "Failed to create rule",
      });
    } finally {
      dispatch({ type: "setSubmitting", value: false });
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 border-t border-edge px-5 py-5">
      <div className="flex items-center gap-2.5">
        <span className="inline-block h-3 w-px bg-sage/50" />
        <span className="label">New Rule</span>
      </div>

      <input
        type="text"
        placeholder="Rule name"
        value={name}
        onChange={(e) => dispatch({ type: "setName", value: e.target.value })}
        required
        className={inputClass}
      />

      <select
        value={action}
        onChange={(e) => dispatch({ type: "setAction", value: e.target.value as ActionType })}
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
        onChange={(e) => dispatch({ type: "setParamsText", value: e.target.value })}
        placeholder={PARAM_EXAMPLES[action]}
        rows={3}
        className={`${inputClass} resize-none`}
      />

      <div className="flex items-center gap-2.5 text-[11px] text-txt-2">
        <Toggle
          checked={isGlobal}
          onChange={(v) => dispatch({ type: "setIsGlobal", value: v })}
          label="Global scope"
        />
        <span>Global scope</span>
      </div>

      {!isGlobal && (
        <div className="grid grid-cols-2 gap-2">
          <input
            type="text"
            placeholder="session_id"
            value={sessionId}
            onChange={(e) => dispatch({ type: "setSessionId", value: e.target.value })}
            className={inputClass}
          />
          <input
            type="text"
            placeholder="device_id"
            value={deviceId}
            onChange={(e) => dispatch({ type: "setDeviceId", value: e.target.value })}
            className={inputClass}
          />
          <input
            type="text"
            placeholder="account_id"
            value={accountId}
            onChange={(e) => dispatch({ type: "setAccountId", value: e.target.value })}
            className={inputClass}
          />
          <input
            type="text"
            placeholder="model"
            value={model}
            onChange={(e) => dispatch({ type: "setModel", value: e.target.value })}
            className={inputClass}
          />
        </div>
      )}

      {error && <p className="text-[11px] text-rose">{error}</p>}

      <button
        type="submit"
        disabled={submitting || !name.trim()}
        className="btn w-full bg-sage/8 border border-sage/30 px-3 py-2.5 text-[10px] font-medium uppercase tracking-[0.14em] text-sage hover:bg-sage/15 cursor-pointer transition-colors"
      >
        {submitting ? (
          <span className="flex items-center justify-center gap-2">
            <span className="inline-block h-3 w-3 rounded-full border-2 border-sage/30 border-t-sage spinner" />
            Creating
          </span>
        ) : (
          "Create Rule"
        )}
      </button>
    </form>
  );
}
