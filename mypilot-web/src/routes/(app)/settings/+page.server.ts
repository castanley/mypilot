import type { PageServerLoad } from "./$types";
import { serverGet } from "$lib/server/api";
import type { ForkConfig, RetentionConfig } from "$lib/types";

export const load: PageServerLoad = async ({ request }) => {
  const cookie = request.headers.get("cookie") ?? "";
  const config = await serverGet<ForkConfig>("/admin/config", cookie).catch(() => null);
  const retention = await serverGet<RetentionConfig>("/retention", cookie).catch(() => null);
  return { config, retention };
};
