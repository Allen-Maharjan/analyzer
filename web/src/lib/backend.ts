import "server-only";

import type { components } from "@/lib/api-types";

export type Dashboard = components["schemas"]["DashboardOut"];
export type Reason = components["schemas"]["ReasonOut"];

const BASE = process.env.GA_API_URL ?? "http://localhost:8010";

export class BackendError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function backend<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new BackendError(503, "The analysis service isn't reachable.");
  }
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body = await response.json();
      message = body.message ?? body.detail ?? message;
    } catch {}
    throw new BackendError(response.status, message);
  }
  return response.json() as Promise<T>;
}

export async function backendOrNull<T>(path: string): Promise<T | null> {
  try {
    return await backend<T>(path);
  } catch (error) {
    if (error instanceof BackendError && error.status === 404) return null;
    throw error;
  }
}

/** Forward a state-changing request from a route handler, preserving status and body. */
export async function forward(path: string, init: RequestInit): Promise<Response> {
  try {
    const response = await fetch(`${BASE}${path}`, { cache: "no-store", ...init });
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: { "content-type": response.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return Response.json({ message: "The analysis service isn't reachable. Try again in a minute." }, { status: 503 });
  }
}
