<script lang="ts">
  import Badge from "$lib/components/Badge.svelte";
  import Button from "$lib/components/Button.svelte";
  import Card from "$lib/components/Card.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import { ICONS } from "$lib/components/Icon.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import Segmented from "$lib/components/Segmented.svelte";
  import Select from "$lib/components/Select.svelte";
  import Slider from "$lib/components/Slider.svelte";
  import StatusBadge from "$lib/components/StatusBadge.svelte";
  import Stepper from "$lib/components/Stepper.svelte";
  import Toggle from "$lib/components/Toggle.svelte";
  import { confirmAction } from "$lib/stores/confirm";
  import { toast } from "$lib/stores/toast";

  let toggleA = true;
  let toggleB = false;
  let seg = "standard";
  let sel = "dark";
  let slide = 65;
  let stp = 1.8;

  const swatches = [
    { name: "bg", var: "--bg" },
    { name: "surface", var: "--surface" },
    { name: "surface-2", var: "--surface-2" },
    { name: "line", var: "--line" },
    { name: "fg", var: "--fg" },
    { name: "fg-muted", var: "--fg-muted" },
    { name: "accent", var: "--accent" },
    { name: "success", var: "--success" },
    { name: "warning", var: "--warning" },
    { name: "danger", var: "--danger" },
    { name: "info", var: "--info" },
  ];

  async function demoConfirm() {
    const ok = await confirmAction({
      title: "Confirm dangerous action",
      message: "This is what a type-to-confirm modal looks like for safety-critical actions.",
      danger: true,
      confirmLabel: "Do it",
      typeToConfirm: "CONFIRM",
    });
    if (ok) toast.success("Confirmed");
    else toast.info("Cancelled");
  }

  const iconNames = Object.keys(ICONS);
</script>

<svelte:head><title>Style guide · MyPilot</title></svelte:head>

<PageHeader
  eyebrow="System"
  title="Style guide"
  description="The MyPilot design system — tokens, components, and interaction patterns." />

<div class="space-y-6">
  <Card title="Color tokens" subtitle="Semantic palette (theme-aware)" icon="palette">
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
      {#each swatches as s}
        <div class="overflow-hidden rounded-lg border border-line">
          <div class="h-14" style="background: rgb(var({s.var}))"></div>
          <div class="px-2.5 py-1.5"><p class="mono text-xs text-fg">{s.name}</p></div>
        </div>
      {/each}
    </div>
  </Card>

  <Card title="Typography" subtitle="Inter + JetBrains Mono" icon="sparkles">
    <div class="space-y-2.5">
      <p class="text-3xl font-semibold tracking-tight text-fg">Display — Fleet command</p>
      <p class="text-xl font-semibold text-fg">Heading — Device telemetry</p>
      <p class="text-base text-fg">Body — Configure every device with confidence.</p>
      <p class="text-sm text-fg-muted">Muted — supporting copy and descriptions.</p>
      <p class="mono text-sm text-fg">mono — 1d3f7a9c2b4e6810</p>
    </div>
  </Card>

  <Card title="Buttons" subtitle="Variants and sizes" icon="sparkles">
    <div class="flex flex-wrap items-center gap-3">
      <Button variant="primary" icon="check">Primary</Button>
      <Button variant="secondary" icon="refresh-cw">Secondary</Button>
      <Button variant="ghost" icon="settings">Ghost</Button>
      <Button variant="danger" icon="trash">Danger</Button>
      <Button variant="danger-soft" icon="power">Danger soft</Button>
      <Button variant="primary" loading>Loading</Button>
      <Button variant="secondary" disabled>Disabled</Button>
      <Button variant="secondary" iconOnly icon="pencil" ariaLabel="Edit" />
    </div>
    <div class="mt-4 flex flex-wrap items-center gap-3">
      <Button variant="secondary" size="sm">Small</Button>
      <Button variant="secondary" size="md">Medium</Button>
      <Button variant="secondary" size="lg">Large</Button>
    </div>
  </Card>

  <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
    <Card title="Badges & status" icon="shield-check">
      <div class="flex flex-wrap gap-2">
        <Badge tone="neutral">Neutral</Badge>
        <Badge tone="accent">Accent</Badge>
        <Badge tone="success">Success</Badge>
        <Badge tone="warning">Warning</Badge>
        <Badge tone="danger">Danger</Badge>
        <Badge tone="info">Info</Badge>
      </div>
      <div class="divider my-4"></div>
      <div class="space-y-2">
        <StatusBadge online={true} onroad={true} />
        <StatusBadge online={true} onroad={false} />
        <StatusBadge online={false} />
      </div>
    </Card>

    <Card title="Form controls" icon="settings">
      <div class="space-y-4">
        <div class="flex items-center justify-between"><span class="text-sm text-fg">Toggle (on)</span><Toggle bind:checked={toggleA} /></div>
        <div class="flex items-center justify-between"><span class="text-sm text-fg">Toggle (off)</span><Toggle bind:checked={toggleB} /></div>
        <div class="flex items-center justify-between gap-4"><span class="text-sm text-fg">Segmented</span>
          <Segmented bind:value={seg} options={[{ value: "eco", label: "Eco" }, { value: "standard", label: "Standard" }, { value: "sport", label: "Sport" }]} />
        </div>
        <div class="flex items-center justify-between gap-4"><span class="text-sm text-fg">Select</span>
          <div class="w-40"><Select bind:value={sel} options={[{ value: "stock", label: "Stock" }, { value: "dark", label: "Dark" }, { value: "vivid", label: "Vivid" }]} /></div>
        </div>
        <div><span class="mb-2 block text-sm text-fg">Slider</span><Slider bind:value={slide} min={10} max={100} step={5} unit="%" /></div>
        <div class="flex items-center justify-between gap-4"><span class="text-sm text-fg">Stepper</span>
          <Stepper bind:value={stp} min={1} max={2.7} step={0.1} unit="s" />
        </div>
        <div><span class="mb-1.5 block text-sm text-fg">Text input</span><input class="input" placeholder="Type something…" /></div>
      </div>
    </Card>
  </div>

  <Card title="Feedback" subtitle="Toasts & confirmation" icon="info">
    <div class="flex flex-wrap gap-3">
      <Button variant="secondary" on:click={() => toast.success("Saved", "Your changes were applied.")}>Success toast</Button>
      <Button variant="secondary" on:click={() => toast.error("Failed", "Something went wrong.")}>Error toast</Button>
      <Button variant="secondary" on:click={() => toast.warning("Heads up", "Device is on the road.")}>Warning toast</Button>
      <Button variant="secondary" on:click={() => toast.info("FYI", "An update is available.")}>Info toast</Button>
      <Button variant="danger-soft" on:click={demoConfirm}>Confirm modal</Button>
    </div>
  </Card>

  <Card title="Icons" subtitle={`${iconNames.length} inline SVG icons`} icon="sparkles">
    <div class="grid grid-cols-4 gap-2 sm:grid-cols-8 lg:grid-cols-12">
      {#each iconNames as name}
        <div class="flex flex-col items-center gap-1.5 rounded-lg border border-line bg-surface-2 p-2.5 text-fg-muted" title={name}>
          <Icon {name} size={18} />
          <span class="mono w-full truncate text-center text-[0.625rem] text-fg-subtle">{name}</span>
        </div>
      {/each}
    </div>
  </Card>
</div>
