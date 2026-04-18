import { Navigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import OnboardingDialog from "@/components/onboarding/OnboardingDialog";

interface ProtectedRouteProps {
  children: React.ReactNode;
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isAuthenticated, isLoading, needsMigration, dismissMigration } =
    useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background text-foreground">
        <div className="inline-flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
          <span
            className="inline-block h-3 w-3 animate-spin rounded-full border-[1.5px] border-solid border-current border-r-transparent"
            role="status"
            aria-label="Loading"
          />
          checking session…
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <>
      {children}
      <OnboardingDialog open={needsMigration} onFinish={dismissMigration} />
    </>
  );
}
