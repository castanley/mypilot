<script lang="ts">
  import { confirmState, resolveConfirm } from "$lib/stores/confirm";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import Modal from "./Modal.svelte";

  let typed = "";
  $: state = $confirmState;
  $: if (state.open) {
    // reset the typed value when a new confirm opens
  }
  $: needsType = !!state.typeToConfirm;
  $: canConfirm = !needsType || typed === state.typeToConfirm;

  function done(ok: boolean) {
    resolveConfirm(ok);
    typed = "";
  }
</script>

<Modal open={state.open} title="" size="sm" on:close={() => done(false)}>
  <div class="flex flex-col items-center gap-4 pt-2 text-center">
    <div
      class="grid h-12 w-12 place-items-center rounded-xl border"
      class:border-danger={state.danger}
      class:bg-danger-soft={state.danger}
      class:text-danger={state.danger}
      class:border-line={!state.danger}
      class:bg-surface-2={!state.danger}
      class:text-accent={!state.danger}>
      <Icon name={state.danger ? "alert-triangle" : "info"} size={22} />
    </div>
    <div class="space-y-1.5">
      <h2 class="text-base font-semibold text-fg">{state.title}</h2>
      <p class="text-sm text-fg-muted">{state.message}</p>
    </div>
    {#if needsType}
      <div class="w-full text-left">
        <label class="hint mb-1.5 block" for="confirm-type">
          Type <span class="mono font-semibold text-fg">{state.typeToConfirm}</span> to confirm
        </label>
        <input
          id="confirm-type"
          class="input"
          bind:value={typed}
          autocomplete="off"
          placeholder={state.typeToConfirm} />
      </div>
    {/if}
  </div>
  <svelte:fragment slot="footer">
    <Button variant="ghost" on:click={() => done(false)}>
      {state.cancelLabel ?? "Cancel"}
    </Button>
    <Button
      variant={state.danger ? "danger" : "primary"}
      disabled={!canConfirm}
      on:click={() => done(true)}>
      {state.confirmLabel ?? "Confirm"}
    </Button>
  </svelte:fragment>
</Modal>
