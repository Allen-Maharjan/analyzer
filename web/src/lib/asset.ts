export type Asset = { id: string; label: string; instrument: string; quote_currency: string; price_unit: string; local_label: string };
export function withAsset(path: string, asset: string): string {
  return `${path}${path.includes("?") ? "&" : "?"}asset=${encodeURIComponent(asset)}`;
}
