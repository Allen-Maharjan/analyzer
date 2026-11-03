import { forward } from "@/lib/backend";

export async function POST(request: Request) {
  const asset = new URL(request.url).searchParams.get("asset") ?? "gold";
  const body = await request.text();
  if (body.length > 1000) return Response.json({ message: "Request too large." }, { status: 413 });
  return forward(`/api/v1/news/risk?asset=${encodeURIComponent(asset)}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
  });
}
