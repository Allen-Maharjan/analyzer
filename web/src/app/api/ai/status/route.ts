import { backend } from "@/lib/backend";
import type { AiOverview } from "@/lib/ai";

export async function GET(request: Request) {
  try {
    const ai = await backend<AiOverview>(`/api/v1/ai?asset=${encodeURIComponent(new URL(request.url).searchParams.get("asset") ?? "gold")}`);
    return Response.json({ status: ai.latest_run?.status ?? null });
  } catch {
    return Response.json({ status: null }, { status: 503 });
  }
}
