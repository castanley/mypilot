<script lang="ts">
  import "../app.css";
  import ConfirmModal from "$lib/components/ConfirmModal.svelte";
  import ToastContainer from "$lib/components/ToastContainer.svelte";
</script>

<!--
  Root layout is a pass-through: it only carries truly global UI (styles, confirm modal, toasts).
  The dashboard shell (sidebar + topbar) lives in (app)/+layout.svelte; bare pages — the landing
  page, /login, /setup, /terms, and the /docs wiki (its own layout) — render with no shell. There
  is no per-route {#if} here, so navigating between bare and shell routes can't flash the chrome.
-->
<slot />

<ConfirmModal />
<ToastContainer />
