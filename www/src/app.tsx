import { useState } from "react";
import { CreateRuleForm } from "./components/CreateRuleForm";
import { ExchangeDetail } from "./components/ExchangeDetail";
import { ExchangeList } from "./components/ExchangeList";
import { BreakpointEditor } from "./components/editor/BreakpointEditor";
import { RulesList } from "./components/RulesList";
import { useBreakpoint } from "./hooks/useBreakpoint";
import { useExchangeStream } from "./hooks/useExchangeStream";
import { useRules } from "./hooks/useRules";

type Tab = "log" | "rules";

export function App() {
  const { exchanges, connected, pausedFlow } = useExchangeStream();
  const { rules, createRule, toggleRule, deleteRule } = useRules();
  const { mode, arm, disarm } = useBreakpoint();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("log");

  return (
    <div className="flex h-screen bg-canvas text-txt">
      {/* Left panel */}
      <div className="flex w-[340px] min-w-[300px] flex-col border-r border-edge">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4">
          <div className="flex items-center gap-3">
            <h1 className="text-[13px] font-semibold tracking-wider text-txt uppercase">
              Manicure
            </h1>
            <span className="text-[10px] text-txt-3 font-light">v0.0.1</span>
          </div>
          <div className="flex items-center gap-3">
            {mode === "off" ? (
              <button
                type="button"
                onClick={arm}
                className="btn rounded-md border border-sage/20 bg-sage/5 px-2.5 py-1 text-[11px] font-medium text-sage hover:bg-sage/10 cursor-pointer"
              >
                Arm
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <span className="flex items-center gap-1.5 rounded-md bg-amber/10 border border-amber/20 px-2.5 py-1 text-[11px] font-medium text-amber">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber pulse-dot" />
                  Armed
                </span>
                <button
                  type="button"
                  onClick={disarm}
                  className="btn text-[11px] text-txt-3 hover:text-txt cursor-pointer"
                >
                  Disarm
                </button>
              </div>
            )}
            <span
              className={`flex items-center gap-1.5 text-[11px] ${
                connected ? "text-sage" : "text-rose"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  connected ? "bg-sage pulse-dot" : "bg-rose"
                }`}
              />
              {connected ? "Live" : "Offline"}
            </span>
          </div>
        </div>

        {/* Tab bar */}
        <div className="flex border-b border-edge">
          {(["log", "rules"] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={`flex-1 py-2.5 text-[11px] font-medium uppercase tracking-wider cursor-pointer transition-colors ${
                activeTab === tab ? "text-txt border-b-2 border-sky" : "text-txt-3 hover:text-txt-2"
              }`}
            >
              {tab}
            </button>
          ))}
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
        {pausedFlow != null ? (
          <BreakpointEditor pausedFlow={pausedFlow} onResolved={() => {}} />
        ) : activeTab === "log" && selectedId ? (
          <ExchangeDetail id={selectedId} />
        ) : (
          <div className="flex h-full items-center justify-center">
            <span className="text-[12px] text-txt-3">
              {activeTab === "log"
                ? "Select an exchange to inspect"
                : "Switch to Log to view exchanges"}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
