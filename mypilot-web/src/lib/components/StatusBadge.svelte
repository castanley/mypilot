<script lang="ts">
  import { cx } from "$lib/utils";
  import Icon from "./Icon.svelte";

  // Connectivity + driving state, legible without relying on color alone:
  // each state carries an icon and a text label.
  export let online: boolean;
  export let onroad = false;
  export let size: "sm" | "md" = "md";

  $: connKind = online ? "success" : "neutral";
  $: connLabel = online ? "Online" : "Offline";
  $: connIcon = online ? "wifi" : "wifi-off";
</script>

<span class="inline-flex items-center gap-1.5">
  <span class={cx("badge", connKind === "success" ? "badge-success" : "badge-neutral", size === "sm" && "px-2 py-0")}>
    <Icon name={connIcon} size={size === "sm" ? 12 : 13} />
    {connLabel}
  </span>
  {#if onroad}
    <span class={cx("badge badge-warning", size === "sm" && "px-2 py-0")}>
      <Icon name="car" size={size === "sm" ? 12 : 13} />
      On road
    </span>
  {:else if online}
    <span class={cx("badge badge-neutral", size === "sm" && "px-2 py-0")}>
      <Icon name="lock-open" size={size === "sm" ? 12 : 13} />
      Parked
    </span>
  {/if}
</span>
