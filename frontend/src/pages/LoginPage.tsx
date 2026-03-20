import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, Loader2, AlertCircle, User, Lock, ShieldCheck, ArrowRight } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { setupCredentials } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function SetupForm() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");

    if (!username.trim() || !password.trim()) {
      setError("Please enter both username and password");
      return;
    }

    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setIsSubmitting(true);
    try {
      const result = await setupCredentials(username, password);
      if (result.success) {
        // Server is restarting to enable auth sessions.
        // Poll until it's back, then redirect to login.
        setError("");
        const pollUntilReady = async () => {
          for (let i = 0; i < 30; i++) {
            await new Promise((r) => setTimeout(r, 2000));
            try {
              const resp = await fetch("/auth/check_setup");
              if (resp.ok) {
                window.location.href = "/";
                return;
              }
            } catch {
              // Server still restarting
            }
          }
          // Fallback after 60s
          window.location.href = "/";
        };
        pollUntilReady();
      } else {
        setError(result.error || "Setup failed");
        setIsSubmitting(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Setup failed");
      setIsSubmitting(false);
    }
  };

  return (
    <div>
      <div className="flex items-center gap-2 mb-4 text-sm text-muted-foreground">
        <ShieldCheck className="w-4 h-4" />
        <span>Create your admin account to get started</span>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="space-y-2">
          <label
            htmlFor="setup-username"
            className="text-sm font-medium text-foreground"
          >
            Username
          </label>
          <div className="relative">
            <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              id="setup-username"
              type="text"
              placeholder="Choose a username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={isSubmitting}
              autoComplete="username"
              className="pl-10"
            />
          </div>
        </div>

        <div className="space-y-2">
          <label
            htmlFor="setup-password"
            className="text-sm font-medium text-foreground"
          >
            Password
          </label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              id="setup-password"
              type="password"
              placeholder="Choose a password (min 8 characters)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isSubmitting}
              autoComplete="new-password"
              className="pl-10"
            />
          </div>
        </div>

        <div className="space-y-2">
          <label
            htmlFor="setup-confirm-password"
            className="text-sm font-medium text-foreground"
          >
            Confirm Password
          </label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              id="setup-confirm-password"
              type="password"
              placeholder="Confirm your password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              disabled={isSubmitting}
              autoComplete="new-password"
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
          disabled={isSubmitting}
        >
          {isSubmitting && !error ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              {username ? "Restarting server..." : "Creating account..."}
            </>
          ) : (
            "Create Account"
          )}
        </Button>
      </form>
    </div>
  );
}

function LoginForm() {
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
    <div>
      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="space-y-2">
          <label
            htmlFor="username"
            className="text-[13px] font-medium text-[var(--muted-foreground)]"
          >
            Username
          </label>
          <div className="relative">
            <User className="absolute left-4 top-1/2 -translate-y-1/2 w-[18px] h-[18px] text-[var(--text-muted,#6B6B70)]" />
            <Input
              id="username"
              type="text"
              placeholder="Enter your username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={isVerifying}
              autoComplete="username"
              className="pl-11 h-12 bg-[var(--surface-elevated,var(--secondary))] border-[var(--border-elevated,var(--border))] rounded-lg"
            />
          </div>
        </div>

        <div className="space-y-2">
          <label
            htmlFor="password"
            className="text-[13px] font-medium text-[var(--muted-foreground)]"
          >
            Password
          </label>
          <div className="relative">
            <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-[18px] h-[18px] text-[var(--text-muted,#6B6B70)]" />
            <Input
              id="password"
              type="password"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isVerifying}
              autoComplete="current-password"
              className="pl-11 h-12 bg-[var(--surface-elevated,var(--secondary))] border-[var(--border-elevated,var(--border))] rounded-lg"
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
          className="w-full h-12 text-[15px] font-semibold bg-gradient-to-r from-[#FF5C00] to-[#FF8A4C] hover:from-[#FF6A1A] hover:to-[#FF9560] text-white border-0 rounded-lg gap-2"
          disabled={isVerifying}
        >
          {isVerifying ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Signing in...
            </>
          ) : (
            <>
              Sign in
              <ArrowRight className="w-[18px] h-[18px]" />
            </>
          )}
        </Button>
      </form>
    </div>
  );
}

export default function LoginPage() {
  const { needsSetup } = useAuth();

  return (
    <div className="min-h-screen flex items-center justify-center bg-background relative overflow-hidden px-4">
      {/* Background radial glow */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse 80% 60% at 50% 40%, rgba(255,92,0,0.03), transparent)",
        }}
      />

      {/* Single card containing everything */}
      <div className="w-full max-w-[420px] relative z-10 bg-[#141417] rounded-2xl border border-[#1F1F23] shadow-[0_4px_40px_rgba(255,92,0,0.03)] px-10 py-12 flex flex-col items-center gap-8">
        {/* Brand section */}
        <div className="flex flex-col items-center gap-3">
          <div className="flex items-center justify-center w-[72px] h-[72px] rounded-2xl bg-gradient-to-b from-[#FF5C00] to-[#FF8A4C] shadow-lg shadow-[#FF5C00]/20">
            <BookOpen className="w-9 h-9 text-white" />
          </div>
          <h1 className="text-[32px] font-semibold tracking-[4px] text-white" style={{ fontFamily: "var(--font-mono, 'DM Mono', monospace)" }}>
            COMICARR
          </h1>
          <p className="text-[#8B8B90] text-sm">
            {needsSetup
              ? "Welcome! Set up your account to get started."
              : "Your comic book library manager"}
          </p>
        </div>

        {/* Form section */}
        <div className="w-full">
          {needsSetup ? <SetupForm /> : <LoginForm />}
        </div>

        {/* Footer */}
        <p className="text-center text-xs text-[#4A4A4E]">
          Automated comic book management
        </p>
      </div>
    </div>
  );
}
