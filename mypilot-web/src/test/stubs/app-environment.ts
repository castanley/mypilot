// Stub for SvelteKit's $app/environment in unit tests. `browser=false` keeps the devices store's
// `if (browser)` side-effects (WebSocket subscribe, resync) from running, so tests exercise the pure
// reducer + selectors. Mirrors the values SvelteKit provides during SSR/Node.
export const browser = false;
export const dev = false;
export const building = false;
export const version = "test";
