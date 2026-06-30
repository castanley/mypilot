<script lang="ts">
  import { afterNavigate } from "$app/navigation";
  import Sidebar from "$lib/components/Sidebar.svelte";
  import TopBar from "$lib/components/TopBar.svelte";
  import { getHealth } from "$lib/api";
  import { onMount } from "svelte";
  import { fly } from "svelte/transition";

  export let data: { user: { username: string } | null };

  let drawerOpen = false;
  let cpOnline = true;

  onMount(async () => {
    try {
      const h = await getHealth();
      cpOnline = h.ok;
    } catch {
      cpOnline = false;
    }
  });

  // Close the mobile drawer AFTER navigation finishes and the new page has rendered — NOT on click.
  // Closing it on click animated the drawer away while the old page was still mounted, so for a beat
  // you saw the previous page behind the collapsing drawer before the new one swapped in (the "flash").
  // afterNavigate fires once the new content is in the DOM, so the drawer reveals the right page.
  afterNavigate(() => {
    drawerOpen = false;
  });
</script>

<div class="flex h-[100dvh] overflow-hidden bg-bg">
  <!-- Desktop sidebar -->
  <aside class="hidden w-64 shrink-0 border-r border-line bg-bg-subtle lg:block">
    <Sidebar />
  </aside>

  <!-- Mobile drawer -->
  {#if drawerOpen}
    <div class="fixed inset-0 z-40 lg:hidden">
      <div
        class="absolute inset-0 bg-black/60 backdrop-blur-sm"
        transition:fly={{ duration: 0 }}
        on:click={() => (drawerOpen = false)}
        role="presentation"></div>
      <aside
        class="absolute left-0 top-0 h-full w-72 border-r border-line bg-bg-subtle shadow-2xl"
        transition:fly={{ x: -288, duration: 220 }}>
        <!-- No on:navigate close here: afterNavigate closes the drawer once the new page is rendered,
             so it never reveals the old page mid-collapse. -->
        <Sidebar />
      </aside>
    </div>
  {/if}

  <div class="flex min-w-0 flex-1 flex-col">
    <TopBar online={cpOnline} username={data?.user?.username ?? "admin"} on:menu={() => (drawerOpen = true)} />
    <main class="flex-1 overflow-y-auto overflow-x-hidden">
      <div class="mx-auto w-full min-w-0 max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <slot />
      </div>
    </main>
  </div>
</div>
