import { error } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";
import { getDoc } from "$lib/server/docs";

export const load: PageServerLoad = async ({ params }) => {
  const doc = getDoc(params.slug);
  if (!doc) throw error(404, "That doc doesn't exist");
  return { doc };
};
