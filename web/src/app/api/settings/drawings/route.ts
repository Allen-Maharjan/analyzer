import { forward } from "@/lib/backend";

function path(request: Request) {
  const asset = new URL(request.url).searchParams.get("asset") ?? "gold";
  return `/api/v1/settings/drawings?asset=${encodeURIComponent(asset)}`;
}

export async function GET(request: Request) {
  return forward(path(request), { method: "GET" });
}

export async function PUT(request: Request) {
  const body = await request.text();
  if (body.length > 30000) return Response.json({ message: "Too many lines to save. Delete some and try again." }, { status: 413 });
  return forward(path(request), { method: "PUT", headers: { "content-type": "application/json" }, body });
}
