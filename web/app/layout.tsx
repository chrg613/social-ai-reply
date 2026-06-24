import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";
import { Toaster } from "@/components/ui/sonner";

import "../styles/globals.css";
import { AuthProvider } from "../components/auth/auth-provider";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { TooltipProvider } from "@/components/ui/tooltip";
import { MotionProvider } from "@/components/providers/motion-provider";
import { Inter } from "next/font/google";
import { cn } from "@/lib/utils";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "SignalFlow",
  description:
    "AI visibility, community engagement, and content workflows for brands building authority across modern discovery channels.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={cn(inter.variable)} data-scroll-behavior="smooth">
      <body suppressHydrationWarning className="relative">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:z-[100] focus:top-2 focus:left-2 focus:bg-primary focus:text-primary-foreground focus:px-4 focus:py-2 focus:rounded-md"
        >
          Skip to main content
        </a>
        <ThemeProvider
          attribute="data-theme"
          defaultTheme="light"
          enableSystem
          disableTransitionOnChange
          storageKey="rf-theme"
        >
          <ErrorBoundary>
            <AuthProvider>
              <MotionProvider>
                <TooltipProvider>
                  {children}
                  <Toaster richColors position="bottom-right" />
                </TooltipProvider>
              </MotionProvider>
            </AuthProvider>
          </ErrorBoundary>
        </ThemeProvider>
      </body>
    </html>
  );
}
