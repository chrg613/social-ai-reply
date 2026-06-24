import Link from "next/link";
import { ThemeToggle } from "@/components/shared/theme-toggle";

export function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen">
      {/* Left branded panel */}
      <div
        className="hidden md:flex md:w-1/2 flex-col items-center justify-center p-12 text-center relative overflow-hidden"
        style={{
          background: "linear-gradient(to bottom right, var(--auth-brand-from), var(--auth-brand-to))",
          color: "var(--auth-brand-text)",
        }}
      >
        <Link href="/" className="mb-4 font-heading text-2xl font-bold z-10">
          SignalFlow
        </Link>
        <p className="max-w-xs text-base leading-relaxed z-10" style={{ color: "var(--auth-brand-text-muted)" }}>
          Find your audience. Engage authentically. Grow on Reddit.
        </p>
        {/* decorative circles */}
        <div className="pointer-events-none absolute bottom-0 left-0 h-64 w-64 rounded-full blur-3xl" style={{ background: "var(--auth-brand-accent)" }} />
        <div className="pointer-events-none absolute right-0 top-0 h-48 w-48 rounded-full blur-3xl" style={{ background: "var(--auth-brand-accent)" }} />
      </div>

      {/* Right form panel */}
      <div className="flex w-full flex-col items-center justify-center px-6 py-12 md:w-1/2 bg-background relative">
        <div className="absolute top-4 right-4 md:top-6 md:right-6">
          <ThemeToggle />
        </div>
        <div className="w-full max-w-sm">
          {children}
        </div>
      </div>
    </div>
  );
}
