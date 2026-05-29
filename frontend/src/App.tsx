import { Navigate, Route, Routes } from "react-router-dom";
import type { ReactElement } from "react";

import { AuthProvider, useAuth } from "./auth/AuthContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import DutyConfigPage from "./pages/DutyConfigPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import ProfilePage from "./pages/ProfilePage";
import TeamHierarchyPage from "./pages/TeamHierarchyPage";

function ForcedPasswordGate({ children }: { children: ReactElement }) {
  const { mustChangePassword } = useAuth();
  if (mustChangePassword) return <Navigate to="/change-password" replace />;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/change-password" element={<ChangePasswordPage />} />
          <Route path="/" element={<ForcedPasswordGate><HomePage /></ForcedPasswordGate>} />
          <Route path="/team" element={<ForcedPasswordGate><TeamHierarchyPage /></ForcedPasswordGate>} />
          <Route path="/duty-config" element={<ForcedPasswordGate><DutyConfigPage /></ForcedPasswordGate>} />
          <Route path="/profile" element={<ForcedPasswordGate><ProfilePage /></ForcedPasswordGate>} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}
