import { svelte } from "@sveltejs/vite-plugin-svelte";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Unit-test config kept SEPARATE from vite.config.ts so we don't pull the full SvelteKit pipeline
// (routing/SSR) into unit tests. We resolve the `$lib` alias and stub the SvelteKit virtual modules
// the store imports ($app/environment) so pure store/util logic is testable in plain Node/jsdom.
export default defineConfig({
  plugins: [svelte({ hot: false })],
  resolve: {
    alias: {
      $lib: fileURLToPath(new URL("./src/lib", import.meta.url)),
      // In the test (Node) env, `browser` is false — which means the store's `if (browser)` block
      // (WebSocket subscription + resync side-effects) does NOT run, so we exercise the pure reducer
      // and selectors in isolation. Exactly the seam we want to test.
      "$app/environment": fileURLToPath(new URL("./src/test/stubs/app-environment.ts", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.{test,spec}.{js,ts}"],
    globals: true,
  },
});
