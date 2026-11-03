import { forward } from "@/lib/backend";
export async function GET() { return forward("/api/v1/assets", { method: "GET" }); }
