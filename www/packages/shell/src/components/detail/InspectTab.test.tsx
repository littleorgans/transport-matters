import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ExchangeDetail } from "@tm/core/types/exchanges";
import type { InternalRequest, InternalResponse } from "@tm/core/types/ir";
import type { OverrideAudit } from "@tm/core/types/overrides";
import { beforeEach, describe, expect, it } from "vitest";
import { useUIStore } from "../../stores/uiStore";
import { InspectTab } from "./InspectTab";

function makeRequest(overrides: Partial<InternalRequest> = {}): InternalRequest {
  return {
    model: "gpt-5-codex",
    provider: "codex",
    system: [],
    tools: [],
    messages: [],
    sampling: {
      max_tokens: 1024,
      temperature: null,
      top_p: null,
      top_k: null,
      stop_sequences: [],
    },
    metadata: {
      session_id: "sess-1",
      device_id: null,
      account_id: null,
      provider_metadata: {},
    },
    stream: false,
    provider_extras: {},
    ...overrides,
  };
}

function makeAudit(entries: OverrideAudit["entries"]): OverrideAudit {
  return {
    entries,
    chars_before: 0,
    chars_after: 0,
    system_chars_before: 0,
    system_chars_after: 0,
    tools_chars_before: 0,
    tools_chars_after: 0,
    messages_chars_before: 0,
    messages_chars_after: 0,
  };
}

function makeDetail({
  request,
  curated,
  audit = null,
  response = null,
}: {
  request: InternalRequest;
  curated?: InternalRequest | null;
  audit?: OverrideAudit | null;
  response?: InternalResponse | null;
}): ExchangeDetail {
  return {
    entry: {
      id: "exchange-1",
      ts: new Date("2026-01-01T12:00:00Z").toISOString(),
      provider: "codex",
      model: "codex/gpt-5-codex",
      path: "exchanges/test/",
      req: {
        system_parts: request.system.length,
        system_chars: 0,
        tools_count: request.tools.length,
        tools_chars: 0,
        messages_count: request.messages.length,
        messages_chars: 0,
        total_chars: 0,
      },
      pipeline: null,
      res: null,
      mutated_manually: false,
    },
    request_ir: request as unknown as Record<string, unknown>,
    request_curated_ir: curated ? (curated as unknown as Record<string, unknown>) : null,
    request_audit: audit,
    response_ir: response ? (response as unknown as Record<string, unknown>) : null,
    transport: null,
    events: null,
    turn: null,
    transport_diagnostics: [],
    codex_derived_artifacts: null,
  };
}

function renderTab(detail: ExchangeDetail, props: { expandAll?: boolean } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <InspectTab detail={detail} expandAll={props.expandAll} />
    </QueryClientProvider>,
  );
}

describe("InspectTab", () => {
  beforeEach(() => {
    useUIStore.setState({ autoExpandBlocks: true });
  });

  it("mounts every inspect body when expandAll overrides collapsed defaults", () => {
    useUIStore.setState({ autoExpandBlocks: false });
    const systemText = `${"system export body ".repeat(20)}END`;
    const messageText = `${"message export body ".repeat(20)}END`;
    const responseText = `${"response export body ".repeat(20)}END`;
    const toolDescription = `${"tool export description ".repeat(20)}END`;
    const detail = makeDetail({
      request: makeRequest({
        system: [{ type: "text", text: systemText }],
        tools: [
          {
            name: "mcp__demo__expand_all_tool",
            description: toolDescription,
            input_schema: { type: "object", properties: { payload: { type: "string" } } },
          },
        ],
        messages: [{ role: "user", content: [{ type: "text", text: messageText }] }],
      }),
      response: {
        id: "response-1",
        model: "gpt-5-codex",
        provider: "codex",
        stop_reason: null,
        usage: {
          input_tokens: 1,
          output_tokens: 1,
          cache_creation_input_tokens: 0,
          cache_read_input_tokens: 0,
        },
        content: [{ type: "text", text: responseText }],
        provider_extras: {},
      },
    });

    const { unmount } = renderTab(detail);

    expect(screen.queryByDisplayValue(systemText)).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue(messageText)).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue(toolDescription)).not.toBeInTheDocument();
    expect(screen.queryByText(responseText)).not.toBeInTheDocument();
    unmount();

    renderTab(detail, { expandAll: true });

    expect(screen.getByDisplayValue(systemText)).toBeInTheDocument();
    expect(screen.getByDisplayValue(messageText)).toBeInTheDocument();
    expect(screen.getByDisplayValue(toolDescription)).toBeInTheDocument();
    expect(screen.getByText(responseText)).toBeInTheDocument();
  });

  it("does not render sampling controls in the inspect panel", () => {
    const detail = makeDetail({
      request: makeRequest(),
      curated: makeRequest({
        sampling: {
          max_tokens: 2048,
          temperature: 0.3,
          top_p: null,
          top_k: null,
          stop_sequences: ["END"],
        },
      }),
    });

    renderTab(detail);

    expect(screen.queryByLabelText("Max tokens")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Temperature")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Stop sequences")).not.toBeInTheDocument();
  });

  it("does not render provider extras controls in the inspect panel", () => {
    const detail = makeDetail({
      request: makeRequest({
        provider_extras: {
          thinking: { type: "adaptive", display: "summarized" },
          output_config: { effort: "medium" },
        },
      }),
      curated: makeRequest({
        provider_extras: {
          thinking: { type: "enabled", budget_tokens: 8192, display: "omitted" },
          output_config: { effort: "high" },
        },
      }),
    });

    renderTab(detail);

    expect(screen.queryByLabelText("Budget")).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "enabled" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "omitted" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "high" })).not.toBeInTheDocument();
  });

  it("renders truncate_tool_result with the curated truncated text instead of the original", () => {
    const originalText = "A".repeat(220);
    const truncatedText = `${"A".repeat(80)} [truncated]`;
    const detail = makeDetail({
      request: makeRequest({
        messages: [
          {
            role: "assistant",
            content: [{ type: "tool_use", id: "tu-1", name: "bash", input: { cmd: "ls" } }],
          },
          {
            role: "user",
            content: [
              {
                type: "tool_result",
                tool_use_id: "tu-1",
                content: [{ type: "text", text: originalText }],
                is_error: false,
              },
            ],
          },
        ],
      }),
      curated: makeRequest({
        messages: [
          {
            role: "assistant",
            content: [{ type: "tool_use", id: "tu-1", name: "bash", input: { cmd: "ls" } }],
          },
          {
            role: "user",
            content: [
              {
                type: "tool_result",
                tool_use_id: "tu-1",
                content: [{ type: "text", text: truncatedText }],
                is_error: false,
              },
            ],
          },
        ],
      }),
      audit: makeAudit([
        {
          kind: "truncate_tool_result",
          target: "toolresult:tu-1",
          applied: true,
          chars_delta: truncatedText.length - originalText.length,
          curated_value: truncatedText,
        },
      ]),
    });

    renderTab(detail);

    expect(screen.getByText("truncated")).toBeInTheDocument();
    expect(screen.getByText(truncatedText)).toBeInTheDocument();
    expect(screen.queryByText(originalText)).not.toBeInTheDocument();
  });

  it("does not render truncate_tool_result when the final curated request removed that tool result", () => {
    const originalText = "A".repeat(220);
    const truncatedText = `${"A".repeat(80)} [truncated]`;
    const detail = makeDetail({
      request: makeRequest({
        messages: [
          {
            role: "assistant",
            content: [{ type: "tool_use", id: "tu-1", name: "bash", input: { cmd: "ls" } }],
          },
          {
            role: "user",
            content: [
              {
                type: "tool_result",
                tool_use_id: "tu-1",
                content: [{ type: "text", text: originalText }],
                is_error: false,
              },
            ],
          },
        ],
      }),
      curated: makeRequest({
        messages: [
          {
            role: "assistant",
            content: [{ type: "tool_use", id: "tu-1", name: "bash", input: { cmd: "ls" } }],
          },
        ],
      }),
      audit: makeAudit([
        {
          kind: "truncate_tool_result",
          target: "toolresult:tu-1",
          applied: true,
          chars_delta: truncatedText.length - originalText.length,
          curated_value: truncatedText,
        },
        {
          kind: "message_block_toggle",
          target: "msg:1:blk:0",
          applied: true,
          chars_delta: -originalText.length,
          curated_value: null,
        },
      ]),
    });

    renderTab(detail);

    expect(screen.queryByText(truncatedText)).not.toBeInTheDocument();
    expect(screen.getByText(originalText)).toBeInTheDocument();
  });
});
