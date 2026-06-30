<script lang="ts">
  import { base } from "$app/paths";
  import { page } from "$app/stores";
  import { ApiError, changePassword, logout } from "$lib/api";
  import { theme, toggleTheme } from "$lib/stores/theme";
  import { toast } from "$lib/stores/toast";
  import { goto } from "$app/navigation";
  import { createEventDispatcher } from "svelte";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import Modal from "./Modal.svelte";

  export let online = true;
  export let username = "admin";
  const dispatch = createEventDispatcher<{ menu: void }>();

  $: crumbs = buildCrumbs($page.url.pathname);
  function buildCrumbs(path: string): { label: string; href: string | null }[] {
    const rel = path.replace(base, "").replace(/^\//, "");
    if (!rel) return [{ label: "Dashboard", href: null }];
    const parts = rel.split("/");
    const out: { label: string; href: string | null }[] = [];
    let acc = "";
    parts.forEach((p, i) => {
      acc += "/" + p;
      const label = /^[0-9a-f]{8,}$/i.test(p)
        ? p.slice(0, 8)
        : p.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
      out.push({ label, href: i === parts.length - 1 ? null : base + acc });
    });
    return out;
  }

  let userOpen = false;
  async function doLogout() {
    await logout();
    // Re-run the SSR auth guard with the cleared session.
    await goto(base + "/login", { invalidateAll: true });
  }

  let pwOpen = false;
  let curPw = "";
  let newPw = "";
  let newPw2 = "";
  let pwBusy = false;
  function openChangePw() {
    userOpen = false;
    curPw = newPw = newPw2 = "";
    pwOpen = true;
  }
  $: pwValid = curPw.length > 0 && newPw.length >= 8 && newPw === newPw2;
  async function submitChangePw() {
    if (!pwValid) return;
    pwBusy = true;
    try {
      await changePassword(curPw, newPw);
      toast.success("Password changed", "Other sessions were signed out.");
      pwOpen = false;
    } catch (e) {
      toast.error("Couldn't change password", e instanceof ApiError ? e.message : undefined);
    } finally {
      pwBusy = false;
    }
  }
</script>

<header class="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-line bg-bg/80 px-4 backdrop-blur-md sm:px-6">
  <button
    type="button"
    class="btn btn-ghost btn-icon-sm lg:hidden"
    aria-label="Open menu"
    on:click={() => dispatch("menu")}>
    <Icon name="menu" size={20} />
  </button>

  <nav class="flex min-w-0 flex-1 items-center gap-1.5 text-sm" aria-label="Breadcrumb">
    {#each crumbs as crumb, i}
      {#if i > 0}
        <Icon name="chevron-right" size={14} class="shrink-0 text-fg-subtle" />
      {/if}
      {#if crumb.href}
        <a href={crumb.href} class="truncate text-fg-muted hover:text-fg">{crumb.label}</a>
      {:else}
        <span class="truncate font-medium text-fg">{crumb.label}</span>
      {/if}
    {/each}
  </nav>

  <div class="flex items-center gap-1.5">
    <span
      class="hidden items-center gap-2 rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs font-medium sm:inline-flex"
      title={online ? "Control plane reachable" : "Control plane unreachable"}>
      <span class="dot {online ? 'bg-success' : 'bg-danger'}"></span>
      <span class="text-fg-muted">{online ? "Connected" : "Offline"}</span>
    </span>

    <button
      type="button"
      class="btn btn-ghost btn-icon-sm"
      aria-label="Toggle theme"
      on:click={toggleTheme}>
      <Icon name={$theme === "dark" ? "sun" : "moon"} size={18} />
    </button>

    <div class="relative">
      <button
        type="button"
        class="btn btn-ghost btn-icon-sm"
        aria-label="Account menu"
        aria-expanded={userOpen}
        on:click={() => (userOpen = !userOpen)}>
        <span class="grid h-7 w-7 place-items-center rounded-full bg-accent-soft text-accent">
          <Icon name="user" size={15} />
        </span>
      </button>
      {#if userOpen}
        <button
          class="fixed inset-0 z-10 cursor-default"
          aria-label="Close menu"
          on:click={() => (userOpen = false)}></button>
        <div class="card absolute right-0 z-20 mt-2 w-52 overflow-hidden p-1.5 shadow-xl">
          <div class="px-3 py-2">
            <p class="text-sm font-semibold text-fg">{username}</p>
            <p class="text-xs text-fg-subtle">Administrator</p>
          </div>
          <div class="divider my-1"></div>
          <button
            type="button"
            on:click={openChangePw}
            class="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-fg-muted transition hover:bg-surface-2 hover:text-fg">
            <Icon name="lock" size={16} />
            Change password
          </button>
          <button
            type="button"
            on:click={doLogout}
            class="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-fg-muted transition hover:bg-surface-2 hover:text-fg">
            <Icon name="log-out" size={16} />
            Sign out
          </button>
        </div>
      {/if}
    </div>
  </div>
</header>

<Modal open={pwOpen} title="Change password" size="sm" on:close={() => (pwOpen = false)}>
  <div class="space-y-3">
    <div>
      <label class="label" for="cur-pw">Current password</label>
      <input id="cur-pw" type="password" class="input" bind:value={curPw} autocomplete="current-password" />
    </div>
    <div>
      <label class="label" for="new-pw">New password</label>
      <input id="new-pw" type="password" class="input" bind:value={newPw} autocomplete="new-password" />
      <p class="hint">At least 8 characters.</p>
    </div>
    <div>
      <label class="label" for="new-pw2">Confirm new password</label>
      <input id="new-pw2" type="password" class="input" bind:value={newPw2} autocomplete="new-password" />
      {#if newPw2 && newPw !== newPw2}<p class="error-text">Passwords don't match.</p>{/if}
    </div>
  </div>
  <svelte:fragment slot="footer">
    <Button variant="ghost" on:click={() => (pwOpen = false)}>Cancel</Button>
    <Button variant="primary" loading={pwBusy} disabled={!pwValid} on:click={submitChangePw}>
      Change password
    </Button>
  </svelte:fragment>
</Modal>
