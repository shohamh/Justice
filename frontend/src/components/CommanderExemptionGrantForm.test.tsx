import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import CommanderExemptionGrantForm from "./CommanderExemptionGrantForm";
import { grantCommanderExemption, escalateCommanderExemption } from "../api/exemptions";

vi.mock("../api/exemptions", () => ({
  grantCommanderExemption: vi.fn(() => Promise.resolve()),
  escalateCommanderExemption: vi.fn(() => Promise.resolve({})),
}));

const commanderTypes = [{ id: "c1", name: "פטור פיקודי כללי" }];
const officialTypes = [{ id: "o1", name: "פטור רפואי" }];

test("grant is blocked until the confirmation checkbox is ticked", () => {
  render(
    <CommanderExemptionGrantForm
      soldierId="s1"
      commanderExemptionTypes={commanderTypes}
      officialExemptionTypes={officialTypes}
      onGranted={() => {}}
      canApplyImmediately={true}
    />
  );
  fireEvent.change(screen.getByTestId("commander-exemption-reason"), { target: { value: "סיבה" } });
  fireEvent.click(screen.getByTestId("commander-exemption-submit"));

  const modalConfirm = screen.getByTestId("commander-exemption-confirm");
  expect(modalConfirm).toBeDisabled();
  fireEvent.click(screen.getByTestId("commander-exemption-ack-checkbox"));
  expect(modalConfirm).not.toBeDisabled();
});

test("plain grant calls grantCommanderExemption when escalate is off", async () => {
  render(
    <CommanderExemptionGrantForm
      soldierId="s1"
      commanderExemptionTypes={commanderTypes}
      officialExemptionTypes={officialTypes}
      onGranted={() => {}}
      canApplyImmediately={true}
    />
  );
  fireEvent.change(screen.getByTestId("commander-exemption-reason"), { target: { value: "סיבה" } });
  fireEvent.click(screen.getByTestId("commander-exemption-submit"));
  fireEvent.click(screen.getByTestId("commander-exemption-ack-checkbox"));
  fireEvent.click(screen.getByTestId("commander-exemption-confirm"));

  await waitFor(() => expect(grantCommanderExemption).toHaveBeenCalledWith("s1", expect.objectContaining({ reason: "סיבה" })));
  expect(escalateCommanderExemption).not.toHaveBeenCalled();
});

test("escalate on with apply-immediately calls escalateCommanderExemption with apply_immediately true", async () => {
  render(
    <CommanderExemptionGrantForm
      soldierId="s1"
      commanderExemptionTypes={commanderTypes}
      officialExemptionTypes={officialTypes}
      onGranted={() => {}}
      canApplyImmediately={true}
    />
  );
  fireEvent.change(screen.getByTestId("commander-exemption-reason"), { target: { value: "סיבה" } });
  fireEvent.click(screen.getByTestId("commander-exemption-escalate-checkbox"));
  fireEvent.click(screen.getByTestId("commander-exemption-apply-immediately-checkbox"));
  fireEvent.click(screen.getByTestId("commander-exemption-submit"));
  fireEvent.click(screen.getByTestId("commander-exemption-ack-checkbox"));
  fireEvent.click(screen.getByTestId("commander-exemption-confirm"));

  await waitFor(() =>
    expect(escalateCommanderExemption).toHaveBeenCalledWith(
      "s1",
      expect.objectContaining({ apply_immediately: true, official_exemption_type_id: "o1", commander_exemption_type_id: "c1" })
    )
  );
});

test("escalate on without apply-immediately defaults apply_immediately to false", async () => {
  render(
    <CommanderExemptionGrantForm
      soldierId="s1"
      commanderExemptionTypes={commanderTypes}
      officialExemptionTypes={officialTypes}
      onGranted={() => {}}
      canApplyImmediately={true}
    />
  );
  fireEvent.change(screen.getByTestId("commander-exemption-reason"), { target: { value: "סיבה" } });
  fireEvent.click(screen.getByTestId("commander-exemption-escalate-checkbox"));
  fireEvent.click(screen.getByTestId("commander-exemption-submit"));
  fireEvent.click(screen.getByTestId("commander-exemption-ack-checkbox"));
  fireEvent.click(screen.getByTestId("commander-exemption-confirm"));

  await waitFor(() =>
    expect(escalateCommanderExemption).toHaveBeenCalledWith(
      "s1",
      expect.objectContaining({ apply_immediately: false, commander_exemption_type_id: undefined })
    )
  );
});

test("date inputs render and accept Israeli dd/mm/yyyy format", () => {
  render(
    <CommanderExemptionGrantForm
      soldierId="s1"
      commanderExemptionTypes={commanderTypes}
      officialExemptionTypes={officialTypes}
      onGranted={() => {}}
      canApplyImmediately={true}
    />
  );
  const startDateInput = screen.getByTestId("commander-exemption-start");
  const endDateInput = screen.getByTestId("commander-exemption-end");

  fireEvent.change(startDateInput, { target: { value: "05/03/2026" } });
  fireEvent.change(endDateInput, { target: { value: "10/03/2026" } });

  expect(startDateInput).toHaveValue("05/03/2026");
  expect(endDateInput).toHaveValue("10/03/2026");
});

it("hides the non-escalate submit path and apply-immediately checkbox when canApplyImmediately is false", () => {
  render(<CommanderExemptionGrantForm soldierId="s1" commanderExemptionTypes={[{ id: "c1", name: "פ1" }]} officialExemptionTypes={[{ id: "o1", name: "פ2" }]} onGranted={vi.fn()} canApplyImmediately={false} />);
  expect(screen.queryByTestId("commander-exemption-apply-immediately-checkbox")).not.toBeInTheDocument();
});

it("shows the apply-immediately checkbox when canApplyImmediately is true", () => {
  render(<CommanderExemptionGrantForm soldierId="s1" commanderExemptionTypes={[{ id: "c1", name: "פ1" }]} officialExemptionTypes={[{ id: "o1", name: "פ2" }]} onGranted={vi.fn()} canApplyImmediately={true} />);
  fireEvent.click(screen.getByTestId("commander-exemption-escalate-checkbox"));
  expect(screen.getByTestId("commander-exemption-apply-immediately-checkbox")).toBeInTheDocument();
});
