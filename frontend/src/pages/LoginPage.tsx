import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, Loader2, AlertCircle, User, Lock } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const { login, isVerifying } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");

    if (!username.trim() || !password.trim()) {
      setError("Please enter both username and password");
      return;
    }

    const result = await login(username, password);

    if (result.success) {
      navigate("/");
    } else {
      setError(result.error || "Login failed");
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background relative overflow-hidden px-4">
      {/* Background decoration */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div
          className="absolute -top-1/2 -left-1/2 w-full h-full opacity-[0.03] dark:opacity-[0.02]"
          style={{
            background:
              "radial-gradient(circle at center, var(--primary) 0%, transparent 50%)",
          }}
        />
        <div
          className="absolute -bottom-1/2 -right-1/2 w-full h-full opacity-[0.03] dark:opacity-[0.02]"
          style={{
            background:
              "radial-gradient(circle at center, var(--primary) 0%, transparent 50%)",
          }}
        />
      </div>

      {/* Login card */}
      <div className="w-full max-w-sm relative z-10">
        {/* Logo section */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 border border-primary/20 mb-6 shadow-lg shadow-primary/10">
            <BookOpen className="w-10 h-10 text-primary" />
          </div>
          <h1 className="text-4xl font-bold mb-2">
            <span className="gradient-brand">Mylar</span>
          </h1>
          <p className="text-muted-foreground">
            Your comic book library manager
          </p>
        </div>

        {/* Form card */}
        <div className="bg-card border border-card-border rounded-xl p-6 shadow-xl shadow-black/5 dark:shadow-black/20">
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <label
                htmlFor="username"
                className="text-sm font-medium text-foreground"
              >
                Username
              </label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  id="username"
                  type="text"
                  placeholder="Enter your username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={isVerifying}
                  autoComplete="username"
                  className="pl-10"
                />
              </div>
            </div>

            <div className="space-y-2">
              <label
                htmlFor="password"
                className="text-sm font-medium text-foreground"
              >
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  id="password"
                  type="password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isVerifying}
                  autoComplete="current-password"
                  className="pl-10"
                />
              </div>
            </div>

            {error && (
              <div className="flex items-start gap-3 p-3 text-sm text-[var(--status-error)] bg-[var(--status-error-bg)] border border-[var(--status-error)]/20 rounded-lg">
                <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <Button
              type="submit"
              className="w-full h-11 text-base font-medium"
              disabled={isVerifying}
            >
              {isVerifying ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Signing in...
                </>
              ) : (
                "Sign in"
              )}
            </Button>
          </form>
        </div>

        {/* Footer */}
        <p className="text-center text-xs text-muted-foreground/60 mt-6">
          Automated comic book management
        </p>
      </div>
    </div>
  );
}
