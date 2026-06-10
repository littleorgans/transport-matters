export type HarnessProxyMode = "reverse" | "explicit";
export type HarnessTrustRequirement = "none" | "codex_ca_certificate";
export type HarnessShellEnvironmentPolicy =
  | "sanitized_base_url"
  | "sanitized_proxy_with_shell_excludes";
export type HarnessPassThroughPolicy = "verbatim_after_separator";

export interface HarnessCapabilities {
  startup_probe: boolean;
  disposable_probe: boolean;
  overlay_before_work: boolean;
  tool_schema_overlay: boolean;
  provider_extras_controls: boolean;
  replay: boolean;
  fork: boolean;
  transport_diagnostics: boolean;
  codex_turn_telemetry: boolean;
  websocket_artifacts: boolean;
  http_fallback_artifacts: boolean;
}

export interface HarnessDescriptor {
  id: string;
  display_name: string;
  command_name: string;
  subcommand_id: string;
  binary_option: string;
  disable_flag: string;
  proxy_mode: HarnessProxyMode;
  trust_requirement: HarnessTrustRequirement;
  shell_environment_policy: HarnessShellEnvironmentPolicy;
  pass_through_policy: HarnessPassThroughPolicy;
  capabilities: HarnessCapabilities;
}

// Managed CLI capabilities returned by GET /api/capabilities.
// Local install state for each managed CLI the desktop can spawn as a captured
// run. Distinct from HarnessCapabilities above, which describes protocol
// features for a harness.

/** The managed CLIs that can be spawned as a captured run. Doubles as the captured pane provider. */
export type CliName = "claude" | "codex";

export interface CliCapability {
  installed: boolean;
  path: string | null;
  version: string | null;
}

export interface CapabilitiesResponse {
  clis: Record<CliName, CliCapability>;
}
