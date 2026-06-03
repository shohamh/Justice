import { Navigate, Route, Routes } from "react-router-dom";
import type { ReactElement } from "react";

import { AuthProvider, useAuth } from "./auth/AuthContext";
import { SoldierModalProvider } from "./contexts/SoldierModalContext";
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
import CommandDashboardPage from "./pages/CommandDashboardPage";
import AlgorithmPage from "./pages/AlgorithmPage";
import RegisterPage from "./pages/RegisterPage";
import TelegramSetupPage from "./pages/TelegramSetupPage";
import AdminInviteCodesPage from "./pages/AdminInviteCodesPage";

function ForcedPasswordGate({ children }: { children: ReactElement }) {
  const { mustChangePassword } = useAuth();
  if (mustChangePassword) return <Navigate to="/change-password" replace />;
  return children;
}

function TelegramGate({ children }: { children: ReactElement }) {
  const { telegramRequired, telegramLinked } = useAuth();
  if (telegramRequired && !telegramLinked) return <Navigate to="/setup/telegram" replace />;
  return children;
}

function AppGate({ children }: { children: ReactElement }) {
  return <ForcedPasswordGate><TelegramGate>{children}</TelegramGate></ForcedPasswordGate>;
}

export default function App() {
  return (
    <AuthProvider>
      <SoldierModalProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/change-password" element={<ChangePasswordPage />} />
            <Route path="/setup/telegram" element={<TelegramSetupPage />} />
            <Route path="/" element={<AppGate><HomePage /></AppGate>} />
            <Route path="/team" element={<AppGate><TeamHierarchyPage /></AppGate>} />
            <Route path="/duty-config" element={<AppGate><DutyConfigPage /></AppGate>} />
            <Route path="/duty-management" element={<AppGate><DutyManagementPage /></AppGate>} />
            <Route path="/transparency" element={<AppGate><TransparencyPage /></AppGate>} />
            <Route path="/my-duties" element={<AppGate><MyDutiesPage /></AppGate>} />
            <Route path="/my-requests" element={<AppGate><MyRequestsPage /></AppGate>} />
            <Route path="/approvals" element={<AppGate><ApprovalsPage /></AppGate>} />
            <Route path="/unit-calendar" element={<AppGate><UnitCalendarPage /></AppGate>} />
            <Route path="/shifts" element={<AppGate><ShiftsPage /></AppGate>} />
            <Route path="/shift-templates" element={<AppGate><ShiftTemplatesPage /></AppGate>} />
            <Route path="/swaps" element={<AppGate><SwapsPage /></AppGate>} />
            <Route path="/profile" element={<AppGate><ProfilePage /></AppGate>} />
            <Route path="/command-dashboard" element={<AppGate><CommandDashboardPage /></AppGate>} />
            <Route path="/notifications" element={<AppGate><NotificationsPage /></AppGate>} />
            <Route path="/algorithm" element={<AppGate><AlgorithmPage /></AppGate>} />
            <Route path="/admin/invite-codes" element={<AppGate><AdminInviteCodesPage /></AppGate>} />
          </Route>
        </Routes>
      </SoldierModalProvider>
    </AuthProvider>
  );
}
