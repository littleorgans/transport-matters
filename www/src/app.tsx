import { CreateRuleForm } from "./components/CreateRuleForm";
import { ExchangeDetail } from "./components/ExchangeDetail";
import { ExchangeList } from "./components/ExchangeList";
import { BreakpointEditor } from "./components/editor/BreakpointEditor";
import { RulesList } from "./components/RulesList";
import { useBreakpoint } from "./hooks/useBreakpoint";
import { useExchangeStream } from "./hooks/useExchangeStream";
import { useExchanges } from "./hooks/useExchanges";
import { useRules } from "./hooks/useRules";
import { useUIStore } from "./stores/uiStore";

export function App() {
  const { exchanges } = useExchanges();
  const { connected } = useExchangeStream();
  const { rules, createRule, toggleRule, deleteRule } = useRules();
  const { mode, arm, disarm } = useBreakpoint();
  const { selectedId, setSelectedId, activeTab, setActiveTab, pausedFlow, clearPausedFlow } =
    useUIStore();

  return (
    <div className="h-screen bg-canvas text-txt">
      <div className="frame flex h-full border-x border-edge">
        {/* Left panel */}
        <aside className="flex w-[340px] min-w-[300px] flex-col border-r border-edge">
          {/* Header */}
          <div className="top-highlight flex items-center justify-between px-5 py-4">
            <div className="flex items-center gap-3">
              <h1 className="text-[12px] font-semibold tracking-[0.18em] text-txt uppercase">
                Manicure
              </h1>
              <span className="text-[9px] text-txt-3 tracking-wider tabular-nums">v0.0.1</span>
            </div>
            <div className="flex items-center gap-3">
              {mode === "off" ? (
                <button
                  type="button"
                  onClick={arm}
                  className="btn border border-sage/25 bg-sage/5 px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider text-sage hover:bg-sage/10 cursor-pointer"
                >
                  Arm
                </button>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="flex items-center gap-1.5 border border-amber/25 bg-amber/5 px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider text-amber">
                    <span className="h-1 w-1 rounded-full bg-amber pulse-dot" />
                    Armed
                  </span>
                  <button
                    type="button"
                    onClick={disarm}
                    className="btn text-[10px] uppercase tracking-wider text-txt-3 hover:text-txt cursor-pointer"
                  >
                    Disarm
                  </button>
                </div>
              )}
              <span
                className={`flex items-center gap-1.5 text-[10px] uppercase tracking-wider ${
                  connected ? "text-sage" : "text-rose"
                }`}
              >
                <span
                  className={`h-1 w-1 rounded-full ${connected ? "bg-sage pulse-dot" : "bg-rose"}`}
                />
                {connected ? "Live" : "Off"}
              </span>
            </div>
          </div>

          <div className="hairline-x mx-5" />

          {/* Tab bar */}
          <div className="flex border-b border-edge">
            {(["log", "rules"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setActiveTab(tab)}
                className={`relative flex-1 py-3 text-[10px] font-medium uppercase tracking-[0.16em] cursor-pointer transition-all duration-150 ${
                  activeTab === tab
                    ? "tab-pressed text-txt"
                    : "tab-rest text-txt-3 hover:text-txt-2"
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
        </aside>

        {/* Right panel */}
        <main className="flex-1 overflow-hidden">
          {pausedFlow != null ? (
            <BreakpointEditor pausedFlow={pausedFlow} onResolved={clearPausedFlow} />
          ) : activeTab === "log" && selectedId ? (
            <ExchangeDetail id={selectedId} />
          ) : (
            <div className="flex h-full items-center justify-center">
              <span className="label">
                {activeTab === "log" ? "Select an exchange to inspect" : "Switch to log view"}
              </span>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
