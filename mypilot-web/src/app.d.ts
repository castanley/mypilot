import type { Me } from "$lib/types";

declare global {
  namespace App {
    interface Error {}
    interface Locals {
      user: Me | null;
      needsSetup: boolean;
    }
    interface PageData {
      user?: Me | null;
      needsSetup?: boolean;
      // The lone non-revoked device's id (set by the (app) layout load) when the account has exactly
      // one device, else null — lets the sidebar link "Devices" straight at it. Undefined off the (app) group.
      soleDeviceId?: string | null;
    }
    interface PageState {}
    interface Platform {}
  }
}

export {};
