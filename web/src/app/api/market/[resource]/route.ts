import { forward } from "@/lib/backend";
import { marketPath } from "@/lib/market-query";

export async function GET(request: Request, { params }: { params: Promise<{ resource: string }> }) {
  const { resource } = await params;
  const target = marketPath(resource, new URL(request.url).searchParams);
  if ("status" in target) return Response.json({ message: target.message }, { status: target.status });
  return forward(target.path, { method: "GET" });
}
