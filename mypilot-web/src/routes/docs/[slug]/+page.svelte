<script lang="ts">
  import { base } from "$app/paths";
  import Icon from "$lib/components/Icon.svelte";
  import type { RenderedDoc } from "$lib/server/docs";

  export let data: {
    doc: RenderedDoc;
    site: { project_name: string };
  };

  $: doc = data.doc;
  $: name = data.site?.project_name || "MyPilot";
</script>

<svelte:head>
  <title>{doc.title} — {name} docs</title>
</svelte:head>

<div class="mx-auto max-w-6xl px-4 py-10 sm:px-6">
  <a href={base + "/docs"} class="inline-flex items-center gap-1.5 text-sm text-fg-muted transition hover:text-fg">
    <Icon name="arrow-left" size={15} /> All docs
  </a>

  <div class="mt-6 lg:grid lg:grid-cols-[1fr_15rem] lg:gap-10">
    <article class="min-w-0">
      <h1 class="text-3xl font-semibold tracking-tight text-fg">{doc.title}</h1>
      <div class="doc-prose mt-6">
        {@html doc.html}
      </div>
    </article>

    {#if doc.toc.length > 1}
      <aside class="mt-10 hidden lg:mt-0 lg:block">
        <div class="sticky top-24">
          <p class="section-label mb-3">On this page</p>
          <nav class="space-y-1.5 border-l border-line">
            {#each doc.toc as h}
              <a
                href={"#" + h.id}
                class="block border-l border-transparent -ml-px pl-3 text-sm text-fg-muted transition hover:border-accent hover:text-fg {h.depth >= 3 ? 'pl-6' : ''}">
                {h.text}
              </a>
            {/each}
          </nav>
        </div>
      </aside>
    {/if}
  </div>
</div>
