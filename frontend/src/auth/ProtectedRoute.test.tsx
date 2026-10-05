import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import ProtectedRoute from "./ProtectedRoute";

vi.mock("./AuthContext", () => ({
  useAuth: () => ({ loggedIn: false, authLoading: false }),
}));

function LoginLocation() {
  const location = useLocation();
  const from = location.state?.from;
  return (
    <output data-testid="login-location">
      {JSON.stringify({ pathname: location.pathname, from })}
    </output>
  );
}

test("preserves the protected internal path and query in login router state", () => {
  render(
    <MemoryRouter initialEntries={["/import/sessions/session-42?tab=summary#details"]}>
      <Routes>
        <Route path="/login" element={<LoginLocation />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/import/sessions/:id" element={<div>protected content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );

  expect(screen.getByTestId("login-location")).toHaveTextContent(
    JSON.stringify({
      pathname: "/login",
      from: {
        pathname: "/import/sessions/session-42",
        search: "?tab=summary",
        hash: "#details",
      },
    }),
  );
});
