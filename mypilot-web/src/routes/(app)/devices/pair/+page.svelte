<script lang="ts">
  import { base } from "$app/paths";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { onMount } from "svelte";
  import { ApiError, claimDevice } from "$lib/api";
  import Button from "$lib/components/Button.svelte";
  import Card from "$lib/components/Card.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import { toast } from "$lib/stores/toast";

  let code = "";
  let busy = false;
  let error = "";

  $: normalized = code.replace(/[^a-z0-9]/gi, "").toUpperCase().slice(0, 8);

  // Prefill from a scanned device QR (?code=XXXXXXXX) so the user only has to confirm.
  onMount(() => {
    const fromQr = $page.url.searchParams.get("code");
    if (fromQr) code = fromQr;
  });

  async function submit() {
    error = "";
    if (normalized.length !== 8) {
      error = "Enter the full 8-character pairing code.";
      return;
    }
    busy = true;
    try {
      const device = await claimDevice(normalized);
      toast.success("Device paired", device.alias);
      goto(base + "/devices/" + device.id);
    } catch (e) {
      error = e instanceof ApiError ? e.message : "Pairing failed. Please try again.";
    } finally {
      busy = false;
    }
  }

  const steps = [
    { icon: "car", title: "Open your device", text: "On the device screen, go to Settings → Device → Pair." },
    { icon: "qr", title: "Scan or read the code", text: "Scan the QR code with your phone to prefill it here, or read the 8-character code shown below the QR." },
    { icon: "shield-check", title: "Confirm", text: "Confirm the code below to securely claim the device." },
  ];
</script>

<svelte:head><title>Pair device · MyPilot</title></svelte:head>

<!-- ?all forces the device LIST; with exactly one existing device a bare /devices would redirect into
     that device, so backing out of pairing would never reach the list. -->
<a href={base + "/devices?all"} class="mb-4 inline-flex items-center gap-1.5 text-sm text-fg-muted hover:text-fg">
  <Icon name="arrow-left" size={16} /> Devices
</a>

<PageHeader eyebrow="Fleet" title="Pair a device" description="Link a comma device to this control plane." />

<div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
  <Card title="Pairing code" subtitle="Enter the code shown on your device" icon="add-device">
    <form on:submit|preventDefault={submit} class="space-y-4">
      <div>
        <label class="label" for="code">8-character code</label>
        <input
          id="code"
          class="input mono text-center text-lg tracking-[0.4em] uppercase {error ? 'input-invalid' : ''}"
          placeholder="XXXXXXXX"
          autocomplete="off"
          autocapitalize="characters"
          bind:value={code}
          maxlength="11" />
        <div class="mt-2 flex items-center justify-between">
          {#if error}<p class="error-text">{error}</p>{:else}<span></span>{/if}
          <span class="mono text-xs text-fg-subtle">{normalized.length}/8</span>
        </div>
      </div>
      <Button type="submit" variant="primary" class="w-full" loading={busy} disabled={normalized.length !== 8}>
        Pair device
      </Button>
      <p class="text-center text-xs text-fg-subtle">
        Pairing codes are single-use and expire about 10 minutes after they appear on the device.
      </p>
    </form>
  </Card>

  <Card title="How to pair" subtitle="Three quick steps" icon="info">
    <ol class="space-y-4">
      {#each steps as step, i}
        <li class="flex gap-3.5">
          <div class="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-surface-2 text-accent">
            <Icon name={step.icon} size={17} />
          </div>
          <div>
            <p class="text-sm font-medium text-fg">{i + 1}. {step.title}</p>
            <p class="mt-0.5 text-sm text-fg-muted">{step.text}</p>
          </div>
        </li>
      {/each}
    </ol>
  </Card>
</div>
