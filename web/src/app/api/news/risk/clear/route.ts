import { forward } from "@/lib/backend";

export async function POST(request: Request) {
  const asset = new URL(request.url).searchParams.get("asset") ?? "gold";
  return forward(`/api/v1/news/risk/clear?asset=${encodeURIComponent(asset)}`, { method: "POST" });
}
