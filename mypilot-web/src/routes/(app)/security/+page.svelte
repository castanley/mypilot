<script lang="ts">
  import ComingSoon from "$lib/components/ComingSoon.svelte";
  import { comingSoonMeta } from "$lib/nav";
  const m = comingSoonMeta.security;
</script>

<svelte:head><title>{m.title} · MyPilot</title></svelte:head>
<ComingSoon icon={m.icon} title={m.title} description={m.description} bullets={m.bullets} />
