import type { PageServerLoad } from "./$types";
import { listDocGroups } from "$lib/server/docs";

// The index renders straight from the repo's docs/*.md — single source of truth.
export const load: PageServerLoad = async () => {
  return { groups: listDocGroups() };
};
