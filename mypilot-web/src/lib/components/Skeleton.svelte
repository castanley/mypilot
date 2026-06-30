<script lang="ts">
  import { cx } from "$lib/utils";
  export let width = "100%";
  export let height = "1rem";
  export let rounded = "0.375rem";
  let className = "";
  export { className as class };
</script>

<div
  class={cx("skeleton", className)}
  style="width: {width}; height: {height}; border-radius: {rounded};"
  aria-hidden="true"></div>
