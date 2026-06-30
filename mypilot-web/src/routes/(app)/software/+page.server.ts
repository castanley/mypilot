import type { PageServerLoad } from "./$types";
import { serverGet } from "$lib/server/api";
import type { DeviceSummary, SoftwareReleaseOut } from "$lib/types";

// SSR: the release catalog + a fleet version overview. Per-device update/rollback (offroad-gated,
// audited) lives on each device's Software tab.
export const load: PageServerLoad = async ({ request }) => {
  const cookie = request.headers.get("cookie") ?? "";
  const [releases, devices] = await Promise.all([
    serverGet<SoftwareReleaseOut[]>("/software/releases", cookie).catch(
      () => [] as SoftwareReleaseOut[],
    ),
    serverGet<DeviceSummary[]>("/devices", cookie).catch(() => [] as DeviceSummary[]),
  ]);
  return { releases, devices };
};
