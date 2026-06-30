import adapter from "@sveltejs/adapter-node";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    // Served by a Node server (node build) on :3000 behind Caddy. The app is
    // client-rendered (ssr=false in src/routes/+layout.ts); Node serves the SPA shell.
    adapter: adapter(),
    alias: {
      $lib: "src/lib",
    },
  },
};

export default config;
