<script lang="ts">
  import { base } from "$app/paths";
  import { page } from "$app/stores";
  import { navGroups, navItems } from "$lib/nav";
  import { cx } from "$lib/utils";
  import Icon from "./Icon.svelte";

  $: current = $page.url.pathname;
  // Admin-only nav items (e.g. Developer) are hidden from non-admins. The route + API enforce admin
  // too; this just keeps the entry out of their sidebar.
  $: isAdmin = !!$page.data?.user?.is_admin;
  $: visibleItems = navItems.filter((i) => !i.adminOnly || isAdmin);
  // When the account has exactly one device, link "Devices" straight at it so clicking navigates
  // ONCE to /devices/{id} — no hop through /devices and its single-device redirect (which shows as a
  // URL blip). Falls back to the plain list href when there are 0 or 2+ devices. The list highlight
  // (isActive) still keys off the item's declared href, so the entry lights up on /devices/* either way.
  $: soleDeviceId = $page.data?.soleDeviceId;
  function hrefFor(item: { href: string }): string {
    if (item.href === "/devices" && soleDeviceId) return base + "/devices/" + soleDeviceId;
    return base + item.href;
  }

  // Takes `path` explicitly so the markup expression depends on `current` and Svelte
  // re-evaluates it on every navigation (the desktop sidebar persists across routes).
  function matches(href: string, path: string): boolean {
    const full = base + href;
    if (href === "/") return path === full || path === base || path === base + "/";
    return path === full || path.startsWith(full + "/");
  }
  // "Most-specific wins": a parent like /devices must NOT highlight on /devices/pair when a more
  // specific nav item (/devices/pair) also matches. Active only if no other nav item matches with a
  // longer (more specific) href.
  function isActive(href: string, path: string): boolean {
    if (!matches(href, path)) return false;
    return !navItems.some((other) => other.href !== href && other.href.length > href.length && matches(other.href, path));
  }
</script>

<div class="flex h-full flex-col gap-1">
  <div class="flex h-16 items-center gap-2.5 px-5">
    <div class="grid h-9 w-9 place-items-center rounded-lg bg-accent text-accent-fg shadow-sm">
      <Icon name="gauge" size={20} strokeWidth={2.2} />
    </div>
    <div class="leading-tight">
      <p class="text-sm font-semibold tracking-tight text-fg">MyPilot</p>
      <p class="text-[0.6875rem] font-medium text-fg-subtle">Command Center</p>
    </div>
  </div>

  <nav class="flex-1 space-y-5 overflow-y-auto px-3 py-2">
    {#each navGroups as group}
      <div>
        <p class="section-label px-3 pb-2">{group.label}</p>
        <ul class="space-y-0.5">
          {#each visibleItems.filter((i) => i.group === group.id) as item}
            {@const active = isActive(item.href, current)}
            <li>
              <a
                href={hrefFor(item)}
                aria-current={active ? "page" : undefined}
                class={cx(
                  "group relative flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors duration-150",
                  active
                    ? "bg-accent-soft/60 text-fg"
                    : "text-fg-muted hover:bg-surface-2 hover:text-fg",
                )}>
                {#if active}
                  <span class="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r-full bg-accent"></span>
                {/if}
                <Icon
                  name={item.icon}
                  size={18}
                  class={active ? "text-accent" : "text-fg-subtle group-hover:text-fg-muted"} />
                <span class="flex-1">{item.label}</span>
                {#if item.comingSoon}
                  <span class="rounded border border-line bg-surface-2 px-1.5 py-0.5 text-[0.625rem] font-medium uppercase tracking-wide text-fg-subtle">
                    Soon
                  </span>
                {/if}
              </a>
            </li>
          {/each}
        </ul>
      </div>
    {/each}
  </nav>

  <div class="space-y-0.5 border-t border-line p-3">
    <a
      href={base + "/docs"}
      class="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg">
      <Icon name="logs" size={18} class="text-fg-subtle" />
      Documentation
    </a>
    <a
      href={base + "/style-guide"}
      class="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg">
      <Icon name="palette" size={18} class="text-fg-subtle" />
      Style guide
    </a>
  </div>
</div>
