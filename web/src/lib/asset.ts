export type Asset = { id: string; label: string; instrument: string; quote_currency: string; price_unit: string; local_label: string };
/** Assets with a Trade screen. Mirrors `AssetDefinition.tradable` in the backend, which returns 404 for the rest. */
export const TRADABLE_ASSETS = new Set(["silver"]);
export function withAsset(path: string, asset: string): string {
  return `${path}${path.includes("?") ? "&" : "?"}asset=${encodeURIComponent(asset)}`;
}
