<script lang="ts">
  import { base } from "$app/paths";
  import Icon from "$lib/components/Icon.svelte";

  // `site` from this page's load; `user` from the root layout load.
  export let data: {
    site: { project_name: string; stack_url: string; source_url: string };
    user: { username: string } | null;
  };

  $: name = data.site?.project_name || "MyPilot";
  $: source = data.site?.source_url || "";
  $: signedIn = !!data.user;

  const features = [
    { icon: "devices", title: "Devices & pairing", body: "Pair a comma device with a one-time, signed code. Live presence, telemetry, and remote reboot — offroad-gated and audited." },
    { icon: "settings", title: "Settings", body: "Change device settings remotely with offroad, danger, and capability gating. Every change is reconciled live and logged." },
    { icon: "routes", title: "Routes & logs", body: "Your drives and logs ingested to object storage you control. Download the real bytes, set retention, delete anything." },
    { icon: "models", title: "Models", body: "See the device's real driving models; switch and roll back — the device verifies the checksum before activating." },
    { icon: "software", title: "Software channels", body: "Release and staging channels mapped to real branches. Update and roll back, all offroad-only." },
    { icon: "backups", title: "Backups & migration", body: "Snapshot settings to JSON, diff, restore, and move config between devices." },
  ];

  const steps = [
    { n: "1", t: "Deploy the stack", d: "Clone the repo and run ./scripts/install.sh — Podman-first (Docker works too). Postgres, Redis, MinIO, API, web, Caddy." },
    { n: "2", t: "Create your admin", d: "Open your URL, set up the first admin, and change the password. Strong secrets are generated for you." },
    { n: "3", t: "Configure your fork", d: "In Settings, set your Stack URL and GitHub install source — every install URL follows. No hard-coding." },
    { n: "4", t: "Flash & pair", d: "Install your branch via the comma's Custom Software, then pair from the code shown on the device screen. No SSH." },
  ];
</script>

<svelte:head>
  <title>{name} — self-hosted control plane for your driving stack</title>
  <meta name="description" content="{name} is an open-source, self-hosted control plane for a SunnyPilot/openpilot fork. You own the device, data, routes, models, and control plane — no required cloud." />
</svelte:head>

<div class="min-h-[100dvh] bg-bg text-fg">
  <!-- nav -->
  <header class="sticky top-0 z-30 border-b border-line bg-bg/80 backdrop-blur-md">
    <div class="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
      <div class="flex items-center gap-2.5">
        <div class="grid h-9 w-9 place-items-center rounded-lg bg-accent text-accent-fg shadow-sm">
          <Icon name="gauge" size={20} strokeWidth={2.2} />
        </div>
        <span class="text-sm font-semibold tracking-tight">{name}</span>
      </div>
      <nav class="flex items-center gap-2">
        {#if source}
          <a href={source} target="_blank" rel="noreferrer" class="btn btn-ghost btn-sm hidden sm:inline-flex">
            <Icon name="git-branch" size={15} /> Source
          </a>
        {/if}
        <a href={base + "/docs"} class="btn btn-ghost btn-sm hidden sm:inline-flex">Docs</a>
        <a href="#self-host" class="btn btn-ghost btn-sm hidden sm:inline-flex">Self-host</a>
        {#if signedIn}
          <a href={base + "/dashboard"} class="btn btn-primary btn-sm">Open dashboard</a>
        {:else}
          <a href={base + "/login"} class="btn btn-primary btn-sm">Log in</a>
        {/if}
      </nav>
    </div>
  </header>

  <!-- hero -->
  <section class="relative overflow-hidden border-b border-line">
    <div class="grid-noise absolute inset-0 opacity-50"></div>
    <div class="absolute -right-32 -top-32 h-96 w-96 rounded-full bg-accent/15 blur-3xl"></div>
    <div class="relative mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
      <span class="badge badge-neutral"><Icon name="shield-check" size={12} /> Open source · Self-hosted</span>
      <h1 class="mt-5 max-w-3xl text-4xl font-semibold leading-[1.1] tracking-tight sm:text-6xl">
        Your self-driving stack, <span class="text-accent">on your own infrastructure.</span>
      </h1>
      <p class="mt-5 max-w-2xl text-lg text-fg-muted">
        {name} is a self-hosted control plane for a SunnyPilot/openpilot fork — devices, settings, routes,
        logs, models, software, and backups. You own the device, the data, and the control plane.
        <span class="text-fg">No required cloud. Your car keeps driving even if {name} is offline.</span>
      </p>
      <div class="mt-8 flex flex-wrap items-center gap-3">
        {#if signedIn}
          <a href={base + "/dashboard"} class="btn btn-primary btn-lg"><Icon name="dashboard" size={18} /> Open dashboard</a>
        {:else}
          <a href={base + "/login"} class="btn btn-primary btn-lg"><Icon name="lock" size={18} /> Log in</a>
        {/if}
        <a href="#self-host" class="btn btn-secondary btn-lg">Self-host it <Icon name="chevron-right" size={16} /></a>
      </div>
    </div>
  </section>

  <!-- features -->
  <section class="mx-auto max-w-6xl px-4 py-16 sm:px-6">
    <h2 class="text-2xl font-semibold tracking-tight sm:text-3xl">Everything, self-hosted</h2>
    <p class="mt-2 max-w-2xl text-fg-muted">A complete control panel running on infrastructure you control.</p>
    <div class="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {#each features as f}
        <div class="card p-5">
          <div class="grid h-11 w-11 place-items-center rounded-xl border border-line bg-surface-2 text-accent">
            <Icon name={f.icon} size={20} />
          </div>
          <h3 class="mt-4 text-base font-semibold">{f.title}</h3>
          <p class="mt-1.5 text-sm text-fg-muted">{f.body}</p>
        </div>
      {/each}
    </div>
  </section>

  <!-- self-host -->
  <section id="self-host" class="border-y border-line bg-bg-subtle">
    <div class="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <span class="badge badge-accent">Modular & fork-friendly</span>
      <h2 class="mt-4 text-2xl font-semibold tracking-tight sm:text-3xl">Run your own in minutes</h2>
      <p class="mt-2 max-w-2xl text-fg-muted">
        Nothing deployment-specific is hard-coded. Fork it, set your Stack URL and install source in
        Settings, point a build at it, and pair. Every step is in the docs.
      </p>
      <div class="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {#each steps as s}
          <div class="card panel-pad">
            <div class="grid h-8 w-8 place-items-center rounded-full bg-accent text-sm font-semibold text-accent-fg">{s.n}</div>
            <h3 class="mt-3 font-semibold">{s.t}</h3>
            <p class="mt-1 text-sm text-fg-muted">{s.d}</p>
          </div>
        {/each}
      </div>
      <div class="mt-6 overflow-x-auto rounded-lg border border-line bg-bg p-4">
        <pre class="mono text-sm text-fg-muted">git clone &lt;your-fork&gt; mypilot &amp;&amp; cd mypilot
./scripts/install.sh        <span class="text-fg-subtle"># Podman-first; prints your URL</span></pre>
      </div>
      <div class="mt-6 flex flex-wrap gap-3">
        <a href={base + "/docs"} class="btn btn-primary btn-lg"><Icon name="logs" size={16} /> Browse the docs</a>
        {#if source}
          <a href={source} target="_blank" rel="noreferrer" class="btn btn-secondary btn-lg"><Icon name="git-branch" size={16} /> View the source</a>
        {/if}
        {#if !signedIn}
          <a href={base + "/login"} class="btn btn-secondary btn-lg">Log in to your instance</a>
        {/if}
      </div>
    </div>
  </section>

  <!-- footer -->
  <footer class="mx-auto max-w-6xl px-4 py-10 sm:px-6">
    <div class="flex flex-col items-start justify-between gap-3 border-t border-line pt-6 text-sm text-fg-subtle sm:flex-row sm:items-center">
      <div class="flex items-center gap-2">
        <Icon name="gauge" size={16} class="text-fg-muted" />
        <span>{name} · self-hosted control plane</span>
      </div>
      <div class="flex items-center gap-4">
        <a href={base + "/docs"} class="hover:text-fg">Docs</a>
        <a href={base + "/terms"} class="hover:text-fg">Terms</a>
        {#if source}<a href={source} target="_blank" rel="noreferrer" class="hover:text-fg">Source</a>{/if}
        <a href={base + "/login"} class="hover:text-fg">Log in</a>
      </div>
    </div>
  </footer>
</div>
