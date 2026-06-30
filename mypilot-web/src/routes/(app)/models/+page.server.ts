import type { PageServerLoad } from "./$types";
import { serverGet } from "$lib/server/api";
import type { ModelOut } from "$lib/types";

// SSR: the global driving-model catalog. Per-device active model + switching lives on the
// device detail "Models" tab (it is an offroad-gated, audited action scoped to one device).
export const load: PageServerLoad = async ({ request }) => {
  const cookie = request.headers.get("cookie") ?? "";
  const models = await serverGet<ModelOut[]>("/models", cookie).catch(() => [] as ModelOut[]);
  return { models };
};
