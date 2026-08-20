import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import DutyHistoryWidget from "./DutyHistoryWidget";

describe("DutyHistoryWidget", () => {
  it("shows the transparency-page link when the user can view transparency", () => {
    render(
      <MemoryRouter>
        <DutyHistoryWidget
          duties={[]}
          typeNames={{}}
          locationNames={{}}
          myRow={null}
          allRows={[]}
          canViewTransparency={true}
        />
      </MemoryRouter>
    );

    expect(screen.getByText("לדף השקיפות →")).toBeInTheDocument();
  });

  it("hides the transparency-page link when the user lacks permission", () => {
    render(
      <MemoryRouter>
        <DutyHistoryWidget
          duties={[]}
          typeNames={{}}
          locationNames={{}}
          myRow={null}
          allRows={[]}
          canViewTransparency={false}
        />
      </MemoryRouter>
    );

    expect(screen.queryByText("לדף השקיפות →")).not.toBeInTheDocument();
  });
});
