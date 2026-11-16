import { assetParam } from "@/lib/asset-param";
import { forward } from "@/lib/backend";

export async function PUT(request: Request) {
  const asset = assetParam(request);
  if (!asset) return Response.json({ message: "Invalid asset." }, { status: 400 });
  return forward(`/api/v1/trade/settings?asset=${encodeURIComponent(asset)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
