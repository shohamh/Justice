import { describe, it, expect } from "vitest";
import he from "./he.json";

// Mirrors backend/app/db/models.py NotificationType enum values verbatim —
// the 27 members confirmed by reading the full enum body, PLUS
// "swap_pending_approval", added by the swap-requests-fixes plan's Task 3,
// which this plan's Global Constraints require to run BEFORE this task.
// If a new notification type is added to the backend enum in the future,
// add it here too — this test exists specifically to catch the class of bug
// where a new enum value ships with no matching translation key.
const NOTIFICATION_TYPES = [
  "swap_offer", "swap_accepted", "swap_rejected",
  "exemption_approved", "exemption_rejected",
  "constraint_approved", "constraint_rejected",
  "assignment_created", "assignment_removed",
  "score_adjusted", "announcement",
  "algorithm_job_done", "algorithm_job_failed",
  "enrollment_request_received", "enrollment_approved", "enrollment_rejected",
  "constraint_pending", "exemption_request_pending", "swap_offer_incoming",
  "gimelim_dismissed", "gimelim_reserve_called_up", "gimelim_demoted_to_reserve", "gimelim_reassigned",
  "exemption_revoked",
  "transfer_request_pending", "transfer_request_rejected",
  "system_announcement", "enrollment_fields_edited",
  "swap_pending_approval", "no_show_marked", "range_assignment_confirmed", "range_roster_changed", "range_cancelled", "range_no_show", "range_excusal_pending", "range_excusal_approved", "range_excusal_rejected", "range_reserve_promoted", "range_reserve_excused", "range_excusal_no_backfill", "range_reminder", "range_reminder_shortfall",
  "bug_report_comment", "weapon_ineligible_detected", "range_covers_duty_info",
  "range_absence_reported_to_commander", "range_attendance_corrected_to_present",
  "rank_advanced", "rank_advancement_soon", "mitvahim_expiring_soon", "mitvahim_expired", "alal_expiring_soon", "alal_expired",
  "personal_constraint_overridden",
];

describe("he.json notification type coverage", () => {
  it("has a type_<value> translation for every backend NotificationType", () => {
    const missing = NOTIFICATION_TYPES.filter((v) => !(`type_${v}` in he.notifications));
    expect(missing).toEqual([]);
  });
});

describe("he.json admin promotion coverage", () => {
  it("translates an incorrect acting-admin password", () => {
    expect(he.errors).toHaveProperty("wrong_current_password", "הסיסמה הנוכחית שגויה.");
  });
});

describe("he.json cancellation reconciliation coverage", () => {
  it("translates the cancelled-constraints section heading", () => {
    expect(he.my_requests).toHaveProperty("cancelled_constraints", "אילוצים שבוטלו");
  });

  it("translates the active-exemption revocation warning", () => {
    expect(he.exemptions).toHaveProperty(
      "revoke_active_warning",
      "זוהי פעולה קיצונית השמורה למקרים מיוחדים. יש לנמק את הביטול.",
    );
  });

  it("translates the cancel-constraint action and its active-constraint warning", () => {
    expect(he.team).toHaveProperty("cancel_constraint", "ביטול אילוץ אישי");
    expect(he.team).toHaveProperty(
      "cancel_constraint_active_warning",
      "זוהי פעולה קיצונית השמורה למקרים מיוחדים. יש לנמק את הביטול.",
    );
  });
});
