<script lang="ts">
  import { base } from "$app/paths";
  import { goto } from "$app/navigation";
  import { ApiError, setup } from "$lib/api";
  import Button from "$lib/components/Button.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import { toast } from "$lib/stores/toast";

  let step = 1;
  let username = "";
  let password = "";
  let confirm = "";
  let busy = false;
  let error = "";

  $: strong = password.length >= 8;
  $: match = password === confirm && confirm.length > 0;

  function next() {
    error = "";
    if (step === 1 && !username.trim()) {
      error = "Choose a username to continue.";
      return;
    }
    step += 1;
  }

  async function finish() {
    error = "";
    if (!strong) {
      error = "Password must be at least 8 characters.";
      return;
    }
    if (!match) {
      error = "Passwords do not match.";
      return;
    }
    busy = true;
    try {
      await setup(username.trim(), password);
      // Re-run the SSR auth guard with the new session.
      await goto(base + "/dashboard", { invalidateAll: true });
    } catch (e) {
      error = e instanceof ApiError ? e.message : "Setup failed.";
    } finally {
      busy = false;
    }
  }

  const stepMeta = [
    { n: 1, label: "Admin account" },
    { n: 2, label: "Password" },
    { n: 3, label: "Done" },
  ];
</script>

<svelte:head><title>Set up · MyPilot</title></svelte:head>

<div class="flex min-h-[100dvh] items-center justify-center p-6">
  <div class="w-full max-w-md">
    <div class="mb-8 flex flex-col items-center text-center">
      <div class="grid h-11 w-11 place-items-center rounded-xl bg-accent text-accent-fg"><Icon name="gauge" size={24} strokeWidth={2.2} /></div>
      <h1 class="mt-4 text-2xl font-semibold tracking-tight text-fg">Set up MyPilot</h1>
      <p class="mt-1.5 text-sm text-fg-muted">Create the administrator account for your control plane.</p>
    </div>

    <!-- stepper -->
    <div class="mb-8 flex items-center justify-center gap-2">
      {#each stepMeta as s, i}
        <div class="flex items-center gap-2">
          <div
            class="grid h-7 w-7 place-items-center rounded-full border text-xs font-semibold transition
              {step > s.n ? 'border-accent bg-accent text-accent-fg' : step === s.n ? 'border-accent text-accent' : 'border-line text-fg-subtle'}">
            {#if step > s.n}<Icon name="check" size={14} />{:else}{s.n}{/if}
          </div>
          {#if i < stepMeta.length - 1}
            <div class="h-px w-8 {step > s.n ? 'bg-accent' : 'bg-line'}"></div>
          {/if}
        </div>
      {/each}
    </div>

    <div class="card panel-pad">
      {#if error}
        <div class="mb-4 flex items-center gap-2.5 rounded-md border border-danger/40 bg-danger-soft px-3.5 py-2.5 text-sm text-danger">
          <Icon name="alert-triangle" size={16} class="shrink-0" />{error}
        </div>
      {/if}

      {#if step === 1}
        <form on:submit|preventDefault={next} class="space-y-4">
          <div>
            <label class="label" for="su">Administrator username</label>
            <input id="su" class="input" autocomplete="username" bind:value={username} placeholder="owner" />
            <p class="hint">This is the account you'll use to manage every device.</p>
          </div>
          <Button type="submit" variant="primary" class="w-full" iconRight="chevron-right">Continue</Button>
        </form>
      {:else if step === 2}
        <form on:submit|preventDefault={finish} class="space-y-4">
          <div>
            <label class="label" for="sp">Password</label>
            <input id="sp" type="password" class="input" autocomplete="new-password" bind:value={password} placeholder="At least 8 characters" />
            <p class="mt-1.5 flex items-center gap-1.5 text-xs {strong ? 'text-success' : 'text-fg-subtle'}">
              <Icon name={strong ? "check" : "minus"} size={12} /> At least 8 characters
            </p>
          </div>
          <div>
            <label class="label" for="sc">Confirm password</label>
            <input id="sc" type="password" class="input" autocomplete="new-password" bind:value={confirm} placeholder="Re-enter password" />
            {#if confirm.length > 0}
              <p class="mt-1.5 flex items-center gap-1.5 text-xs {match ? 'text-success' : 'text-danger'}">
                <Icon name={match ? "check" : "x"} size={12} /> {match ? "Passwords match" : "Passwords do not match"}
              </p>
            {/if}
          </div>
          <div class="flex gap-2">
            <Button variant="ghost" icon="chevron-left" on:click={() => (step = 1)}>Back</Button>
            <Button type="submit" variant="primary" class="flex-1" loading={busy} disabled={!strong || !match}>
              Create account
            </Button>
          </div>
        </form>
      {/if}
    </div>

    <p class="mt-6 text-center text-sm text-fg-muted">
      Already set up?
      <a href={base + "/login"} class="font-medium text-accent hover:underline">Sign in</a>
    </p>
  </div>
</div>
