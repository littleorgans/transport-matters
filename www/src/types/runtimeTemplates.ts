// Runtime template browse shapes returned by `GET /v1/runtime-templates`.
// Mirrors `RuntimeTemplateSummary` (api: transport_matters/runtime_templates.py).
// The endpoint serialises with `exclude_none=True`, so optional fields are
// ABSENT (not null) when unset — except `recommended_model`, which is set to
// `null` explicitly when a template ships no recommendation.

/** Vendors a template's capabilities declare support for. */
export type RuntimeTemplateVendor = "anthropic" | "openai";

/**
 * Harness a template recommends. Broader than the captured-run set: only
 * `claude`/`codex` (the {@link HarnessName} captured-run providers) are
 * spawnable today; `opencode`/`pi` are display-only this slice.
 */
export type RuntimeTemplateHarness = "claude" | "codex" | "opencode" | "pi";

export type RuntimeTemplateEffort = "low" | "medium" | "high" | "xhigh";

export interface RecommendedModelDefault {
  harness?: RuntimeTemplateHarness | null;
  vendor?: RuntimeTemplateVendor | null;
}

export interface RecommendedVendorModel {
  model?: string | null;
  effort?: RuntimeTemplateEffort | null;
}

export interface RecommendedModel {
  default?: RecommendedModelDefault | null;
  by_vendor?: Partial<Record<RuntimeTemplateVendor, RecommendedVendorModel>> | null;
}

/** One agent/runtime template, as listed by the browse endpoint. */
export interface RuntimeTemplateSummary {
  name: string;
  vendors: RuntimeTemplateVendor[];
  required_capabilities: string[];
  recommended_model: RecommendedModel | null;
}

export interface RuntimeTemplatesResponse {
  items: RuntimeTemplateSummary[];
}
