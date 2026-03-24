import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import { ThemeProvider } from "@/contexts/ThemeContext";
import ProtectedRoute from "@/components/ProtectedRoute";
import Layout from "@/components/layout/Layout";
import LoginPage from "@/pages/LoginPage";
import HomePage from "@/pages/HomePage";
import SeriesDetailPage from "@/pages/SeriesDetailPage";
import SearchPage from "@/pages/SearchPage";
import UpcomingPage from "@/pages/UpcomingPage";
import WantedPage from "@/pages/WantedPage";
import SettingsPage from "@/pages/SettingsPage";
import ImportPage from "@/pages/ImportPage";
import { ToastProvider } from "@/components/ui/toast";
import ErrorBoundary from "@/components/ErrorBoundary";
import { useServerEvents } from "@/hooks/useServerEvents";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";

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
  const { apiKey, sseKey } = useAuth();

  // Set up SSE connection when authenticated
  useServerEvents(sseKey, !!(apiKey && sseKey));

  // Set up global keyboard shortcuts
  useKeyboardShortcuts();

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <Layout>
                <Routes>
                  <Route path="/" element={<HomePage />} />
                  <Route
                    path="/series/:comicId"
                    element={<SeriesDetailPage />}
                  />
                  <Route path="/search" element={<SearchPage />} />
                  <Route path="/upcoming" element={<UpcomingPage />} />
                  <Route path="/wanted" element={<WantedPage />} />
                  <Route path="/import" element={<ImportPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </Layout>
            </ProtectedRoute>
          }
        />
      </Routes>
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
