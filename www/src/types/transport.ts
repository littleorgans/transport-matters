export interface TransportHeader {
  name: string;
  value: string;
}

export interface TransportUpgradeArtifacts {
  scheme: string;
  host: string;
  path: string;
  request_headers: TransportHeader[];
  response_status_code: number | null;
  response_headers: TransportHeader[];
}

export interface TransportHttpRequestArtifacts {
  method: string | null;
  scheme: string;
  host: string;
  path: string;
  headers: TransportHeader[];
}

export interface TransportHttpResponseArtifacts {
  status_code: number | null;
  headers: TransportHeader[];
}

export interface TransportCloseArtifacts {
  ts?: string | null;
  close_code: number | null;
  close_reason: string | null;
  closed_by_client: boolean | null;
  initial_client_frame_captured: boolean;
  client_message_count: number;
  server_message_count: number;
}

export interface TransportMessageArtifact {
  ts?: string | null;
  direction: "client" | "server";
  is_text: boolean;
  size_bytes: number;
  dropped: boolean;
  event_type: string | null;
  payload_text: string | null;
  payload_json: Record<string, unknown> | unknown[] | null;
  payload_base64: string | null;
}

interface TransportArtifactsBase {
  provider: string;
  messages: TransportMessageArtifact[];
}

export interface TransportWebSocketArtifacts extends TransportArtifactsBase {
  protocol: "websocket";
  upgrade: TransportUpgradeArtifacts;
  close: TransportCloseArtifacts | null;
}

export interface TransportHttpArtifacts extends TransportArtifactsBase {
  protocol: "http";
  request: TransportHttpRequestArtifacts | null;
  response: TransportHttpResponseArtifacts | null;
}

export type TransportArtifacts = TransportWebSocketArtifacts | TransportHttpArtifacts;

export interface TransportDiagnostic {
  severity: "info" | "warning" | "error";
  code: string;
  summary: string;
  detail: string | null;
  operator_checks: string[];
}
