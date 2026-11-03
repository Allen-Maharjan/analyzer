import { authConfigured } from "@/lib/session";

export const dynamic = "force-dynamic";

const ERRORS: Record<string, string> = {
  wrong: "That password isn't right. Try again.",
  setup: "Sign-in isn't set up yet. Set OWNER_PASSWORD and SESSION_SECRET in .env, then restart the app.",
};

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string; next?: string }> }) {
  const { error, next } = await searchParams;
  const message = !authConfigured() ? ERRORS.setup : error ? ERRORS[error] : null;
  const safeNext = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
  return (
    <main className="mx-auto grid min-h-dvh max-w-sm content-center px-4">
      <h1 className="text-2xl font-semibold tracking-tight">Gold Advisor</h1>
      <p className="mt-1 text-ink-2">Sign in to see today's advice.</p>
      <form action="/api/login" method="post" className="mt-8 grid gap-4">
        <input type="hidden" name="next" value={safeNext} />
        <label className="grid gap-1.5">
          <span className="text-sm font-medium">Password</span>
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
            autoFocus
            className="min-h-11 rounded-xl border border-line bg-panel px-3 text-base"
          />
        </label>
        {message && (
          <p role="alert" className="text-sm text-wait">
            {message}
          </p>
        )}
        <button type="submit" className="min-h-11 rounded-xl bg-accent px-4 font-semibold text-white hover:bg-accent-hover">
          Sign in
        </button>
      </form>
    </main>
  );
}
