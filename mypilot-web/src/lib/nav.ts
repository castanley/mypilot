export interface NavItem {
  label: string;
  href: string;
  icon: string;
  comingSoon?: boolean;
  adminOnly?: boolean; // hidden from non-admins (the route + API also enforce admin)
  group: "main" | "fleet" | "system";
}

// Path-prefix aware: the base path is applied at render time via $app/paths.
export const navItems: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: "dashboard", group: "main" },
  { label: "Devices", href: "/devices", icon: "devices", group: "fleet" },
  { label: "Pair device", href: "/devices/pair", icon: "add-device", group: "fleet" },
  { label: "Routes", href: "/routes", icon: "routes", group: "fleet" },
  { label: "Drives", href: "/drives", icon: "video", group: "fleet" },
  { label: "Map", href: "/map", icon: "map", group: "fleet" },
  { label: "Models", href: "/models", icon: "models", group: "fleet" },
  { label: "Settings", href: "/settings", icon: "settings", group: "system" },
  { label: "Software", href: "/software", icon: "software", group: "system" },
  { label: "Backups", href: "/backups", icon: "backups", group: "system" },
  { label: "Logs", href: "/logs", icon: "logs", group: "system" },
  { label: "Security", href: "/security", icon: "security", comingSoon: true, group: "system" },
  { label: "Developer", href: "/developer", icon: "developer", adminOnly: true, group: "system" },
];

export const navGroups: { id: NavItem["group"]; label: string }[] = [
  { id: "main", label: "Overview" },
  { id: "fleet", label: "Fleet" },
  { id: "system", label: "System" },
];

export const comingSoonMeta: Record<
  string,
  { icon: string; title: string; description: string; bullets: string[] }
> = {
  routes: {
    icon: "routes",
    title: "Routes & drives",
    description: "Review every drive your devices have recorded, with maps and telemetry.",
    bullets: [
      "Interactive map of each recorded route",
      "Per-drive disengagement and intervention markers",
      "Filter by device, date range, and duration",
    ],
  },
  models: {
    icon: "models",
    title: "Driving models",
    description: "Manage the neural network models running on your fleet.",
    bullets: [
      "Browse available driving models and changelogs",
      "Assign models per device with staged rollout",
      "Pin a known-good model and roll back instantly",
    ],
  },
  settings: {
    icon: "settings",
    title: "Account settings",
    description: "Account and notification preferences.",
    bullets: [
      "Profile, password, and two-factor authentication",
      "Notification routing for fleet alerts",
      "API tokens for programmatic access",
    ],
  },
  software: {
    icon: "software",
    title: "Software updates",
    description: "Coordinate firmware and openpilot updates across your fleet.",
    bullets: [
      "See available versions per branch",
      "Schedule updates for offroad windows",
      "Track install progress and rollback history",
    ],
  },
  backups: {
    icon: "backups",
    title: "Backups",
    description: "Snapshot and restore device configuration and tuning.",
    bullets: [
      "Automatic nightly configuration snapshots",
      "Restore a device to any previous snapshot",
      "Export backups to object storage",
    ],
  },
  logs: {
    icon: "logs",
    title: "System logs",
    description: "Stream structured logs from devices and the control plane.",
    bullets: [
      "Live tail with severity filtering",
      "Search across devices and components",
      "Download log bundles for support",
    ],
  },
  security: {
    icon: "security",
    title: "Security",
    description: "Access control, sessions, and the full audit trail.",
    bullets: [
      "Review active sessions and revoke access",
      "Complete, immutable audit log",
      "Configure SSH and remote-access policy",
    ],
  },
  developer: {
    icon: "developer",
    title: "Developer",
    description: "Tools for building on top of the MyPilot API.",
    bullets: [
      "Interactive API explorer",
      "Webhook subscriptions for fleet events",
      "Realtime WebSocket inspector",
    ],
  },
};
