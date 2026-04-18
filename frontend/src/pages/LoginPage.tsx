import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Loader2,
  AlertCircle,
  User,
  Lock,
  ShieldCheck,
  ArrowRight,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { setupCredentials } from "@/lib/api";
import { Kbd } from "@/components/ui/kbd";
import GridShader from "@/components/login/GridShader";
import Logo from "@/components/Logo";

function MonoLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-mono text-[10px] tracking-[0.08em] uppercase text-muted-foreground mb-1.5">
      {children}
    </div>
  );
}

function FieldShell({
  icon: Icon,
  children,
  focused,
}: {
  icon: typeof User;
  children: React.ReactNode;
  focused?: boolean;
}) {
  return (
    <div
      className="flex items-center gap-2.5 px-3 py-2.5 rounded-md border bg-background transition-all"
      style={{
        borderColor: focused ? "var(--primary)" : "var(--border)",
        boxShadow: focused
          ? "0 0 0 3px color-mix(in oklab, var(--primary) 18%, transparent)"
          : undefined,
      }}
    >
      <Icon
        className="w-[13px] h-[13px] shrink-0"
        style={{ color: "var(--muted-foreground)" }}
      />
      {children}
    </div>
  );
}

function SetupForm() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [focus, setFocus] = useState<string | null>(null);
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
              // still restarting
            }
          }
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
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="flex items-center gap-2 -mt-2 mb-2 font-mono text-[11px] text-muted-foreground">
        <ShieldCheck
          className="w-3.5 h-3.5"
          style={{ color: "var(--primary)" }}
        />
        <span>first-run · create admin</span>
      </div>

      <div>
        <MonoLabel>Username</MonoLabel>
        <FieldShell icon={User} focused={focus === "u"}>
          <input
            type="text"
            placeholder="Choose a username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onFocus={() => setFocus("u")}
            onBlur={() => setFocus(null)}
            disabled={isSubmitting}
            autoComplete="username"
            className="flex-1 bg-transparent text-[13px] text-foreground outline-none placeholder:text-[var(--text-muted)]"
          />
        </FieldShell>
      </div>

      <div>
        <MonoLabel>Password</MonoLabel>
        <FieldShell icon={Lock} focused={focus === "p"}>
          <input
            type="password"
            placeholder="min 8 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onFocus={() => setFocus("p")}
            onBlur={() => setFocus(null)}
            disabled={isSubmitting}
            autoComplete="new-password"
            className="flex-1 bg-transparent text-[13px] text-foreground outline-none placeholder:text-[var(--text-muted)] tracking-[0.15em]"
          />
        </FieldShell>
      </div>

      <div>
        <MonoLabel>Confirm password</MonoLabel>
        <FieldShell icon={Lock} focused={focus === "c"}>
          <input
            type="password"
            placeholder="confirm"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            onFocus={() => setFocus("c")}
            onBlur={() => setFocus(null)}
            disabled={isSubmitting}
            autoComplete="new-password"
            className="flex-1 bg-transparent text-[13px] text-foreground outline-none placeholder:text-[var(--text-muted)] tracking-[0.15em]"
          />
        </FieldShell>
      </div>

      {error && (
        <div
          className="flex items-start gap-2 p-2.5 text-[12px] rounded-md border"
          style={{
            color: "var(--status-error)",
            background: "var(--status-error-bg)",
            borderColor:
              "color-mix(in oklab, var(--status-error) 30%, transparent)",
          }}
        >
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span className="font-mono">{error}</span>
        </div>
      )}

      <button
        type="submit"
        disabled={isSubmitting}
        className="w-full flex items-center justify-center gap-2 py-2.5 rounded-md text-[13px] font-semibold disabled:opacity-60"
        style={{
          background: "var(--primary)",
          color: "var(--primary-foreground)",
        }}
      >
        {isSubmitting ? (
          <>
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            {username ? "Restarting server…" : "Creating account…"}
          </>
        ) : (
          <>
            <span>Create account</span>
            <Kbd
              className="!bg-black/10 !border-black/20 !text-black/70"
              style={{ color: "rgba(0,0,0,0.7)" }}
            >
              ↵
            </Kbd>
          </>
        )}
      </button>
    </form>
  );
}

function LoginForm() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [focus, setFocus] = useState<string | null>(null);
  const [showPw, setShowPw] = useState(false);
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
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <MonoLabel>Username</MonoLabel>
        <FieldShell icon={User} focused={focus === "u"}>
          <input
            type="text"
            placeholder="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onFocus={() => setFocus("u")}
            onBlur={() => setFocus(null)}
            disabled={isVerifying}
            autoComplete="username"
            className="flex-1 bg-transparent text-[13px] text-foreground outline-none placeholder:text-[var(--text-muted)]"
          />
        </FieldShell>
      </div>

      <div>
        <MonoLabel>Password</MonoLabel>
        <FieldShell icon={Lock} focused={focus === "p"}>
          <input
            type={showPw ? "text" : "password"}
            placeholder="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onFocus={() => setFocus("p")}
            onBlur={() => setFocus(null)}
            disabled={isVerifying}
            autoComplete="current-password"
            className="flex-1 bg-transparent text-[13px] text-foreground outline-none placeholder:text-[var(--text-muted)] tracking-[0.15em]"
          />
          <button
            type="button"
            onClick={() => setShowPw((s) => !s)}
            className="font-mono text-[10px] text-muted-foreground hover:text-foreground"
            tabIndex={-1}
          >
            {showPw ? "hide" : "show"}
          </button>
        </FieldShell>
      </div>

      {error && (
        <div
          className="flex items-start gap-2 p-2.5 text-[12px] rounded-md border"
          style={{
            color: "var(--status-error)",
            background: "var(--status-error-bg)",
            borderColor:
              "color-mix(in oklab, var(--status-error) 30%, transparent)",
          }}
        >
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span className="font-mono">{error}</span>
        </div>
      )}

      <button
        type="submit"
        disabled={isVerifying}
        className="w-full flex items-center justify-center gap-2 py-2.5 rounded-md text-[13px] font-semibold disabled:opacity-60"
        style={{
          background: "var(--primary)",
          color: "var(--primary-foreground)",
        }}
      >
        {isVerifying ? (
          <>
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Signing in…
          </>
        ) : (
          <>
            <span>Continue</span>
            <Kbd className="!bg-black/10 !border-black/20 !text-black/70">
              ↵
            </Kbd>
          </>
        )}
      </button>

      <div className="flex items-center justify-between font-mono text-[10px] text-muted-foreground pt-1">
        <button
          type="button"
          className="hover:text-foreground"
          tabIndex={-1}
          onClick={(e) => e.preventDefault()}
        >
          forgot password
        </button>
        <span className="inline-flex items-center gap-1.5">
          <ArrowRight className="w-3 h-3" />
          <span>sso</span>
        </span>
      </div>
    </form>
  );
}

export default function LoginPage() {
  const { needsSetup } = useAuth();

  return (
    <div className="min-h-screen w-full bg-background text-foreground relative overflow-hidden grid place-items-center px-4">
      {/* Interactive shader grid backdrop */}
      <GridShader />

      {/* Card */}
      <div
        className="relative z-10 w-full max-w-[380px] p-6 rounded-[10px] border bg-card"
        style={{
          borderColor: "var(--border)",
          boxShadow: "0 30px 80px rgba(0,0,0,0.4)",
        }}
      >
        {/* Brand row */}
        <div className="flex items-center gap-2 mb-6">
          <Logo className="h-4 w-auto text-foreground" />
          <span className="ml-auto font-mono text-[10px] text-muted-foreground px-1.5 py-0.5 border border-border rounded-sm">
            v0.15.1
          </span>
        </div>

        <div className="text-[18px] font-semibold tracking-tight mb-1">
          {needsSetup ? "Create admin" : "Sign in"}
        </div>
        <div className="text-[12px] text-muted-foreground mb-4">
          {needsSetup
            ? "Set up your first account to unlock the library."
            : "Access your home server library."}
        </div>

        {needsSetup ? <SetupForm /> : <LoginForm />}
      </div>

      {/* Bottom status strip */}
      <div className="absolute left-5 right-5 bottom-5 flex justify-between font-mono text-[10px] text-muted-foreground z-10 pointer-events-none">
        <span className="flex items-center gap-1.5">
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ background: "var(--status-active)" }}
          />
          HOME.LAN
        </span>
        <span>COMICARR · READY</span>
      </div>
    </div>
  );
}
