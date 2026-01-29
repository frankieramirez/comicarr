import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/contexts/AuthContext';
import ProtectedRoute from '@/components/ProtectedRoute';
import Layout from '@/components/layout/Layout';
import LoginPage from '@/pages/LoginPage';
import HomePage from '@/pages/HomePage';
import SeriesDetailPage from '@/pages/SeriesDetailPage';
import SearchPage from '@/pages/SearchPage';
import { ToastProvider } from '@/components/ui/toast';

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

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>
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
                      <Route path="/series/:comicId" element={<SeriesDetailPage />} />
                      <Route path="/search" element={<SearchPage />} />
                      <Route path="/upcoming" element={<div>Upcoming page coming soon...</div>} />
                      <Route path="/wanted" element={<div>Wanted page coming soon...</div>} />
                      <Route path="/story-arcs" element={<div>Story Arcs page coming soon...</div>} />
                      <Route path="/settings" element={<div>Settings page coming soon...</div>} />
                      <Route path="*" element={<Navigate to="/" replace />} />
                    </Routes>
                  </Layout>
                </ProtectedRoute>
              }
            />
          </Routes>
        </BrowserRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default App;
