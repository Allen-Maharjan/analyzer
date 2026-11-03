import { cookies } from "next/headers";

import { seeOther } from "@/lib/redirect";
import { SESSION_COOKIE } from "@/lib/session";

export async function POST() {
  (await cookies()).delete(SESSION_COOKIE);
  return seeOther("/login");
}
