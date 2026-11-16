import { forward } from "@/lib/backend";

const ACTIONS: Record<string, string> = {
  status: "/api/v1/push/status",
  subscribe: "/api/v1/push/subscriptions",
  unsubscribe: "/api/v1/push/subscriptions/remove",
  test: "/api/v1/push/test",
};

/** Browser notifications: status, subscribe, unsubscribe and test, all POST with a JSON body. */
export async function POST(request: Request, { params }: { params: Promise<{ action: string }> }) {
  const { action } = await params;
  const path = ACTIONS[action];
  if (!path) return Response.json({ message: "Unknown action." }, { status: 404 });
  const body = await request.text();
  return forward(path, { method: "POST", headers: { "content-type": "application/json" }, body: body || "null" });
}
