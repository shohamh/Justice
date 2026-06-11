import { Navigate, Outlet } from "react-router-dom";

import { useAuth } from "./AuthContext";

export default function ProtectedRoute() {
  const { loggedIn, authLoading } = useAuth();
  if (authLoading) return null;
  if (!loggedIn) return <Navigate to="/login" replace />;
  return <Outlet />;
}
