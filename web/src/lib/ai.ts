export type AiOutput = {
  plain_summary: string;
  outlook: "bearish" | "neutral" | "bullish";
  adjustment: number;
  adjustment_reason: string;
  reasons: { text: string; evidence_ids: string[] }[];
  risks: string[];
  watch_levels: string[];
};

export type AiOverview = {
  result: {
    id: number;
    snapshot_id: string;
    provider: string;
    model: string | null;
    cli_version: string | null;
    finished_at: string;
    output: AiOutput;
    deterministic_score: number | null;
    adjusted_score: number | null;
  } | null;
  latest_run: {
    id: number;
    status: "queued" | "running" | "succeeded" | "invalid" | "failed" | "expired";
    provider: string;
    created_at: string;
    finished_at: string | null;
    error: string | null;
    trigger: string;
  } | null;
  settings: { provider: "codex" | "claude" | "kiro" | "openrouter"; model: string | null; automatic: boolean };
  runner: { seen_at: string; providers: Record<string, { ready: boolean; version?: string; error?: string }> } | null;
};

export const PROVIDER_NAMES: Record<string, string> = { codex: "Codex", claude: "Claude Code", kiro: "Kiro", openrouter: "OpenRouter (free models)" };
