import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  useParams,
  useLocation,
} from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NuqsAdapter } from "nuqs/adapters/react-router/v7";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import { ThemeProvider } from "@/contexts/ThemeContext";
import ProtectedRoute from "@/components/ProtectedRoute";
import Layout from "@/components/layout/Layout";
import FocusLayout from "@/components/layout/FocusLayout";
import { ToastProvider } from "@/components/ui/toast";
import ErrorBoundary from "@/components/ErrorBoundary";
import { RouteLoader } from "@/components/RouteLoader";
import { ServerEventsProvider } from "@/contexts/ServerEventsContext";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";

const LoginPage = () => (
  <RouteLoader load={() => import("@/pages/LoginPage")} />
);
const DashboardPage = () => (
  <RouteLoader load={() => import("@/pages/DashboardPage")} />
);
const SeriesListPage = () => (
  <RouteLoader load={() => import("@/pages/SeriesListPage")} />
);
const SeriesDetailPage = () => (
  <RouteLoader load={() => import("@/pages/SeriesDetailPage")} />
);
const IssueDetailPage = () => (
  <RouteLoader load={() => import("@/pages/IssueDetailPage")} />
);
const SearchPage = () => (
  <RouteLoader load={() => import("@/pages/SearchPage")} />
);
const ReleasesPage = () => (
  <RouteLoader load={() => import("@/pages/ReleasesPage")} />
);
const WantedPage = () => (
  <RouteLoader load={() => import("@/pages/WantedPage")} />
);
const SettingsPage = () => (
  <RouteLoader load={() => import("@/pages/SettingsPage")} />
);
const StoryArcsPage = () => (
  <RouteLoader load={() => import("@/pages/StoryArcsPage")} />
);
const StoryArcDetailPage = () => (
  <RouteLoader load={() => import("@/pages/StoryArcDetailPage")} />
);
const ImportPage = () => (
  <RouteLoader load={() => import("@/pages/ImportPage")} />
);
const ActivityPage = () => (
  <RouteLoader load={() => import("@/pages/ActivityPage")} />
);
const AttentionPage = () => (
  <RouteLoader load={() => import("@/pages/AttentionPage")} />
);
const ChatPage = () => <RouteLoader load={() => import("@/pages/ChatPage")} />;

function ChatWorkspace() {
  return (
    <ProtectedRoute>
      <FocusLayout>
        <ChatPage />
      </FocusLayout>
    </ProtectedRoute>
  );
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

/** Redirect old /series/:comicId URLs to /library/:comicId */
function SeriesRedirect() {
  const { comicId } = useParams();
  const location = useLocation();
  return (
    <Navigate
      to={{
        pathname: `/library/${comicId}`,
        search: location.search,
        hash: location.hash,
      }}
      replace
    />
  );
}

/** Redirect old /series URLs to /library */
function SeriesListRedirect() {
  const location = useLocation();
  return (
    <Navigate
      to={{
        pathname: "/library",
        search: location.search,
        hash: location.hash,
      }}
      replace
    />
  );
}

/**
 * AppContent component - handles SSE connection and keyboard shortcuts
 * Must be inside AuthProvider to access auth context
 */
function AppContent() {
  const { isAuthenticated } = useAuth();

  useKeyboardShortcuts();

  return (
    <ServerEventsProvider enabled={isAuthenticated}>
      <BrowserRouter>
        <NuqsAdapter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/chat" element={<ChatWorkspace />} />
            <Route path="/chat/:threadId" element={<ChatWorkspace />} />
            <Route
              path="/*"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Routes>
                      <Route path="/" element={<DashboardPage />} />
                      <Route path="/library" element={<SeriesListPage />} />
                      <Route
                        path="/library/:comicId/issue/:issueId"
                        element={<IssueDetailPage />}
                      />
                      <Route
                        path="/library/:comicId"
                        element={<SeriesDetailPage />}
                      />
                      <Route
                        path="/series/:comicId"
                        element={<SeriesRedirect />}
                      />
                      <Route path="/series" element={<SeriesListRedirect />} />
                      <Route path="/search" element={<SearchPage />} />
                      <Route path="/releases" element={<ReleasesPage />} />
                      <Route
                        path="/upcoming"
                        element={<Navigate to="/releases?view=mine" replace />}
                      />
                      <Route
                        path="/weekly"
                        element={<Navigate to="/releases?view=all" replace />}
                      />
                      <Route path="/wanted" element={<WantedPage />} />
                      <Route path="/story-arcs" element={<StoryArcsPage />} />
                      <Route
                        path="/story-arcs/:storyArcId"
                        element={<StoryArcDetailPage />}
                      />
                      <Route path="/activity" element={<ActivityPage />} />
                      <Route
                        path="/activity/attention"
                        element={<AttentionPage />}
                      />
                      <Route path="/import" element={<ImportPage />} />
                      <Route path="/settings" element={<SettingsPage />} />
                      <Route path="*" element={<Navigate to="/" replace />} />
                    </Routes>
                  </Layout>
                </ProtectedRoute>
              }
            />
          </Routes>
        </NuqsAdapter>
      </BrowserRouter>
    </ServerEventsProvider>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <ToastProvider>
            <AuthProvider>
              <AppContent />
            </AuthProvider>
          </ToastProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
