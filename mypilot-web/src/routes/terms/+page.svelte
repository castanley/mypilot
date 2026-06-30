<script lang="ts">
  import { base } from "$app/paths";
  import Icon from "$lib/components/Icon.svelte";

  export let data: { site: { project_name: string } };

  $: name = data.site?.project_name || "MyPilot";

  // Bump when the substance of the terms changes; surfaced to the reader and mirrors the device's
  // terms_version gate.
  const effective = "2026-06-26";
</script>

<svelte:head>
  <title>Terms of Service — {name}</title>
  <meta
    name="description"
    content="Terms of Service for {name}, an open-source driver-assistance system built on openpilot." />
  <!-- openpilot is the upstream base; sunnypilot is one of several community forks built on it. -->
</svelte:head>

<div class="mx-auto max-w-3xl px-4 py-10 sm:px-6">
  <a href={base + "/"} class="inline-flex items-center gap-1.5 text-sm text-fg-muted transition hover:text-fg">
    <Icon name="arrow-left" size={15} /> Home
  </a>

  <article class="doc-prose mt-6">
    <h1 class="text-3xl font-semibold tracking-tight text-fg">Terms of Service</h1>
    <p class="mt-2 text-sm text-fg-muted">Effective {effective}</p>

    <div
      class="mt-6 flex items-start gap-3 rounded-lg border border-danger/50 bg-danger/10 p-4 text-sm leading-relaxed text-fg"
      role="alert">
      <span class="mt-0.5 shrink-0 text-danger"><Icon name="alert-triangle" size={20} /></span>
      <div>
        <strong class="text-danger">Safety first.</strong>
        {name} is a driver-assistance system, not a self-driving system. You must pay attention and be
        ready to take over at all times. You are always fully responsible for the safe operation of your
        vehicle.
      </div>
    </div>

    <h2>1. Acceptance</h2>
    <p>
      {name} is open-source software built on openpilot and other community forks such as sunnypilot.
      By installing, flashing, or using {name} on a device or in a vehicle, you agree to these Terms
      of Service. If you do not agree, do not install or use {name}.
    </p>

    <h2>2. Driver assistance only — you stay in control</h2>
    <ul>
      <li>{name} is a <strong>driver-assistance system</strong>. It does not make the vehicle autonomous.</li>
      <li>You must <strong>pay attention to the road at all times</strong> and keep your hands on the wheel.</li>
      <li>You must be <strong>ready to take over immediately</strong>, including steering, braking, and accelerating.</li>
      <li>You are <strong>fully responsible</strong> for the vehicle, for obeying all traffic laws, and for the consequences of operating it.</li>
      <li>Never use {name} in conditions, locations, or vehicles for which it is not suited.</li>
    </ul>

    <h2>3. Experimental software</h2>
    <p>
      {name} is experimental and may contain bugs, may behave unexpectedly, and may stop assisting
      without warning. Features may change, break, or be removed at any time. It is provided for
      research, development, and personal use.
    </p>

    <h2>4. Your responsibilities</h2>
    <ul>
      <li>Ensure that using {name} is legal where you drive and complies with your vehicle manufacturer's terms.</li>
      <li>Verify your hardware is installed and calibrated correctly before relying on any assistance.</li>
      <li>Maintain valid insurance and a valid driver's license, and drive within your abilities and the law.</li>
    </ul>

    <h2>5. No warranty</h2>
    <p>
      {name} is provided <strong>"as is" and "as available", without warranty of any kind</strong>,
      express or implied, including but not limited to merchantability, fitness for a particular
      purpose, and non-infringement. The authors and contributors do not warrant that {name} will be
      uninterrupted, error-free, or safe in any particular situation.
    </p>

    <h2>6. Limitation of liability</h2>
    <p>
      To the maximum extent permitted by law, the authors, contributors, and operators of {name} are
      <strong>not liable</strong> for any damages, injuries, losses, or claims arising out of or
      related to your use of (or inability to use) {name}, including direct, indirect, incidental,
      special, consequential, or punitive damages. You assume all risk of use.
    </p>

    <h2>7. Open-source licensing</h2>
    <p>
      {name} is distributed under the licenses of openpilot, the community forks it builds on (such
      as sunnypilot), and its own repositories. Your use is also subject to those licenses. {name} is
      an independent project and is not endorsed by or affiliated with comma.ai, openpilot, or
      sunnypilot.
    </p>

    <h2>8. Privacy</h2>
    <p>
      {name} is self-hosted: device data is reported to the {name} control plane you pair with, which
      you or your operator runs. See the project's privacy documentation for what is collected and how
      it is handled.
    </p>

    <h2>9. Changes to these terms</h2>
    <p>
      These terms may be updated over time. Material changes may require you to re-accept the terms on
      your device before continuing to use {name}.
    </p>

    <p class="mt-8 text-sm text-fg-muted">
      {name} is a personal, open-source project provided without any guarantee. This document is not
      legal advice.
    </p>
  </article>
</div>
