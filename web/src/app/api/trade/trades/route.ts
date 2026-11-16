import { assetParam } from "@/lib/asset-param";
import { forward } from "@/lib/backend";

export async function POST(request: Request) {
  const asset = assetParam(request);
  if (!asset) return Response.json({ message: "Invalid asset." }, { status: 400 });
  return forward(`/api/v1/trade/trades?asset=${encodeURIComponent(asset)}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
