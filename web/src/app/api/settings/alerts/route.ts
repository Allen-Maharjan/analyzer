import { forward } from "@/lib/backend";

export async function PUT(request: Request) {
  return forward("/api/v1/settings/alerts", { method: "PUT", headers: { "content-type": "application/json" }, body: await request.text() });
}
