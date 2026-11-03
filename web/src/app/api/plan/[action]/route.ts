import { forward } from "@/lib/backend";

const ACTIONS = new Set(["purchased", "restart"]);

export async function POST(request: Request, { params }: { params: Promise<{ action: string }> }) {
  const { action } = await params;
  if (!ACTIONS.has(action)) return Response.json({ message: "Unknown action." }, { status: 404 });
  return forward(`/api/v1/plan/${action}?asset=${encodeURIComponent(new URL(request.url).searchParams.get("asset") ?? "gold")}`, { method: "POST" });
}
