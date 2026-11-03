import { forward } from "@/lib/backend";

export async function PUT(request: Request) {
  const body = await request.text();
  if (body.length > 500) return Response.json({ message: "Request too large." }, { status: 413 });
  return forward("/api/v1/ai/settings", { method: "PUT", headers: { "content-type": "application/json" }, body });
}
