import { useAuth } from "../auth/AuthContext";
import { usePublicSettings } from "../hooks/usePublicSettings";
import Layout from "./Layout";
import PageLoading from "./PageLoading";

/**
 * Suspense fallback for lazy routes. For a signed-in user (same conditions
 * ProtectedRoute + the forced-password gate use to render pages) the app shell
 * stays visible and only the content area shows the loading status; otherwise
 * the plain indicator, so the authenticated nav never leaks to signed-out users.
 * A user whom TelegramGate (App.tsx) is about to redirect to the shell-less
 * /setup/telegram page also gets the plain indicator, so the nav (and its
 * count queries) doesn't flash first; the condition mirrors TelegramGate.
 */
export default function RouteFallback() {
  const { loggedIn, authLoading, mustChangePassword, telegramRequired, telegramLinked } = useAuth();
  const settings = usePublicSettings();
  const telegramEnabled = settings?.["telegram.enabled"] === true;
  if (authLoading || !loggedIn || mustChangePassword) return <PageLoading />;
  if (telegramEnabled && telegramRequired && !telegramLinked) return <PageLoading />;
  return (
    <Layout>
      <PageLoading />
    </Layout>
  );
}
