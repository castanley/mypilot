<script lang="ts">
  import {
    ApiError,
    changePassword,
    deleteAllRoutes,
    runRetention,
    setRetention,
    updateAdminConfig,
  } from "$lib/api";
  import Button from "$lib/components/Button.svelte";
  import Card from "$lib/components/Card.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import { confirmAction } from "$lib/stores/confirm";
  import { toast } from "$lib/stores/toast";
  import type { ForkConfig, RetentionConfig } from "$lib/types";

  export let data: { config: ForkConfig | null; retention: RetentionConfig | null };

  // Editable copy of the deployment/fork config.
  let cfg: ForkConfig | null = data.config ? { ...data.config } : null;
  let savingCfg = false;

  // Live preview of the install URLs as you edit (matches the server's derivation).
  $: previewRelease = cfg
    ? `${cfg.installer_base.replace(/\/$/, "")}/${cfg.github_owner}/${cfg.release_branch}`
    : "";
  $: previewStaging = cfg
    ? `${cfg.installer_base.replace(/\/$/, "")}/${cfg.github_owner}/${cfg.staging_branch}`
    : "";
  $: shorthandRelease = cfg ? `${cfg.github_owner}/${cfg.release_branch}` : "";

  async function saveConfig() {
    if (!cfg) return;
    savingCfg = true;
    try {
      const updated = await updateAdminConfig({
        project_name: cfg.project_name,
        source_url: cfg.source_url,
        stack_url: cfg.stack_url,
        installer_base: cfg.installer_base,
        github_owner: cfg.github_owner,
        release_branch: cfg.release_branch,
        staging_branch: cfg.staging_branch,
      });
      cfg = { ...updated };
      toast.success("Settings saved", "Install URLs across the panel now use these values.");
    } catch (e) {
      toast.error("Save failed", e instanceof ApiError ? e.message : undefined);
    } finally {
      savingCfg = false;
    }
  }

  // --- change password ---
  let curPw = "";
  let newPw = "";
  let newPw2 = "";
  let pwBusy = false;
  $: pwValid = curPw.length > 0 && newPw.length >= 8 && newPw === newPw2;
  async function savePassword() {
    if (!pwValid) return;
    pwBusy = true;
    try {
      await changePassword(curPw, newPw);
      curPw = newPw = newPw2 = "";
      toast.success("Password changed", "Other sessions were signed out.");
    } catch (e) {
      toast.error("Couldn't change password", e instanceof ApiError ? e.message : undefined);
    } finally {
      pwBusy = false;
    }
  }

  // --- privacy: retention + delete-all ---
  // route_days/log_days fall back to the legacy single `days` for an older config; 0 = keep forever.
  let routeDays = data.retention?.route_days ?? data.retention?.days ?? 0;
  let logDays = data.retention?.log_days ?? data.retention?.days ?? 0;
  let retentionBusy = false;
  let runBusy = false;
  let wipeBusy = false;

  async function saveRetention() {
    retentionBusy = true;
    try {
      const r = await setRetention({ route_days: Number(routeDays) || 0, log_days: Number(logDays) || 0 });
      routeDays = r.route_days ?? r.days ?? 0;
      logDays = r.log_days ?? r.days ?? 0;
      toast.success("Retention saved", "New uploads and the next cleanup use this policy.");
    } catch (e) {
      toast.error("Couldn't save retention", e instanceof ApiError ? e.message : undefined);
    } finally {
      retentionBusy = false;
    }
  }

  async function runRetentionNow() {
    const ok = await confirmAction({
      title: "Run cleanup now",
      message: "Delete all routes/logs older than the retention windows above? This cannot be undone.",
      confirmLabel: "Run cleanup",
      danger: true,
    });
    if (!ok) return;
    runBusy = true;
    try {
      const r = await runRetention();
      toast.success("Cleanup complete", `Deleted ${r.routes_deleted} route(s) and ${r.logs_deleted} log(s).`);
    } catch (e) {
      toast.error("Cleanup failed", e instanceof ApiError ? e.message : undefined);
    } finally {
      runBusy = false;
    }
  }

  async function wipeAllDrives() {
    const ok = await confirmAction({
      title: "Delete ALL drives",
      message:
        "Permanently delete every drive (route) and its stored video/log bytes across all your devices. This cannot be undone.",
      confirmLabel: "Delete everything",
      danger: true,
      typeToConfirm: "DELETE",
    });
    if (!ok) return;
    wipeBusy = true;
    try {
      const r = await deleteAllRoutes();
      toast.success("Drives deleted", `Removed ${r.routes_deleted} drive(s).`);
    } catch (e) {
      toast.error("Delete failed", e instanceof ApiError ? e.message : undefined);
    } finally {
      wipeBusy = false;
    }
  }
</script>

<svelte:head><title>Settings · MyPilot</title></svelte:head>

<PageHeader
  eyebrow="System"
  title="Settings"
  description="Deployment configuration for this self-hosted MyPilot. Forking? Change your Stack URL and install source here — nothing is hard-coded." />

{#if !cfg}
  <div class="card mb-6">
    <EmptyState icon="security" title="Admin only" description="Sign in as an admin to view and change deployment settings." />
  </div>
{:else}
  <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
    <Card title="Deployment & branding" subtitle="Your public site" icon="cloud">
      <div class="space-y-3">
        <div>
          <label class="label" for="proj">Project name</label>
          <input id="proj" class="input" bind:value={cfg.project_name} placeholder="MyPilot" />
          <p class="hint">Shown on the landing page and titles.</p>
        </div>
        <div>
          <label class="label" for="stack-url">Public Stack URL</label>
          <input id="stack-url" class="input" bind:value={cfg.stack_url} placeholder="https://mypilot.example" />
          <p class="hint">The URL devices pair to. Also set it in your fork's <span class="mono">fork.json</span> so builds default to it.</p>
        </div>
        <div>
          <label class="label" for="src">Source URL</label>
          <input id="src" class="input" bind:value={cfg.source_url} placeholder="https://github.com/you/mypilot" />
          <p class="hint">Link to your repo, shown on the public landing page (optional).</p>
        </div>
      </div>
    </Card>

    <Card title="Build / install source" subtitle="Where your device build is fetched from" icon="git-branch">
      <div class="space-y-3">
        <div>
          <label class="label" for="owner">GitHub owner</label>
          <input id="owner" class="input" bind:value={cfg.github_owner} placeholder="your-github-user" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="label" for="rel">Release branch</label>
            <input id="rel" class="input mono" bind:value={cfg.release_branch} />
          </div>
          <div>
            <label class="label" for="stg">Staging branch</label>
            <input id="stg" class="input mono" bind:value={cfg.staging_branch} />
          </div>
        </div>
        <div>
          <label class="label" for="base">Installer base</label>
          <input id="base" class="input mono" bind:value={cfg.installer_base} />
        </div>
      </div>
      <div class="mt-4 rounded-lg border border-line bg-surface-2 p-3 text-xs">
        <p class="text-fg-subtle">Resulting install URLs (what the comma's "Custom Software" uses):</p>
        <p class="mono mt-1 text-fg">release: {previewRelease}</p>
        <p class="mono text-fg">staging: {previewStaging}</p>
        <p class="mt-1 text-fg-subtle">Shorthand on the device: <span class="mono text-fg">{shorthandRelease}</span></p>
      </div>
    </Card>
  </div>

  <div class="mt-4 flex justify-end">
    <Button variant="primary" loading={savingCfg} on:click={saveConfig}>Save deployment settings</Button>
  </div>

  <div class="mt-6 max-w-xl">
    <Card title="Account" subtitle="Change your password" icon="lock">
      <div class="space-y-3">
        <div>
          <label class="label" for="cur">Current password</label>
          <input id="cur" type="password" class="input" bind:value={curPw} autocomplete="current-password" />
        </div>
        <div>
          <label class="label" for="np">New password</label>
          <input id="np" type="password" class="input" bind:value={newPw} autocomplete="new-password" />
          <p class="hint">At least 8 characters.</p>
        </div>
        <div>
          <label class="label" for="np2">Confirm new password</label>
          <input id="np2" type="password" class="input" bind:value={newPw2} autocomplete="new-password" />
          {#if newPw2 && newPw !== newPw2}<p class="error-text">Passwords don't match.</p>{/if}
        </div>
      </div>
      <div class="mt-4 flex justify-end">
        <Button variant="primary" loading={pwBusy} disabled={!pwValid} on:click={savePassword}>Change password</Button>
      </div>
    </Card>
  </div>

  <div class="mt-6 max-w-xl">
    <Card title="Privacy & data" subtitle="Retention and deletion" icon="security">
      <p class="mb-4 text-sm text-fg-muted">
        Drive upload is controlled on the device (off by default). Here you control how long captured
        data is kept on this stack, and you can wipe it.
      </p>

      <div class="space-y-3">
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="label" for="route-days">Keep routes (days)</label>
            <input id="route-days" type="number" min="0" max="3650" class="input" bind:value={routeDays} />
          </div>
          <div>
            <label class="label" for="log-days">Keep logs (days)</label>
            <input id="log-days" type="number" min="0" max="3650" class="input" bind:value={logDays} />
          </div>
        </div>
        <p class="hint">0 = keep forever. Cleanup runs on demand (below); new data is unaffected until then.</p>
      </div>
      <div class="mt-4 flex flex-wrap justify-end gap-2">
        <Button variant="secondary" loading={runBusy} on:click={runRetentionNow}>Run cleanup now</Button>
        <Button variant="primary" loading={retentionBusy} on:click={saveRetention}>Save retention</Button>
      </div>

      <div class="mt-5 rounded-lg border border-danger/40 bg-danger-soft p-3.5">
        <p class="text-sm font-medium text-fg">Delete all drives</p>
        <p class="mt-1 text-xs text-fg-muted">
          Permanently removes every drive and its stored bytes across all your devices. Cannot be undone.
        </p>
        <div class="mt-3 flex justify-end">
          <Button variant="danger" loading={wipeBusy} on:click={wipeAllDrives}>Delete all drives</Button>
        </div>
      </div>
    </Card>
  </div>
{/if}
