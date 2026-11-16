import { assetParam } from "@/lib/asset-param";
import { forward } from "@/lib/backend";

export async function GET(request: Request) {
  const asset = assetParam(request);
  if (!asset) return Response.json({ message: "Invalid asset." }, { status: 400 });
  return forward(`/api/v1/live?asset=${encodeURIComponent(asset)}`, { method: "GET" });
}
