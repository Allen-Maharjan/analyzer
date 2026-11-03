import { AppShell, ErrorState, Section } from "@/components/AppShell";
import { AiSettingsForm } from "@/components/AiSettingsForm";
import { WatchLevelsForm } from "@/components/WatchLevelsForm";
import type { AiOverview } from "@/lib/ai";
import { withAsset, type Asset } from "@/lib/asset";
import { BackendError, backend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function SettingsPage({ searchParams }: { searchParams: Promise<{ asset?: string }> }) {
  const { asset = "gold" } = await searchParams;
  let metadata: Asset | undefined;
  let levels: number[];
  let ai: AiOverview;
  try {
    [levels, ai, metadata] = await Promise.all([
      backend<{ levels: number[] }>(withAsset("/api/v1/settings/watch-levels", asset)).then((r) => r.levels),
      backend<AiOverview>(withAsset("/api/v1/ai", asset)),
      backend<Asset[]>("/api/v1/assets").then(items => items.find(item => item.id === asset)),
    ]);
    if (!metadata) throw new Error("Unknown asset.");
  } catch (error) {
    return (
      <AppShell asset={asset}>
        <ErrorState message={error instanceof BackendError ? error.message : "Something went wrong."} />
      </AppShell>
    );
  }
  return (
    <AppShell asset={asset}>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <Section title="Watch levels">
          <p className="mb-3 text-sm leading-relaxed text-ink-2">
            World {metadata.label.toLowerCase()} prices you want the app to keep an eye on. If the price falls through one of these and keeps falling,
            the advice will lean towards waiting.
          </p>
          <WatchLevelsForm key={asset} initial={levels} asset={asset} />
        </Section>
        <Section title="AI analysis">
          <p className="mb-3 text-sm leading-relaxed text-ink-2">
            The AI reads the app's numbers and writes a short summary. Choose an installed AI tool or OpenRouter free models.
          </p>
          <AiSettingsForm settings={ai.settings} runner={ai.runner} />
        </Section>
        <Section title="Account">
          <form action="/api/logout" method="post">
            <button type="submit" className="min-h-11 rounded-md border border-line px-4 text-sm font-medium hover:bg-hover">
              Sign out
            </button>
          </form>
        </Section>
      </div>
    </AppShell>
  );
}
