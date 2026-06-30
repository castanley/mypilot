import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";

// The workflow provides PORT for dev/serve. Tooling that merely loads this
// config (e.g. svelte-check) has no PORT, so fall back to a default there.
const rawPort = process.env.PORT;
const parsed = rawPort ? Number(rawPort) : NaN;
const port = !Number.isNaN(parsed) && parsed > 0 ? parsed : 5173;

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    port,
    strictPort: true,
    host: "0.0.0.0",
    allowedHosts: true,
  },
  preview: {
    port,
    strictPort: true,
    host: "0.0.0.0",
    allowedHosts: true,
  },
});
