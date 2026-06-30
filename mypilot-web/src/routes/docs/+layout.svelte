<script lang="ts">
  import { base } from "$app/paths";
  import Icon from "$lib/components/Icon.svelte";

  // `site` from docs/+layout.server.ts; `user` from the root layout.
  export let data: {
    site: { project_name: string; stack_url: string; source_url: string };
    user: { username: string } | null;
  };

  $: name = data.site?.project_name || "MyPilot";
  $: source = data.site?.source_url || "";
  $: signedIn = !!data.user;
</script>

<div class="min-h-[100dvh] bg-bg text-fg">
  <header class="sticky top-0 z-30 border-b border-line bg-bg/80 backdrop-blur-md">
    <div class="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
      <a href={base + "/"} class="flex items-center gap-2.5">
        <div class="grid h-9 w-9 place-items-center rounded-lg bg-accent text-accent-fg shadow-sm">
          <Icon name="gauge" size={20} strokeWidth={2.2} />
        </div>
        <span class="text-sm font-semibold tracking-tight">{name}</span>
        <span class="text-sm text-fg-subtle">/ docs</span>
      </a>
      <nav class="flex items-center gap-2">
        {#if source}
          <a href={source} target="_blank" rel="noreferrer" class="btn btn-ghost btn-sm hidden sm:inline-flex">
            <Icon name="git-branch" size={15} /> Source
          </a>
        {/if}
        <a href={base + "/"} class="btn btn-ghost btn-sm hidden sm:inline-flex">Back to site</a>
        {#if signedIn}
          <a href={base + "/dashboard"} class="btn btn-primary btn-sm">Open dashboard</a>
        {:else}
          <a href={base + "/login"} class="btn btn-primary btn-sm">Log in</a>
        {/if}
      </nav>
    </div>
  </header>

  <slot />

  <footer class="mx-auto max-w-6xl px-4 py-10 sm:px-6">
    <div class="flex flex-col items-start justify-between gap-3 border-t border-line pt-6 text-sm text-fg-subtle sm:flex-row sm:items-center">
      <div class="flex items-center gap-2">
        <Icon name="gauge" size={16} class="text-fg-muted" />
        <span>{name} · documentation</span>
      </div>
      <div class="flex items-center gap-4">
        <a href={base + "/docs"} class="hover:text-fg">All docs</a>
        {#if source}<a href={source} target="_blank" rel="noreferrer" class="hover:text-fg">Source</a>{/if}
        <a href={base + "/"} class="hover:text-fg">Home</a>
      </div>
    </div>
  </footer>
</div>
