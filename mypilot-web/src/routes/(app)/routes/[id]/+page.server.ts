import type { PageServerLoad } from "./$types";
import { serverGet } from "$lib/server/api";
import type { RouteDetail } from "$lib/types";

export const load: PageServerLoad = async ({ request, params }) => {
  const cookie = request.headers.get("cookie") ?? "";
  const route = await serverGet<RouteDetail>(`/routes/${params.id}`, cookie).catch(() => null);
  return { route };
};
