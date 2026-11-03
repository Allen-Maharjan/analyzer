import { forward } from "@/lib/backend";

export async function POST(request: Request) {
  return forward(`/api/v1/ai/request?asset=${encodeURIComponent(new URL(request.url).searchParams.get("asset") ?? "gold")}`, { method: "POST" });
}
