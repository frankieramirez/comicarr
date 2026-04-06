import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NuqsAdapter } from "nuqs/adapters/react-router/v7";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import { ThemeProvider } from "@/contexts/ThemeContext";
import ProtectedRoute from "@/components/ProtectedRoute";
import Layout from "@/components/layout/Layout";
import { ToastProvider } from "@/components/ui/toast";
import ErrorBoundary from "@/components/ErrorBoundary";
import { useServerEvents } from "@/hooks/useServerEvents";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";

const LoginPage = lazy(() => import("@/pages/LoginPage"));
const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const SeriesListPage = lazy(() => import("@/pages/SeriesListPage"));
const SeriesDetailPage = lazy(() => import("@/pages/SeriesDetailPage"));
const SearchPage = lazy(() => import("@/pages/SearchPage"));
const UpcomingPage = lazy(() => import("@/pages/UpcomingPage"));
const WantedPage = lazy(() => import("@/pages/WantedPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));
const StoryArcsPage = lazy(() => import("@/pages/StoryArcsPage"));
const StoryArcDetailPage = lazy(() => import("@/pages/StoryArcDetailPage"));
const ImportPage = lazy(() => import("@/pages/ImportPage"));
const WeeklyPage = lazy(() => import("@/pages/WeeklyPage"));

// Create a client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

/**
 * AppContent component - handles SSE connection and keyboard shortcuts
 * Must be inside AuthProvider to access auth context
 */
function AppContent() {
  const { isAuthenticated } = useAuth();

  // Set up SSE connection when authenticated (JWT cookie-based)
  useServerEvents(isAuthenticated);

  // Set up global keyboard shortcuts
  useKeyboardShortcuts();

  return (
    <BrowserRouter>
      <NuqsAdapter>
        <Suspense fallback={null}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/*"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Suspense fallback={null}>
                      <Routes>
                        <Route path="/" element={<DashboardPage />} />
                        <Route path="/series" element={<SeriesListPage />} />
                        <Route
                          path="/series/:comicId"
                          element={<SeriesDetailPage />}
                        />
                        <Route path="/search" element={<SearchPage />} />
                        <Route path="/upcoming" element={<UpcomingPage />} />
                        <Route path="/wanted" element={<WantedPage />} />
                        <Route path="/story-arcs" element={<StoryArcsPage />} />
                        <Route
                          path="/story-arcs/:storyArcId"
                          element={<StoryArcDetailPage />}
                        />
                        <Route path="/weekly" element={<WeeklyPage />} />
                        <Route path="/import" element={<ImportPage />} />
                        <Route path="/settings" element={<SettingsPage />} />
                        <Route path="*" element={<Navigate to="/" replace />} />
                      </Routes>
                    </Suspense>
                  </Layout>
                </ProtectedRoute>
              }
            />
          </Routes>
        </Suspense>
      </NuqsAdapter>
    </BrowserRouter>
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
