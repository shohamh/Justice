import { Navigate, Outlet, useLocation } from "react-router-dom";

import PageLoading from "../components/PageLoading";
import { useAuth } from "./AuthContext";

export default function ProtectedRoute() {
  const { loggedIn, authLoading } = useAuth();
  const location = useLocation();
  // Keep the loading status on screen while the session is restored instead of
  // blanking the page: it replaces index.html's identical boot placeholder.
  if (authLoading) return <PageLoading />;
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
