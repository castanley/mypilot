import type { PageServerLoad } from "./$types";
import { serverGet } from "$lib/server/api";
import type { AdminTool } from "$lib/types";

// The Admin hub lists admin-only utility pages. The set is discovered at runtime from
// /api/admin/tools (admin-gated; empty by default — an installed extension can register one), so the
// panel ships no per-tool entries. A non-admin gets [] (and the page shows the admin-only notice).
export const load: PageServerLoad = async ({ request, parent }) => {
  const { user } = await parent();
  const isAdmin = !!user?.is_admin;
  const cookie = request.headers.get("cookie") ?? "";
  const tools = isAdmin
    ? await serverGet<AdminTool[]>("/admin/tools", cookie).catch(() => [] as AdminTool[])
    : [];
  return { isAdmin, tools };
};
