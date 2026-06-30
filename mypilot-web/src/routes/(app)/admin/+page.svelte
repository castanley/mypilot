<script lang="ts">
  import PageHeader from "$lib/components/PageHeader.svelte";
  import Card from "$lib/components/Card.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import { base } from "$app/paths";
  import type { AdminTool } from "$lib/types";

  export let data: { isAdmin: boolean; tools: AdminTool[] };
</script>

<svelte:head><title>Admin · MyPilot</title></svelte:head>

<PageHeader
  eyebrow="System"
  title="Admin"
  description="Administrative tools for this deployment." />

{#if !data.isAdmin}
  <div class="card mb-6">
    <EmptyState icon="shield-check" title="Admin only" description="Sign in as an admin to use these tools." />
  </div>
{:else if data.tools.length === 0}
  <div class="card mb-6">
    <EmptyState
      icon="module"
      title="No admin tools"
      description="No additional admin tools are installed on this deployment." />
  </div>
{:else}
  <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
    {#each data.tools as tool (tool.key)}
      <a href={base + tool.href} class="block transition hover:opacity-90">
        <Card title={tool.label} subtitle={tool.description || null} icon={tool.icon}>
          <div class="flex items-center gap-1 text-sm text-fg-muted">
            Open <Icon name="chevron-right" size={16} />
          </div>
        </Card>
      </a>
    {/each}
  </div>
{/if}
