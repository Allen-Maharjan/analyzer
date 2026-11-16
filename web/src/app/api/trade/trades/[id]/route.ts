import { assetParam } from "@/lib/asset-param";
import { forward } from "@/lib/backend";

async function target(request: Request, params: Promise<{ id: string }>) {
  const { id } = await params;
  const asset = assetParam(request);
  if (!asset || !/^\d{1,18}$/.test(id)) return null;
  return `/api/v1/trade/trades/${id}?asset=${encodeURIComponent(asset)}`;
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const path = await target(request, params);
  if (!path) return Response.json({ message: "Invalid trade." }, { status: 400 });
  return forward(path, { method: "PUT", headers: { "content-type": "application/json" }, body: await request.text() });
}

export async function DELETE(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const path = await target(request, params);
  if (!path) return Response.json({ message: "Invalid trade." }, { status: 400 });
  return forward(path, { method: "DELETE" });
}
