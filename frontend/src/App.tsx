import { Navigate, Route, Routes } from "react-router-dom";
import type { ReactElement } from "react";

import { AuthProvider, useAuth } from "./auth/AuthContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import ApprovalsPage from "./pages/ApprovalsPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import DutyConfigPage from "./pages/DutyConfigPage";
import DutyManagementPage from "./pages/DutyManagementPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import MyDutiesPage from "./pages/MyDutiesPage";
import MyRequestsPage from "./pages/MyRequestsPage";
import NotificationsPage from "./pages/NotificationsPage";
import ProfilePage from "./pages/ProfilePage";
import TeamHierarchyPage from "./pages/TeamHierarchyPage";
import ShiftsPage from "./pages/ShiftsPage";
import ShiftTemplatesPage from "./pages/ShiftTemplatesPage";
import SwapsPage from "./pages/SwapsPage";
import TransparencyPage from "./pages/TransparencyPage";
import UnitCalendarPage from "./pages/UnitCalendarPage";

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
          <Route path="/duty-management" element={<ForcedPasswordGate><DutyManagementPage /></ForcedPasswordGate>} />
          <Route path="/transparency" element={<ForcedPasswordGate><TransparencyPage /></ForcedPasswordGate>} />
          <Route path="/my-duties" element={<ForcedPasswordGate><MyDutiesPage /></ForcedPasswordGate>} />
          <Route path="/my-requests" element={<ForcedPasswordGate><MyRequestsPage /></ForcedPasswordGate>} />
          <Route path="/approvals" element={<ForcedPasswordGate><ApprovalsPage /></ForcedPasswordGate>} />
          <Route path="/unit-calendar" element={<ForcedPasswordGate><UnitCalendarPage /></ForcedPasswordGate>} />
          <Route path="/shifts" element={<ForcedPasswordGate><ShiftsPage /></ForcedPasswordGate>} />
          <Route path="/shift-templates" element={<ForcedPasswordGate><ShiftTemplatesPage /></ForcedPasswordGate>} />
          <Route path="/swaps" element={<ForcedPasswordGate><SwapsPage /></ForcedPasswordGate>} />
          <Route path="/profile" element={<ForcedPasswordGate><ProfilePage /></ForcedPasswordGate>} />
          <Route path="/notifications" element={<ForcedPasswordGate><NotificationsPage /></ForcedPasswordGate>} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}
