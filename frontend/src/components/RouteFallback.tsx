import { useAuth } from "../auth/AuthContext";
import Layout from "./Layout";
import PageLoading from "./PageLoading";

/**
 * Suspense fallback for lazy routes. For a signed-in user (same conditions
 * ProtectedRoute + the forced-password gate use to render pages) the app shell
 * stays visible and only the content area shows the loading status; otherwise
 * the plain indicator, so the authenticated nav never leaks to signed-out users.
 */
export default function RouteFallback() {
  const { loggedIn, authLoading, mustChangePassword } = useAuth();
  if (authLoading || !loggedIn || mustChangePassword) return <PageLoading />;
  return (
    <Layout>
      <PageLoading />
    </Layout>
  );
}
