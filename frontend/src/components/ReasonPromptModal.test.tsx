// frontend/src/components/ReasonPromptModal.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import ReasonPromptModal from "./ReasonPromptModal";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

describe("ReasonPromptModal", () => {
  it("renders the description as plain text by default", () => {
    render(<ReasonPromptModal title="t" description="a plain reason prompt" onConfirm={vi.fn()} onClose={vi.fn()} />);
    const desc = screen.getByText("a plain reason prompt");
    expect(desc.className).not.toContain("amber");
  });

  it("renders the description with warning styling when variant is warning", () => {
    render(<ReasonPromptModal title="t" description="an extreme action" variant="warning" onConfirm={vi.fn()} onClose={vi.fn()} />);
    const desc = screen.getByText((content, element) => {
      return element?.tagName.toLowerCase() === "p" && content.includes("an extreme action");
    });
    expect(desc.className).toContain("amber");
  });
});
