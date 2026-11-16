import { forward } from "@/lib/backend";

/** Starts an update when the advice is over 20 minutes old (the API decides). */
export async function POST() {
  return forward("/api/v1/refresh/auto", { method: "POST" });
}
