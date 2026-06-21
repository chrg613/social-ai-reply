"use client";

import Link from "next/link";
import { m, useScroll, useMotionValueEvent } from "framer-motion";
import { useState } from "react";
import { Menu, LogOut, Settings, LayoutDashboard } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/components/auth/auth-provider";
import { ThemeToggle } from "@/components/shared/theme-toggle";
import { Button } from "@/components/ui/button";

const navLinks = [
  { label: "Features", href: "#features" },
  { label: "Pricing", href: "#pricing" },
  { label: "Testimonials", href: "#testimonials" },
];

export function Navbar() {
  const { scrollY } = useScroll();
  const [isScrolled, setIsScrolled] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { user, loading, logout } = useAuth();

  useMotionValueEvent(scrollY, "change", (latest) => {
    setIsScrolled(latest > 100);
  });

  const handleLogout = async () => {
    await logout();
    window.location.href = "/";
  };

  const userInitials = user?.full_name
    ? user.full_name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : (user?.email?.[0]?.toUpperCase() ?? "U");

  return (
    <m.nav
      className="fixed top-0 left-0 right-0 z-50 transition-all duration-300"
      style={{
        backgroundColor: isScrolled
          ? "color-mix(in srgb, var(--background) 80%, transparent)"
          : "transparent",
        backdropFilter: isScrolled ? "blur(12px)" : "none",
        WebkitBackdropFilter: isScrolled ? "blur(12px)" : "none",
        borderBottom: isScrolled
          ? "1px solid var(--border)"
          : "1px solid transparent",
      }}
    >
      <div className="mx-auto max-w-7xl px-6">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <Link href="/" className="text-lg font-bold tracking-tight text-foreground">
            SignalFlow
          </Link>

          {/* Nav Links */}
          <div className="hidden items-center gap-8 md:flex">
            {navLinks.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className="relative text-sm font-medium text-muted-foreground transition-colors duration-200 hover:text-primary"
              >
                {link.label}
              </a>
            ))}
          </div>

          {/* Right side: theme toggle + CTA + mobile menu */}
          <div className="flex items-center gap-4">
            {/* Theme toggle (desktop only) */}
            <ThemeToggle className="hidden h-8 w-8 items-center justify-center rounded-lg bg-muted text-muted-foreground transition-colors duration-200 md:flex" />

            {/* User profile dropdown or CTA */}
            {!loading && (
              user ? (
                <DropdownMenu>
                  <DropdownMenuTrigger className="hidden h-9 w-9 items-center justify-center rounded-full bg-primary text-sm font-semibold text-white transition-colors duration-200 hover:bg-[var(--color-coral-hover)] md:flex">
                    {userInitials}
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-56 p-1">
                    <div className="px-1.5 py-1">
                      <div className="truncate text-xs font-medium text-foreground">{user.full_name}</div>
                      <div className="truncate text-xs text-muted-foreground">{user.email}</div>
                    </div>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={() => window.location.href = "/app/dashboard"} className="cursor-pointer">
                      <LayoutDashboard className="mr-2 h-4 w-4" />
                      Dashboard
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => window.location.href = "/app/settings"} className="cursor-pointer">
                      <Settings className="mr-2 h-4 w-4" />
                      Settings
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={handleLogout} className="cursor-pointer text-destructive focus:text-destructive">
                      <LogOut className="mr-2 h-4 w-4" />
                      Sign out
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : (
                <Link
                  href="/register"
                  className={cn(buttonVariants({ size: "default" }), "hidden rounded-lg px-4 text-sm font-semibold md:inline-flex")}
                >
                  Get Started Free
                </Link>
              )
            )}

            {/* Mobile hamburger button */}
            <Button
              variant="outline"
              size="icon"
              onClick={() => setMobileMenuOpen(true)}
              className="md:hidden h-8 w-8"
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </Button>
          </div>

          {/* Mobile menu sheet */}
          <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
            <SheetContent side="right" className="w-72">
              <SheetHeader>
                <SheetTitle>SignalFlow</SheetTitle>
              </SheetHeader>
              <nav className="flex flex-col gap-4 px-4 pt-2">
                {navLinks.map((link) => (
                  <a
                    key={link.href}
                    href={link.href}
                    onClick={() => setMobileMenuOpen(false)}
                    className="text-base font-medium text-muted-foreground transition-colors duration-200 hover:text-primary"
                  >
                    {link.label}
                  </a>
                ))}

                {!loading && (
                  user ? (
                    <>
                      <div className="mt-2 rounded-lg bg-muted p-3">
                        <div className="text-sm font-medium text-foreground">{user.full_name}</div>
                        <div className="text-xs text-muted-foreground">{user.email}</div>
                      </div>
                      <Link
                        href="/app/dashboard"
                        onClick={() => setMobileMenuOpen(false)}
                        className="flex items-center gap-2 text-base font-medium text-muted-foreground transition-colors duration-200 hover:text-primary"
                      >
                        <LayoutDashboard className="h-4 w-4" />
                        Dashboard
                      </Link>
                      <Link
                        href="/app/settings"
                        onClick={() => setMobileMenuOpen(false)}
                        className="flex items-center gap-2 text-base font-medium text-muted-foreground transition-colors duration-200 hover:text-primary"
                      >
                        <Settings className="h-4 w-4" />
                        Settings
                      </Link>
                      <button
                        onClick={() => {
                          setMobileMenuOpen(false);
                          void handleLogout();
                        }}
                        className="flex items-center gap-2 text-base font-medium text-destructive transition-colors duration-200"
                      >
                        <LogOut className="h-4 w-4" />
                        Sign out
                      </button>
                    </>
                  ) : (
                    <Link
                      href="/register"
                      onClick={() => setMobileMenuOpen(false)}
                      className={cn(buttonVariants({ size: "default" }), "mt-2 inline-flex h-10 items-center justify-center rounded-lg px-4 text-sm font-semibold")}
                    >
                      Get Started Free
                    </Link>
                  )
                )}
                <ThemeToggle
                  className="mt-2 flex h-8 w-full items-center justify-center gap-2 rounded-lg bg-muted text-sm text-muted-foreground transition-colors duration-200"
                  showLabel
                />
              </nav>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </m.nav>
  );
}
