<script lang="ts">
  import { cx } from "$lib/utils";
  import Icon from "./Icon.svelte";

  export let variant: "primary" | "secondary" | "ghost" | "danger" | "danger-soft" = "secondary";
  export let size: "sm" | "md" | "lg" = "md";
  export let icon: string | null = null;
  export let iconRight: string | null = null;
  export let iconOnly = false;
  export let loading = false;
  export let disabled = false;
  export let href: string | null = null;
  export let type: "button" | "submit" | "reset" = "button";
  export let title: string | null = null;
  export let ariaLabel: string | null = null;
  let className = "";
  export { className as class };

  const variants: Record<string, string> = {
    primary: "btn-primary",
    secondary: "btn-secondary",
    ghost: "btn-ghost",
    danger: "btn-danger",
    "danger-soft": "btn-danger-soft",
  };
  const sizes: Record<string, string> = { sm: "btn-sm", md: "btn-md", lg: "btn-lg" };

  $: sizeClass = iconOnly ? (size === "sm" ? "btn-icon-sm" : "btn-icon") : sizes[size];
  $: cls = cx("btn", variants[variant], sizeClass, className);
  $: iconSize = size === "sm" ? 15 : 17;
</script>

{#if href}
  <a {href} class={cls} title={title} aria-label={ariaLabel} aria-disabled={disabled} on:click>
    {#if loading}
      <Icon name="refresh-cw" size={iconSize} class="animate-spin" />
    {:else if icon}
      <Icon name={icon} size={iconSize} />
    {/if}
    {#if !iconOnly}<slot />{/if}
    {#if iconRight && !loading}<Icon name={iconRight} size={iconSize} />{/if}
  </a>
{:else}
  <button
    {type}
    class={cls}
    title={title}
    aria-label={ariaLabel}
    disabled={disabled || loading}
    on:click>
    {#if loading}
      <Icon name="refresh-cw" size={iconSize} class="animate-spin" />
    {:else if icon}
      <Icon name={icon} size={iconSize} />
    {/if}
    {#if !iconOnly}<slot />{/if}
    {#if iconRight && !loading}<Icon name={iconRight} size={iconSize} />{/if}
  </button>
{/if}
