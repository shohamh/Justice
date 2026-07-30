import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { usePagePagination } from "./usePagePagination";

function wrapper({ children }: { children: React.ReactNode }) {
  return <MemoryRouter initialEntries={["/somepage"]}>{children}</MemoryRouter>;
}

describe("usePagePagination", () => {
  it("defaults to page 1, offset 0", () => {
    const { result } = renderHook(() => usePagePagination({ limit: 20 }), { wrapper });
    expect(result.current.page).toBe(1);
    expect(result.current.offset).toBe(0);
    expect(result.current.limit).toBe(20);
  });

  it("setPage updates page and offset together", () => {
    const { result } = renderHook(() => usePagePagination({ limit: 20 }), { wrapper });
    act(() => result.current.setPage(3));
    expect(result.current.page).toBe(3);
    expect(result.current.offset).toBe(40);
  });

  it("reads an initial page from the URL", () => {
    function wrapperWithPage({ children }: { children: React.ReactNode }) {
      return <MemoryRouter initialEntries={["/somepage?page=2"]}>{children}</MemoryRouter>;
    }
    const { result } = renderHook(() => usePagePagination({ limit: 20 }), { wrapper: wrapperWithPage });
    expect(result.current.page).toBe(2);
    expect(result.current.offset).toBe(20);
  });

  it("supports a custom param name so multiple paginated lists can coexist on one page", () => {
    function wrapperWithCustomParam({ children }: { children: React.ReactNode }) {
      return <MemoryRouter initialEntries={["/somepage?otherPage=4"]}>{children}</MemoryRouter>;
    }
    const { result } = renderHook(() => usePagePagination({ limit: 20, paramName: "otherPage" }), { wrapper: wrapperWithCustomParam });
    expect(result.current.page).toBe(4);
  });
});
