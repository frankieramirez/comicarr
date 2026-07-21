interface FocusLayoutProps {
  children: React.ReactNode;
}

/** A viewport-sized shell for protected workspaces that need the app chrome hidden. */
export default function FocusLayout({ children }: FocusLayoutProps) {
  return (
    <main className="h-dvh w-screen overflow-hidden bg-background">
      {children}
    </main>
  );
}
