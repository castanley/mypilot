// Renders the repository's docs/*.md as the public wiki. The markdown in the repo is the
// single source of truth — the website renders those exact files, so there's nothing to keep
// in sync in two places. Files are baked into the web image (see mypilot-web/Dockerfile) and can
// be bind-mounted for live editing; MYPILOT_DOCS_DIR overrides the location.
//
// Server-only ($lib/server is never shipped to the browser): we touch the filesystem here.
import { env } from "$env/dynamic/private";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { marked } from "marked";

marked.setOptions({ gfm: true });

// ---------------------------------------------------------------------------------------------
// Where the markdown lives. In the container MYPILOT_DOCS_DIR=/app/docs; `vite dev` falls back
// to the repo's docs/ one level up from mypilot-web.
function resolveDocsDir(): string {
  const candidates = [
    env.MYPILOT_DOCS_DIR,
    resolve("docs"),
    resolve("..", "docs"),
    resolve("..", "..", "docs"),
  ].filter(Boolean) as string[];
  for (const dir of candidates) {
    try {
      if (statSync(dir).isDirectory()) return dir;
    } catch {
      /* try the next candidate */
    }
  }
  return candidates[candidates.length - 1] ?? resolve("docs");
}
const DOCS_DIR = resolveDocsDir();

// Slugs are filenames without the .md. Restrict to a safe charset so a slug can never escape
// DOCS_DIR via path traversal.
const SLUG_RE = /^[a-z0-9][a-z0-9-]*$/;

// Curated wiki: friendly titles, order, and grouping for the user-facing guides. Anything on
// disk that isn't listed here and isn't internal is auto-appended under "More guides", so a
// fork that adds a doc gets it in the index for free. Content always comes from the .md.
interface ManifestEntry {
  slug: string;
  title: string;
  group: string;
  description?: string;
}
const MANIFEST: ManifestEntry[] = [
  { slug: "self-hosting", title: "Self-hosting guide", group: "Getting started", description: "Deploy, configure, and pair — start here." },
  { slug: "install", title: "Install the stack", group: "Getting started", description: "Podman/Docker, LAN, Tailscale, and TLS." },
  { slug: "forking", title: "Forking & branding", group: "Getting started", description: "Make it yours: URLs, branches, the sync action." },
  { slug: "comma4-install", title: "Flash a comma 4", group: "Devices", description: "Install your branch via Custom Software." },
  { slug: "device-registration", title: "Registration & pairing", group: "Devices", description: "One-time, signed pairing — no SSH." },
  { slug: "update-channels", title: "Update channels", group: "Devices", description: "Release and staging branches." },
  { slug: "go-live", title: "Going to production", group: "Operations", description: "The end-to-end go-live checklist." },
  { slug: "security", title: "Security model", group: "Operations", description: "Auth, signing, secrets, and gating." },
  { slug: "privacy", title: "Privacy & data ownership", group: "Operations", description: "You own the data — here's how." },
  { slug: "architecture", title: "Architecture", group: "Reference", description: "How the stack fits together." },
  { slug: "development", title: "Local development", group: "Reference", description: "Run and hack on MyPilot locally." },
];
const GROUP_ORDER = ["Getting started", "Devices", "Operations", "Reference", "More guides"];
// Internal design notes / specs — reachable by direct link, but kept out of the index.
const INTERNAL = new Set([
  "mypilot-web-feature-spec",
  "mypilot-integration-plan",
  "sunnylink-feature-map",
  "sunnylink-settings-schema",
  "sunnypilot-code-notes",
  "sunnypilot-settings-catalog",
  "web-redesign-brief",
]);

export interface DocLink {
  slug: string;
  title: string;
  description?: string;
}
export interface DocGroup {
  label: string;
  items: DocLink[];
}
export interface DocHeading {
  id: string;
  text: string;
  depth: number;
}
export interface RenderedDoc {
  slug: string;
  title: string;
  html: string;
  toc: DocHeading[];
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/<[^>]+>/g, "")
    .replace(/&[a-z]+;/g, " ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function titleFromSlug(slug: string): string {
  return slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// First H1 in the file, with inline markdown punctuation stripped.
function firstHeading(md: string): string | null {
  const m = md.match(/^\s{0,3}#\s+(.+?)\s*$/m);
  return m ? m[1].replace(/[`*_]/g, "").trim() : null;
}

function stripInline(s: string): string {
  return s
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*?([^*]+)\*\*?/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .trim();
}

function availableSlugs(): string[] {
  try {
    return readdirSync(DOCS_DIR)
      .filter((f) => f.endsWith(".md"))
      .map((f) => f.slice(0, -3))
      .filter((s) => SLUG_RE.test(s));
  } catch {
    return [];
  }
}

function readDoc(slug: string): string | null {
  if (!SLUG_RE.test(slug)) return null;
  const file = resolve(DOCS_DIR, `${slug}.md`);
  if (!existsSync(file)) return null;
  try {
    return readFileSync(file, "utf8");
  } catch {
    return null;
  }
}

// Grouped listing for the /docs index.
export function listDocGroups(): DocGroup[] {
  const present = new Set(availableSlugs());
  const byGroup = new Map<string, DocLink[]>();
  const used = new Set<string>();

  for (const entry of MANIFEST) {
    if (!present.has(entry.slug)) continue;
    used.add(entry.slug);
    const items = byGroup.get(entry.group) ?? [];
    items.push({ slug: entry.slug, title: entry.title, description: entry.description });
    byGroup.set(entry.group, items);
  }

  for (const slug of availableSlugs()) {
    if (used.has(slug) || INTERNAL.has(slug)) continue;
    const md = readDoc(slug);
    const title = (md && firstHeading(md)) || titleFromSlug(slug);
    const items = byGroup.get("More guides") ?? [];
    items.push({ slug, title });
    byGroup.set("More guides", items);
  }

  return GROUP_ORDER.filter((g) => byGroup.has(g)).map((label) => ({
    label,
    items: byGroup.get(label)!,
  }));
}

// Rendered-doc cache, invalidated by file mtime so edits show up without a restart.
const cache = new Map<string, { mtimeMs: number; doc: RenderedDoc }>();

export function getDoc(slug: string): RenderedDoc | null {
  if (!SLUG_RE.test(slug)) return null;
  const file = resolve(DOCS_DIR, `${slug}.md`);
  let stat;
  try {
    stat = statSync(file);
  } catch {
    return null;
  }
  if (!stat.isFile()) return null;

  const hit = cache.get(slug);
  if (hit && hit.mtimeMs === stat.mtimeMs) return hit.doc;

  const doc = render(slug, readFileSync(file, "utf8"));
  cache.set(slug, { mtimeMs: stat.mtimeMs, doc });
  return doc;
}

function render(slug: string, raw: string): RenderedDoc {
  const title = firstHeading(raw) || titleFromSlug(slug);

  // Drop the leading H1 from the body — the page renders it as its own header.
  let body = raw;
  const h1 = raw.match(/^\s{0,3}#\s+.+?\s*$/m);
  if (h1 && h1.index !== undefined) {
    body = raw.slice(0, h1.index) + raw.slice(h1.index + h1[0].length);
  }

  // Headings in document order → stable, de-duplicated anchor ids. The same ordered list drives
  // both the id injection (below) and the table of contents.
  const seen = new Map<string, number>();
  const headings: DocHeading[] = (marked.lexer(body) as Array<{ type: string; depth: number; text: string }>)
    .filter((t) => t.type === "heading")
    .map((t) => {
      const base = slugify(t.text) || "section";
      const n = seen.get(base) ?? 0;
      seen.set(base, n + 1);
      return { id: n === 0 ? base : `${base}-${n}`, text: stripInline(t.text), depth: t.depth };
    });

  let html = marked.parse(body) as string;

  // Inject the ids into the rendered heading tags, in order (marked emits bare <hN> tags).
  let i = 0;
  html = html.replace(/<(h[1-6])>/g, (m, tag) => {
    const h = headings[i++];
    return h ? `<${tag} id="${h.id}">` : m;
  });

  // Rewrite links:
  //  - intra-repo "*.md" links → /docs/<slug>
  //  - repo-relative links ("../x") → the source repo on GitHub (so "see the recipe / workflow"
  //    pointers resolve on the wiki, not just when reading the markdown on GitHub)
  //  - external links open in a new tab
  const sourceRepo = (env.MYPILOT_SOURCE_URL || "").replace(/\/+$/, "");
  html = html.replace(/<a href="([^"]+)"/g, (m, href) => {
    if (/^https?:\/\//i.test(href)) return `<a href="${href}" target="_blank" rel="noreferrer noopener"`;
    const md = href.match(/^(?:\.\/)?([a-z0-9-]+)\.md(#[\w-]+)?$/i);
    if (md) return `<a href="/docs/${md[1].toLowerCase()}${md[2] ?? ""}"`;
    if (sourceRepo && href.startsWith("../")) {
      const path = href.replace(/^(?:\.\.\/)+/, "").replace(/^\/+/, "").replace(/#.*$/, "");
      const kind = href.endsWith("/") ? "tree" : "blob";
      return `<a href="${sourceRepo}/${kind}/main/${path}" target="_blank" rel="noreferrer noopener"`;
    }
    return m;
  });

  const toc = headings.filter((h) => h.depth >= 2 && h.depth <= 3);
  return { slug, title, html, toc };
}
