import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import "../i18n";
import CoverOfferModal from "./CoverOfferModal";
import * as swapsApi from "../api/swaps";
import { SwapRequest } from "../api/swaps";

describe("CoverOfferModal", () => {
  it("shows a translated message for cover_blocked:overlap", async () => {
    vi.spyOn(swapsApi, "checkCoverEligibility").mockResolvedValue({
      eligible: true,
      reason: null,
    });
    vi.spyOn(swapsApi, "submitCoverOffer").mockRejectedValue({
      response: { data: { detail: "cover_blocked:overlap" } },
    });

    render(
      <CoverOfferModal
        swap={{ id: "1", duty_assignment_id: "a1" } as SwapRequest}
        myDuties={[]}
        dutyTypes={{}}
        onDone={() => {}}
        onClose={() => {}}
      />
    );

    await waitFor(() => expect(screen.getByText("שלח הצעה")).not.toBeDisabled());
    fireEvent.click(screen.getByText("שלח הצעה"));

    await waitFor(() =>
      expect(screen.getByText("קיימת חפיפה עם תורנות אחרת")).toBeInTheDocument()
    );
  });
});
