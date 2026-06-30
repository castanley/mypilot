<script lang="ts">
  import { changeSetting, resetSetting, ApiError } from "$lib/api";
  import { confirmAction } from "$lib/stores/confirm";
  import { toast } from "$lib/stores/toast";
  import type { SettingOut } from "$lib/types";
  import { cx } from "$lib/utils";
  import { createEventDispatcher } from "svelte";
  import Icon from "./Icon.svelte";
  import Segmented from "./Segmented.svelte";
  import Select from "./Select.svelte";
  import Slider from "./Slider.svelte";
  import Stepper from "./Stepper.svelte";
  import Toggle from "./Toggle.svelte";
  import Tooltip from "./Tooltip.svelte";

  export let deviceId: string;
  export let setting: SettingOut;
  export let onroad: boolean;

  const dispatch = createEventDispatcher<{ changed: void }>();

  let busy = false; // a change request is in flight
  let result: "ok" | "err" | null = null;

  // `local` mirrors the device-reported value and reconciles whenever the parent refetches
  // (after the device confirms the change via the realtime setting_result event).
  $: local = setting.current_value;

  // Onroad locks settings that require the car to be parked.
  $: locked = onroad && setting.requires_offroad;
  // Gated: an arm-on-device-only setting that is currently off — the web may not arm it from here.
  $: gated = !!setting.gated;
  $: disabled = locked || gated || busy;

  const dangerMeta = {
    safe: null,
    caution: { cls: "badge-warning", label: "Caution", icon: "alert-triangle" },
    dangerous: { cls: "badge-danger", label: "Dangerous", icon: "alert-triangle" },
  } as const;

  const jsonEq = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

  async function apply(value: unknown) {
    if (jsonEq(value, setting.current_value)) return;

    // Gate is enforced authoritatively by the stack (403) + the device, but stop the request here
    // too so the UI doesn't optimistically show a change that will be rejected.
    if (gated) {
      local = setting.current_value;
      toast.error("Enable on the device", "This setting must be turned on at the device first.");
      return;
    }

    if (setting.danger_level === "dangerous") {
      const ok = await confirmAction({
        title: setting.label,
        message: `This is a safety-critical setting. ${setting.description} Are you sure you want to change it?`,
        confirmLabel: "Apply change",
        danger: true,
        typeToConfirm: "CONFIRM",
      });
      if (!ok) {
        local = setting.current_value;
        return;
      }
    }

    busy = true;
    result = null;
    local = value; // optimistic — reconciled to the device-confirmed value via refetch
    try {
      // 202 = accepted + dispatched to the device. The device applies it and the confirmed
      // value arrives via realtime; the parent then refetches to reflect the true state.
      await changeSetting(deviceId, setting.key, value, setting.danger_level === "dangerous");
      result = "ok";
      dispatch("changed");
    } catch (err) {
      local = setting.current_value; // revert the optimistic value
      result = "err";
      toast.error("Change failed", err instanceof ApiError ? err.message : "Could not apply");
    } finally {
      busy = false;
      setTimeout(() => (result = null), 2200);
    }
  }

  async function reset() {
    busy = true;
    result = null;
    try {
      await resetSetting(deviceId, setting.key);
      result = "ok";
      dispatch("changed");
    } catch (err) {
      result = "err";
      toast.error("Could not reset", err instanceof ApiError ? err.message : "");
    } finally {
      busy = false;
      setTimeout(() => (result = null), 2200);
    }
  }

  function onTextChange(e: Event) {
    apply((e.target as HTMLInputElement).value);
  }

  $: numUnit = setting.key.includes("brightness")
    ? "%"
    : setting.key.includes("follow_distance")
      ? "s"
      : "";
</script>

<div class="flex flex-col gap-3 py-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
  <div class="min-w-0 flex-1">
    <div class="flex flex-wrap items-center gap-2">
      <label for={"set-" + setting.key} class="text-sm font-medium text-fg">{setting.label}</label>
      {#if !setting.is_default}
        <span class="badge badge-accent">Modified</span>
      {/if}
      {#if dangerMeta[setting.danger_level]}
        <span class={cx("badge", dangerMeta[setting.danger_level]?.cls)}>
          <Icon name="alert-triangle" size={11} />
          {dangerMeta[setting.danger_level]?.label}
        </span>
      {/if}
    </div>
    <p class="mt-1 text-sm text-fg-muted">{setting.description}</p>
    <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-subtle">
      {#if setting.requires_offroad}
        <span class="inline-flex items-center gap-1"><Icon name="car" size={12} /> Requires parked</span>
      {/if}
      {#if setting.requires_reboot}
        <span class="inline-flex items-center gap-1"><Icon name="power" size={12} /> Requires reboot</span>
      {/if}
      {#if !setting.remote_configurable}
        <span class="inline-flex items-center gap-1"><Icon name="lock" size={12} /> Device-only</span>
      {/if}
      {#if locked}
        <span class="inline-flex items-center gap-1 font-medium text-warning">
          <Icon name="lock" size={12} /> Locked while driving
        </span>
      {/if}
      {#if gated}
        <span class="inline-flex items-center gap-1 font-medium text-warning">
          <Icon name="lock" size={12} /> Enable on the device to control here
        </span>
      {/if}
    </div>
  </div>

  <div class="flex shrink-0 items-center gap-2.5 sm:w-auto sm:justify-end">
    <!-- state indicator -->
    <div class="flex h-5 w-5 items-center justify-center">
      {#if busy}
        <Icon name="refresh-cw" size={15} class="animate-spin text-accent" />
      {:else if result === "ok"}
        <Icon name="check" size={16} class="text-success" />
      {:else if result === "err"}
        <Icon name="x" size={16} class="text-danger" />
      {/if}
    </div>

    {#if !setting.is_default && setting.type !== "boolean"}
      <Tooltip text="Reset to default">
        <button
          type="button"
          class="btn btn-ghost btn-icon-sm"
          aria-label="Reset to default"
          {disabled}
          on:click={reset}>
          <Icon name="refresh-cw" size={15} />
        </button>
      </Tooltip>
    {/if}

    {#if setting.type === "boolean"}
      <Toggle
        id={"set-" + setting.key}
        checked={!!local}
        {disabled}
        ariaLabel={setting.label}
        on:change={(e) => apply(e.detail)} />
    {:else if setting.type === "enum" && setting.options}
      {#if setting.options.length <= 3}
        <Segmented
          options={setting.options.map((o) => ({ value: o.value, label: o.label }))}
          value={local}
          {disabled}
          on:change={(e) => apply(e.detail)} />
      {:else}
        <div class="w-44">
          <Select
            id={"set-" + setting.key}
            options={setting.options.map((o) => ({ value: o.value, label: o.label }))}
            value={local}
            {disabled}
            on:change={(e) => apply(e.detail)} />
        </div>
      {/if}
    {:else if setting.type === "number"}
      {#if (setting.max_value ?? 0) - (setting.min_value ?? 0) > 12}
        <div class="w-48">
          <Slider
            value={Number(local)}
            min={setting.min_value ?? 0}
            max={setting.max_value ?? 100}
            step={setting.step ?? 1}
            unit={numUnit}
            {disabled}
            on:change={(e) => apply(e.detail)} />
        </div>
      {:else}
        <Stepper
          value={Number(local)}
          min={setting.min_value ?? 0}
          max={setting.max_value ?? 100}
          step={setting.step ?? 1}
          unit={numUnit}
          {disabled}
          on:change={(e) => apply(e.detail)} />
      {/if}
    {:else}
      <input
        id={"set-" + setting.key}
        class="input w-48"
        value={String(local ?? "")}
        {disabled}
        on:change={onTextChange} />
    {/if}
  </div>
</div>
