import { forward } from "@/lib/backend";

export async function PUT(request: Request) {
  const body = await request.text();
  if (body.length > 2000) return Response.json({ message: "Too many levels." }, { status: 413 });
  return forward(`/api/v1/settings/watch-levels?asset=${encodeURIComponent(new URL(request.url).searchParams.get("asset") ?? "gold")}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body,
  });
}
