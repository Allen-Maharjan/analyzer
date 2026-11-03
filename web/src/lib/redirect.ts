/** Same-site redirect with a relative Location, so it works behind Docker and any proxy host name. */
export function seeOther(path: string, init?: ResponseInit): Response {
  return new Response(null, { ...init, status: 303, headers: { ...(init?.headers ?? {}), Location: path } });
}
