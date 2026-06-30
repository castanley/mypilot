<script lang="ts">
  import { base } from "$app/paths";
  import Icon from "$lib/components/Icon.svelte";
  import type { DocGroup } from "$lib/server/docs";

  export let data: {
    groups: DocGroup[];
    site: { project_name: string; source_url: string };
  };

  $: name = data.site?.project_name || "MyPilot";
</script>

<svelte:head>
  <title>Documentation — {name}</title>
  <meta name="description" content="Guides for self-hosting, forking, flashing a device, and operating {name}." />
</svelte:head>

<section class="relative overflow-hidden border-b border-line">
  <div class="grid-noise absolute inset-0 opacity-50"></div>
  <div class="absolute -right-32 -top-32 h-80 w-80 rounded-full bg-accent/15 blur-3xl"></div>
  <div class="relative mx-auto max-w-6xl px-4 py-14 sm:px-6 sm:py-16">
    <span class="badge badge-neutral"><Icon name="logs" size={12} /> Documentation</span>
    <h1 class="mt-4 max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">
      Everything you need to run {name}
    </h1>
    <p class="mt-3 max-w-2xl text-fg-muted">
      Deploy the stack, make it your own, flash a device, and take it to production. These pages
      render straight from the <span class="text-fg">docs/</span> folder in the repo.
    </p>
  </div>
</section>

<div class="mx-auto max-w-6xl px-4 py-12 sm:px-6">
  <div class="space-y-12">
    {#each data.groups as group}
      <section>
        <h2 class="text-lg font-semibold tracking-tight">{group.label}</h2>
        <div class="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {#each group.items as item}
            <a href={base + "/docs/" + item.slug} class="card panel-pad group transition hover:border-line-strong hover:bg-surface-2">
              <div class="flex items-center justify-between">
                <h3 class="font-semibold text-fg">{item.title}</h3>
                <Icon name="chevron-right" size={16} class="text-fg-subtle transition group-hover:translate-x-0.5 group-hover:text-fg-muted" />
              </div>
              {#if item.description}
                <p class="mt-1.5 text-sm text-fg-muted">{item.description}</p>
              {/if}
            </a>
          {/each}
        </div>
      </section>
    {/each}
  </div>

  {#if data.groups.length === 0}
    <div class="card panel-pad text-fg-muted">No documentation found.</div>
  {/if}
</div>
