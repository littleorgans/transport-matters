import { useState } from "react";
import { CreateRuleForm } from "./components/CreateRuleForm";
import { ExchangeDetail } from "./components/ExchangeDetail";
import { ExchangeList } from "./components/ExchangeList";
import { RulesList } from "./components/RulesList";
import { useExchangeStream } from "./hooks/useExchangeStream";
import { useRules } from "./hooks/useRules";

type Tab = "log" | "rules";

export function App() {
  const { exchanges, connected } = useExchangeStream();
  const { rules, createRule, toggleRule, deleteRule } = useRules();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("log");

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100">
      {/* Left panel */}
      <div className="flex w-1/3 min-w-70 flex-col border-r border-zinc-800">
        <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
          <h1 className="text-sm font-semibold tracking-wide text-zinc-300">Manicure</h1>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs ${
              connected ? "bg-emerald-900/40 text-emerald-400" : "bg-red-900/40 text-red-400"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-emerald-400" : "bg-red-400"}`}
            />
            {connected ? "Live" : "Disconnected"}
          </span>
        </div>

        {/* Tab bar */}
        <div className="flex border-b border-zinc-800">
          <button
            type="button"
            onClick={() => setActiveTab("log")}
            className={`flex-1 px-3 py-1.5 text-xs font-medium cursor-pointer ${
              activeTab === "log"
                ? "text-zinc-100 border-b-2 border-emerald-500"
                : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            Log
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("rules")}
            className={`flex-1 px-3 py-1.5 text-xs font-medium cursor-pointer ${
              activeTab === "rules"
                ? "text-zinc-100 border-b-2 border-emerald-500"
                : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            Rules
          </button>
        </div>

        {activeTab === "log" ? (
          <ExchangeList exchanges={exchanges} selectedId={selectedId} onSelect={setSelectedId} />
        ) : (
          <div className="flex flex-col overflow-y-auto">
            <RulesList rules={rules} onToggle={toggleRule} onDelete={deleteRule} />
            <CreateRuleForm onCreated={createRule} />
          </div>
        )}
      </div>

      {/* Right panel */}
      <div className="flex-1 overflow-hidden">
        {activeTab === "log" && selectedId ? (
          <ExchangeDetail id={selectedId} />
        ) : (
          <div className="flex h-full items-center justify-center text-zinc-600">
            {activeTab === "log"
              ? "Select an exchange to view details"
              : "Select the Log tab to view exchange details"}
          </div>
        )}
      </div>
    </div>
  );
}
