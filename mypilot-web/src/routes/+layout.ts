// SSR is enabled (default). The server hook + +layout.server.ts handle the auth guard;
// pages fetch their data client-side after hydration.
export const prerender = false;
export const trailingSlash = "ignore";
