export type TitleSource = 'manual' | 'placeholder' | 'auto';

export interface NodeRecord {
  id: string;
  title: string;
  title_source: TitleSource;
  kind: string;
  local_message_count: number;
  message_count: number;
  parent_ids?: string[];
  deletable?: boolean;
  frozen?: boolean;
  child_count?: number;
  max_children?: number;
  created_at: string;
  updated_at: string;
}

export interface EdgeRecord {
  source: string;
  target: string;
  type: string;
  context_message_count: number | null;
  deletable?: boolean;
}

export interface MessageRecord {
  role: string;
  content: string;
}

export interface ConfigStatus {
  provider: string;
  model: string;
  api_key_environment: string;
  api_key_configured: boolean;
  available_providers: ProviderOption[];
}

export interface ProviderOption {
  id: string;
  label: string;
  model: string;
  is_dev: boolean;
}

export interface UiState {
  positions?: Record<string, { x: number; y: number }>;
  split_ratio?: number;
}

export interface Snapshot {
  initialized: boolean;
  workspace_name: string;
  platform?: 'windows' | 'macos' | 'linux';
  config?: ConfigStatus;
  nodes?: NodeRecord[];
  edges?: EdgeRecord[];
  ui?: UiState;
}

export interface Conversation {
  node: NodeRecord;
  messages: MessageRecord[];
}

export interface BridgeResponse<T> {
  ok: boolean;
  data?: T;
  error?: string;
}

export interface DesktopBridge {
  [method: string]: (...args: unknown[]) => Promise<BridgeResponse<unknown>>;
}

declare global {
  interface Window {
    pywebview?: {
      api: DesktopBridge;
      platform?: string;
    };
  }
}
