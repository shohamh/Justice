import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "./AuthContext";

export default function ProtectedRoute() {
  const { loggedIn, authLoading } = useAuth();
  const location = useLocation();
  if (authLoading) return null;
  if (!loggedIn) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: { pathname: location.pathname, search: location.search, hash: location.hash } }}
      />
    );
  }
  return <Outlet />;
}
