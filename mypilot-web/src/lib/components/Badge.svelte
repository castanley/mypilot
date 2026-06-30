<script lang="ts">
  import { cx } from "$lib/utils";
  export let tone: "neutral" | "accent" | "success" | "warning" | "danger" | "info" = "neutral";
  let className = "";
  export { className as class };
  const tones: Record<string, string> = {
    neutral: "badge-neutral",
    accent: "badge-accent",
    success: "badge-success",
    warning: "badge-warning",
    danger: "badge-danger",
    info: "badge-info",
  };
</script>

<span class={cx("badge", tones[tone], className)}><slot /></span>
