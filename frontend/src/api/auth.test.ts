import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import {
  fetchMe, listPublicExemptionTypes, fetchOidcStatus, fetchOidcRegistrationContext,
  fetchRegisterNodes, startSsoLogin, OIDC_START_PATH,
} from "./auth";

vi.mock("./client");

const baseMe = {
  id: "s-1",
  personal_number: "123",
  full_name: "Yossi",
  role: "soldier" as const,
  is_commander: false,
  is_duty_manager: false,
  must_change_password: false,
  hierarchy_node_id: null,
  telegram_linked: false,
  telegram_required: false,
  enrollment_pending: false,
  theme_preference: "system" as const,
};

describe("fetchMe", () => {
  it("normalizes a malformed active_deputy_grants field to an empty array", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { ...baseMe, active_deputy_grants: { not: "an array" } } });

    const me = await fetchMe();

    expect(me.active_deputy_grants).toEqual([]);
  });

  it("passes through a well-formed active_deputy_grants field", async () => {
    const grants = [{ principal_id: "p-1", principal_name: "Cmdr", role: "commander" as const, end_date: "2026-01-01" }];
    vi.mocked(api.get).mockResolvedValue({ data: { ...baseMe, active_deputy_grants: grants } });

    const me = await fetchMe();

    expect(me.active_deputy_grants).toEqual(grants);
  });
});

describe("listPublicExemptionTypes", () => {
  it("normalizes a malformed (non-array) response to an empty array", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { not: "an array" } });

    const types = await listPublicExemptionTypes();

    expect(types).toEqual([]);
  });

  it("passes through a well-formed response", async () => {
    const types = [{ id: "et-1", name: "Medical", description: null, is_medical: true }];
    vi.mocked(api.get).mockResolvedValue({ data: types });

    const result = await listPublicExemptionTypes();

    expect(result).toEqual(types);
  });
});

describe("OIDC helpers", () => {
  it("fetchOidcStatus returns enabled only when the server says exactly true", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { enabled: true } });
    expect(await fetchOidcStatus()).toBe(true);
    expect(api.get).toHaveBeenCalledWith("/auth/oidc/status");
    vi.mocked(api.get).mockResolvedValue({ data: { enabled: "yes" } });
    expect(await fetchOidcStatus()).toBe(false);
    vi.mocked(api.get).mockResolvedValue({ data: null });
    expect(await fetchOidcStatus()).toBe(false);
  });

  it("fetchOidcStatus treats a request failure as disabled", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("boom"));
    expect(await fetchOidcStatus()).toBe(false);
  });

  it("fetchOidcRegistrationContext returns email and ad_username", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { email: "a@b.co", ad_username: "a" } });
    expect(await fetchOidcRegistrationContext()).toEqual({ email: "a@b.co", ad_username: "a" });
    expect(api.get).toHaveBeenCalledWith("/auth/oidc/registration-context");
  });

  it("fetchOidcRegistrationContext rejects a malformed body", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { email: 5 } });
    await expect(fetchOidcRegistrationContext()).rejects.toThrow();
  });

  it("fetchRegisterNodes omits invite_code when none is given", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    await fetchRegisterNodes();
    expect(api.get).toHaveBeenLastCalledWith("/auth/register/nodes");
    await fetchRegisterNodes("a b");
    expect(api.get).toHaveBeenLastCalledWith("/auth/register/nodes?invite_code=a%20b");
  });

  it("startSsoLogin does a top-level navigation and never calls the API client", () => {
    const assign = vi.fn();
    vi.stubGlobal("window", { location: { assign } });
    try {
      vi.mocked(api.get).mockClear();
      startSsoLogin();
      expect(assign).toHaveBeenCalledWith(OIDC_START_PATH);
      expect(OIDC_START_PATH).toMatch(/\/auth\/oidc\/start$/);
      expect(api.get).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
