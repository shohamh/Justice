import { Navigate, Route, Routes } from "react-router-dom";
import type { ReactElement } from "react";

import { AuthProvider, useAuth } from "./auth/AuthContext";
import { SoldierModalProvider } from "./contexts/SoldierModalContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import ApprovalsPage from "./pages/ApprovalsPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import MyDutiesPage from "./pages/MyDutiesPage";
import MyRequestsPage from "./pages/MyRequestsPage";
import NotificationsPage from "./pages/NotificationsPage";
import ProfilePage from "./pages/ProfilePage";
import TeamHierarchyPage from "./pages/TeamHierarchyPage";
import SwapsPage from "./pages/SwapsPage";
import TransparencyPage from "./pages/TransparencyPage";
import UnitCalendarPage from "./pages/UnitCalendarPage";
import CommandDashboardPage from "./pages/CommandDashboardPage";
import RegisterPage from "./pages/RegisterPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import VerifyEmailPage from "./pages/VerifyEmailPage";
import TelegramSetupPage from "./pages/TelegramSetupPage";
import ShiftsManagementPage from "./pages/planning/ShiftsManagementPage";
import ConfigPage from "./pages/planning/ConfigPage";
import ScoreAdjustmentPage from "./pages/planning/ScoreAdjustmentPage";
import ExportPage from "./pages/planning/ExportPage";
import PotentialPage from "./pages/planning/PotentialPage";
import AdminSettingsPage from "./pages/admin/AdminSettingsPage";
import HakpazaPage from "./pages/HakpazaPage";
import ImportSessionsListPage from "./pages/ImportSessionsListPage";
import ImportUploadPage from "./pages/ImportUploadPage";
import ImportSessionReviewPage from "./pages/ImportSessionReviewPage";
import ActionPage from "./pages/ActionPage";

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
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/verify-email" element={<VerifyEmailPage />} />
          <Route path="/action" element={<ActionPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/change-password" element={<ChangePasswordPage />} />
            <Route path="/setup/telegram" element={<TelegramSetupPage />} />
            <Route path="/" element={<AppGate><HomePage /></AppGate>} />
            <Route path="/team" element={<AppGate><TeamHierarchyPage /></AppGate>} />
            <Route path="/transparency" element={<AppGate><TransparencyPage /></AppGate>} />
            <Route path="/my-duties" element={<AppGate><MyDutiesPage /></AppGate>} />
            <Route path="/my-requests" element={<AppGate><MyRequestsPage /></AppGate>} />
            <Route path="/approvals" element={<AppGate><ApprovalsPage /></AppGate>} />
            <Route path="/unit-calendar" element={<AppGate><UnitCalendarPage /></AppGate>} />
            <Route path="/swaps" element={<AppGate><SwapsPage /></AppGate>} />
            <Route path="/profile" element={<AppGate><ProfilePage /></AppGate>} />
            <Route path="/command-dashboard" element={<AppGate><CommandDashboardPage /></AppGate>} />
            <Route path="/notifications" element={<AppGate><NotificationsPage /></AppGate>} />
            {/* Planning pages */}
            <Route path="/planning/shifts" element={<AppGate><ShiftsManagementPage /></AppGate>} />
            <Route path="/planning/assignment" element={<Navigate to="/planning/shifts" replace />} />
            <Route path="/planning/config" element={<AppGate><ConfigPage /></AppGate>} />
            <Route path="/planning/score-adjustments" element={<AppGate><ScoreAdjustmentPage /></AppGate>} />
            <Route path="/planning/export" element={<AppGate><ExportPage /></AppGate>} />
            <Route path="/planning/potential" element={<AppGate><PotentialPage /></AppGate>} />
            {/* Admin */}
            <Route path="/admin/settings" element={<AppGate><AdminSettingsPage /></AppGate>} />
            <Route path="/commander/hakpaza" element={<AppGate><HakpazaPage /></AppGate>} />
            <Route path="/import" element={<AppGate><ImportSessionsListPage /></AppGate>} />
            <Route path="/import/upload" element={<AppGate><ImportUploadPage /></AppGate>} />
            <Route path="/import/sessions/:id" element={<AppGate><ImportSessionReviewPage /></AppGate>} />
            {/* Redirects from old routes */}
            <Route path="/duty-management" element={<Navigate to="/planning/shifts" replace />} />
            <Route path="/algorithm" element={<Navigate to="/planning/shifts" replace />} />
            <Route path="/duty-config" element={<Navigate to="/planning/config" replace />} />
            <Route path="/shifts" element={<Navigate to="/planning/shifts" replace />} />
            <Route path="/shift-templates" element={<Navigate to="/planning/shifts" replace />} />
            <Route path="/planning/templates" element={<Navigate to="/planning/shifts" replace />} />
            <Route path="/admin/system-settings" element={<Navigate to="/admin/settings?tab=0" replace />} />
            <Route path="/admin/invite-codes" element={<Navigate to="/admin/settings?tab=1" replace />} />
          </Route>
        </Routes>
      </SoldierModalProvider>
    </AuthProvider>
  );
}
