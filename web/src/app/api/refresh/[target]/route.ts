import { forward } from "@/lib/backend";

const TARGETS = new Set(["nepal_gold", "nepal_rates", "usd_npr"]);

export async function POST(request: Request, { params }: { params: Promise<{ target: string }> }) {
  const { target } = await params;
  if (!TARGETS.has(target)) return Response.json({ message: "Unknown price source." }, { status: 404 });
  return forward(`/api/v1/refresh/${target}`, { method: "POST" });
}
