<script lang="ts">
  import { base } from "$app/paths";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { ApiError, login } from "$lib/api";
  import Button from "$lib/components/Button.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import { toast } from "$lib/stores/toast";

  // Only show the first-run setup link when the instance has no admin yet (the layout load
  // surfaces this). On first run the layout redirects /login -> /setup anyway; this covers the
  // brief pre-redirect render and keeps the prompt hidden once the instance is configured.
  $: needsSetup = Boolean($page.data?.needsSetup);

  let username = "";
  let password = "";
  let busy = false;
  let error = "";

  // Same-origin app path the guard preserved (e.g. /devices/pair?code=XXXX from a scanned QR), so
  // login lands the user back where they were headed. Reject anything that isn't a plain "/..."
  // path to avoid an open redirect.
  function safeNext(next: string | null): string | null {
    if (!next || !next.startsWith("/") || next.startsWith("//")) return null;
    return next;
  }

  async function submit() {
    error = "";
    busy = true;
    try {
      await login(username, password);
      // Re-run the SSR auth guard with the new session, landing on ?next= if present.
      const dest = safeNext($page.url.searchParams.get("next")) ?? "/dashboard";
      await goto(base + dest, { invalidateAll: true });
    } catch (e) {
      error = e instanceof ApiError ? e.message : "Sign in failed.";
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>Sign in · MyPilot</title></svelte:head>

<div class="grid min-h-[100dvh] lg:grid-cols-2">
  <!-- brand panel -->
  <div class="relative hidden flex-col justify-between overflow-hidden bg-bg-subtle p-12 lg:flex">
    <div class="grid-noise absolute inset-0 opacity-60"></div>
    <div class="absolute -right-24 -top-24 h-72 w-72 rounded-full bg-accent/20 blur-3xl"></div>
    <div class="relative flex items-center gap-2.5">
      <div class="grid h-9 w-9 place-items-center rounded-lg bg-accent text-accent-fg"><Icon name="gauge" size={20} strokeWidth={2.2} /></div>
      <span class="text-sm font-semibold tracking-tight text-fg">MyPilot</span>
    </div>
    <div class="relative max-w-md space-y-4">
      <h1 class="text-3xl font-semibold leading-tight tracking-tight text-fg">
        Your self-driving fleet, under one roof.
      </h1>
      <p class="text-fg-muted">
        Monitor presence, configure every device, and keep a complete audit trail — all self-hosted, all yours.
      </p>
      <div class="flex flex-wrap gap-2 pt-2">
        <span class="badge badge-neutral"><Icon name="shield-check" size={12} /> Self-hosted</span>
        <span class="badge badge-neutral"><Icon name="activity" size={12} /> Realtime</span>
        <span class="badge badge-neutral"><Icon name="lock" size={12} /> Audited</span>
      </div>
    </div>
    <p class="relative text-xs text-fg-subtle">MyPilot Command Center</p>
  </div>

  <!-- form panel -->
  <div class="flex items-center justify-center p-6 sm:p-12">
    <div class="w-full max-w-sm">
      <div class="mb-8 lg:hidden">
        <div class="grid h-10 w-10 place-items-center rounded-lg bg-accent text-accent-fg"><Icon name="gauge" size={22} strokeWidth={2.2} /></div>
      </div>
      <h2 class="text-2xl font-semibold tracking-tight text-fg">Sign in</h2>
      <p class="mt-1.5 text-sm text-fg-muted">Welcome back. Enter your credentials to continue.</p>

      <form on:submit|preventDefault={submit} class="mt-8 space-y-4">
        {#if error}
          <div class="flex items-center gap-2.5 rounded-md border border-danger/40 bg-danger-soft px-3.5 py-2.5 text-sm text-danger">
            <Icon name="alert-triangle" size={16} class="shrink-0" />{error}
          </div>
        {/if}
        <div>
          <label class="label" for="u">Username</label>
          <input id="u" class="input" autocomplete="username" bind:value={username} placeholder="owner" />
        </div>
        <div>
          <label class="label" for="p">Password</label>
          <input id="p" type="password" class="input" autocomplete="current-password" bind:value={password} placeholder="••••••••" />
        </div>
        <Button type="submit" variant="primary" class="w-full" loading={busy}>Sign in</Button>
      </form>

      {#if needsSetup}
        <p class="mt-6 text-center text-sm text-fg-muted">
          First time here?
          <a href={base + "/setup"} class="font-medium text-accent hover:underline">Set up your control plane</a>
        </p>
      {/if}
    </div>
  </div>
</div>
