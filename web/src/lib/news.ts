export type NewsArticle = {
  id: string;
  title: string;
  publisher: string;
  published_at: string;
  url: string;
  excerpt: string;
  can_flag: boolean;
};

export type NewsOverview = {
  status: { state: "fresh" | "stale" | "empty" | "unavailable" | "pending"; refreshed_at: string | null; refreshing: boolean; last_attempt_failed: boolean };
  articles: NewsArticle[];
  ai: { summary: string; cited: string[]; finished_at: string } | null;
  risk: { article_id: string; reason: string; confirmed_at: string; expires_at: string } | null;
};
