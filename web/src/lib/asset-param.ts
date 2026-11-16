/** The asset query value, checked before it is forwarded to the API. */
export function assetParam(request: Request): string | null {
  const asset = new URL(request.url).searchParams.get("asset") ?? "gold";
  return /^[a-zA-Z0-9:_-]{1,64}$/.test(asset) ? asset : null;
}
