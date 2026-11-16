import { assetParam } from "@/lib/asset-param";
import { forward } from "@/lib/backend";

/** Lets the page check whether newer advice exists while an update runs. */
export async function GET(request: Request) {
  const asset = assetParam(request);
  if (!asset) return Response.json({ message: "Invalid asset." }, { status: 400 });
  return forward(`/api/v1/dashboard?asset=${encodeURIComponent(asset)}`, { method: "GET" });
}
