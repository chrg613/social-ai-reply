"use client";

import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { type Project, apiRequest, isAuthError } from "@/lib/api";
import { getErrorMessage } from "@/types/errors";
import { setStoredProjectId, withProjectId } from "@/lib/project";
import { useSelectedProjectId } from "@/hooks/use-selected-project";

import { useAuth } from "@/components/auth/auth-provider";
import { supabase } from "@/lib/supabase";
import { useUIStore, COLLAPSED_WIDTH, MIN_WIDTH, MAX_WIDTH } from "@/stores/ui-store";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuLabel,
  DropdownMenuGroup,
} from "@/components/ui/dropdown-menu";
import {
  TooltipProvider,
} from "@/components/ui/tooltip";
import { Card } from "@/components/ui/card";
import {
  Loader2,
  Bell,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  LogOut,
  LayoutDashboard,
  Workflow,
  Eye,
  Search,
  Radar,
  FileText,
  Users,
  Palette,
  UserCircle,
  Terminal,
  Settings,
  Check,
  BarChart2,
} from "lucide-react";
import { MobileNav } from "@/components/shared/mobile-nav";
import { ThemeToggle } from "@/components/shared/theme-toggle";

interface DashData {
  workspace_name?: string;
  projects?: Project[];
}

interface NotificationData {
  unread_count: number;
}

interface NotificationItem {
  id: number;
  title: string;
  message: string;
  icon: string;
  link?: string;
  is_read: boolean;
  created_at: string;
}

function isNotificationRead(notification: NotificationItem): boolean {
  return notification.is_read;
}

const NAV_SECTIONS = [
  {
    title: "OVERVIEW",
    icon: LayoutDashboard,
    items: [
      { href: "/app/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { href: "/app/analytics", label: "Analytics", icon: BarChart2 },
      { href: "/app/agent-runs", label: "Agent Runs", icon: Workflow },
    ],
  },
  {
    title: "INTELLIGENCE",
    icon: Search,
    items: [
      { href: "/app/company", label: "Company Setup", icon: UserCircle },
      { href: "/app/brand-brain", label: "Brand Brain", icon: Palette },
      { href: "/app/sources", label: "Sources", icon: Search },
    ],
  },
  {
    title: "OPPORTUNITIES",
    icon: Radar,
    items: [
      { href: "/app/agents", label: "Agents Feed", icon: Radar },
      { href: "/app/discovery", label: "Social Radar", icon: Radar },
      { href: "/app/content", label: "Content Studio", icon: FileText },
    ],
  },
  {
    title: "OPTIMIZE",
    icon: Eye,
    items: [
      { href: "/app/seo-geo", label: "SEO / GEO", icon: Eye },
      { href: "/app/visibility", label: "AI Visibility", icon: Eye },
    ],
  },
  {
    title: "SETTINGS",
    icon: Settings,
    items: [
      { href: "/app/settings", label: "Settings", icon: Settings },
    ],
  },
];

const PATH_TITLES: Record<string, string> = {
  "/app/dashboard": "Dashboard",
  "/app/auto-pipeline": "Overview / Auto Pipeline",
  "/app/agent-runs": "Overview / Agent Runs",
  "/app/analytics": "Overview / Analytics",
  "/app/company": "Intelligence / Company Setup",
  "/app/brand-brain": "Intelligence / Brand Brain",
  "/app/sources": "Intelligence / Sources",
  "/app/agents": "Opportunities / Agents Feed",
  "/app/discovery": "Opportunities / Social Radar",
  "/app/content": "Opportunities / Content Studio",
  "/app/content-studio": "Opportunities / Content Studio (New)",
  "/app/subreddits": "Engage / Communities",
  "/app/brand": "Configure / Brand Profile",
  "/app/persona": "Configure / Personas",
  "/app/prompts": "Configure / Prompts",
  "/app/seo-geo": "Optimize / SEO / GEO",
  "/app/visibility": "Optimize / AI Visibility",
  "/app/settings": "Settings",
};

/** Group notifications into Today / Yesterday / Older buckets. */
function groupNotifications(notifications: NotificationItem[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);

  const groups: { label: string; items: NotificationItem[] }[] = [
    { label: "Today", items: [] },
    { label: "Yesterday", items: [] },
    { label: "Older", items: [] },
  ];

  for (const notif of notifications) {
    const created = new Date(notif.created_at);
    if (created >= today) {
      groups[0].items.push(notif);
    } else if (created >= yesterday) {
      groups[1].items.push(notif);
    } else {
      groups[2].items.push(notif);
    }
  }

  return groups.filter((g) => g.items.length > 0);
}

export default function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { token, loading: authLoading, logout } = useAuth();
  const [dash, setDash] = useState<DashData | null>(null);
  const [loading, setLoading] = useState(true);
  const [initialLoad, setInitialLoad] = useState(true);
  const [error, setError] = useState("");
  const [notifCount, setNotifCount] = useState(0);
  const selectedProjectId = useSelectedProjectId();
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);

  // Separate state for desktop and mobile notification popovers to avoid conflicts
  const [desktopNotifOpen, setDesktopNotifOpen] = useState(false);
  const [mobileNotifOpen, setMobileNotifOpen] = useState(false);
  const { sidebarOpen, setSidebarOpen } = useUIStore();

  const notificationGroups = useMemo(() => groupNotifications(notifications), [notifications]);

  useEffect(() => {
    if (authLoading) {
      return;
    }
    if (!token) {
      router.replace("/login");
      return;
    }
    void loadShell(selectedProjectId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, token, selectedProjectId]);

  useEffect(() => {
    if (!token) return;
    void loadNotifications();

    let intervalId: ReturnType<typeof setInterval> | null = null;

    function startPolling() {
      if (intervalId) return;
      intervalId = setInterval(() => {
        void loadNotifications();
      }, 60000);
    }

    function stopPolling() {
      if (intervalId) {
        clearInterval(intervalId);
        intervalId = null;
      }
    }

    function handleVisibility() {
      if (document.visibilityState === "visible") {
        startPolling();
      } else {
        stopPolling();
      }
    }

    startPolling();
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      stopPolling();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, selectedProjectId]);

  useEffect(() => {
    const projects = dash?.projects || [];
    if (!projects.length) {
      return;
    }
    if (selectedProjectId && projects.some((project) => project.id === selectedProjectId)) {
      return;
    }
    const nextProjectId = projects[0].id;
    setStoredProjectId(nextProjectId);
  }, [dash?.projects, selectedProjectId]);

  async function loadShell(projectId: number | null) {
    // Only show full-page spinner on the very first load (before any data exists).
    // Subsequent project switches keep the current UI visible while fetching.
    if (initialLoad) {
      setLoading(true);
    }
    try {
      const [dashRes, notifRes] = await Promise.allSettled([
        apiRequest<DashData>(withProjectId("/v1/dashboard", projectId), {}, token),
        apiRequest<NotificationData>("/v1/notifications", {}, token),
      ]);

      if (dashRes.status === "fulfilled") {
        setDash(dashRes.value);
      }
      if (notifRes.status === "fulfilled") {
        setNotifCount(notifRes.value.unread_count || 0);
      }

      const dashFailed = dashRes.status === "rejected" && isAuthError(dashRes.reason);
      if (dashFailed) {
        // Token may have expired between bootstrap and this fetch.
        // Attempt a Supabase token refresh before giving up entirely.
        try {
          const { data: { session: refreshed } } = await supabase.auth.refreshSession();
          if (refreshed?.access_token) {
            const retryRes = await apiRequest<DashData>(
              withProjectId("/v1/dashboard", projectId), {}, refreshed.access_token
            );
            setDash(retryRes);
          } else {
            void logout();
            router.replace("/login");
            return;
          }
        } catch {
          void logout();
          router.replace("/login");
          return;
        }
      }
    } catch (e: unknown) {
      const msg = getErrorMessage(e);
      if (isAuthError(e)) {
        try {
          const { data: { session: refreshed } } = await supabase.auth.refreshSession();
          if (refreshed?.access_token) {
            const retryRes = await apiRequest<DashData>(
              withProjectId("/v1/dashboard", projectId), {}, refreshed.access_token
            );
            setDash(retryRes);
          } else {
            void logout();
            router.replace("/login");
            return;
          }
        } catch {
          void logout();
          router.replace("/login");
          return;
        }
      }
      setError(msg || "Failed to load workspace");
    }
    setLoading(false);
    setInitialLoad(false);
  }

  async function loadNotifications() {
    try {
      const res = await apiRequest<{ items: NotificationItem[] }>(
        "/v1/notifications",
        {},
        token
      );
      setNotifications(res.items || []);
      const unread = (res.items || []).filter((n) => !isNotificationRead(n)).length;
      setNotifCount(unread);
    } catch {
      // Silently ignore — notifications are non-critical and may hit rate limits during heavy usage
    }
  }

  async function markAsRead(notificationId: number) {
    try {
      await apiRequest(`/v1/notifications/${notificationId}/read`, { method: "PUT" }, token);
      setNotifications((prev) => prev.map((n) => (n.id === notificationId ? { ...n, is_read: true } : n)));
      setNotifCount((prev) => Math.max(prev - 1, 0));
    } catch (error) {
      console.error("Failed to mark as read:", error);
    }
  }

  async function markAllAsRead() {
    try {
      await apiRequest("/v1/notifications/read-all", { method: "PUT" }, token);
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
      setNotifCount(0);
    } catch (error) {
      console.error("Failed to mark all as read:", error);
    }
  }

  function handleNotificationClick(notif: NotificationItem) {
    if (!isNotificationRead(notif)) {
      void markAsRead(notif.id);
    }
    if (notif.link) {
      router.push(notif.link);
      setDesktopNotifOpen(false);
      setMobileNotifOpen(false);
    }
  }

  function handleLogout() {
    void logout();
    router.replace("/login");
  }

  const selectedProject =
    dash?.projects?.find((project) => project.id === selectedProjectId) ??
    dash?.projects?.[0] ??
    null;

  const currentTitle = PATH_TITLES[pathname] || "Workspace";

  // Sidebar state
  const {
    sidebarCollapsed,
    sidebarWidth,
    collapsedSections,
    toggleSidebarCollapsed,
    setSidebarCollapsed,
    setSidebarWidth,
    toggleSection,
  } = useUIStore();

  // Resize handle logic
  const isResizing = useRef(false);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isResizing.current = true;
    setSidebarCollapsed(false);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing.current) return;
      const newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, e.clientX));
      setSidebarWidth(Math.round(newWidth));
    };

    const handleMouseUp = () => {
      isResizing.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
  }, [setSidebarCollapsed, setSidebarWidth]);

  const effectiveWidth = sidebarCollapsed ? COLLAPSED_WIDTH : sidebarWidth;

  if (authLoading || loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto text-primary" />
          <p className="mt-4 text-muted-foreground">Loading your workspace...</p>
        </div>
      </div>
    );
  }

  if (error && !dash) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Card className="max-w-sm text-center p-6">
          <h3 className="text-sm font-semibold">Something went wrong</h3>
          <p className="mt-1 text-sm text-muted-foreground">{error}</p>
          <Button
            variant="outline"
            className="mt-4"
            onClick={() => {
              setError("");
              void loadShell(selectedProjectId);
            }}
          >
            Retry
          </Button>
        </Card>
      </div>
    );
  }

  return (
    <TooltipProvider>
      <div className="flex h-screen">
        <style>{`
          .rf-main-content { margin-left: 0; }
          @media (min-width: 768px) {
            .rf-main-content { margin-left: var(--sidebar-w); transition: margin-left 200ms ease-in-out; }
          }
        `}</style>
        {/* Sidebar (desktop only) */}
        <aside
          className="hidden md:flex fixed inset-y-0 left-0 z-40 bg-sidebar text-sidebar-foreground flex-col transition-[width] duration-200 ease-in-out"
          style={{ width: `${effectiveWidth}px` }}
        >
          {/* Brand */}
          <div className={cn(
            "flex items-center shrink-0 border-b border-sidebar-border/50",
            sidebarCollapsed ? "justify-center py-4 px-2" : "gap-3 px-4 py-4"
          )}>
            <Link href="/app/dashboard" className="flex items-center gap-2 text-sidebar-foreground no-underline">
              {/* SVG Logo icon */}
              <div className={cn(
                "flex items-center justify-center rounded-lg bg-sidebar-primary/15 shrink-0",
                sidebarCollapsed ? "h-9 w-9" : "h-8 w-8"
              )}>
                <svg viewBox="0 0 24 24" className={cn("h-5 w-5 text-sidebar-primary", sidebarCollapsed && "h-6 w-6")} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M9.5 9.5a3.5 3.5 0 0 1 5 0" />
                  <path d="M14.5 14.5a3.5 3.5 0 0 1-5 0" />
                  <circle cx="9.5" cy="9.5" r="0.5" fill="currentColor" />
                  <circle cx="14.5" cy="14.5" r="0.5" fill="currentColor" />
                </svg>
              </div>
              {!sidebarCollapsed && (
                <div className="flex flex-col leading-none">
                  <span className="text-base font-bold tracking-tight">SignalFlow</span>
                  <span className="text-[9px] font-semibold text-sidebar-primary/70 uppercase tracking-widest mt-1">Community OS</span>
                </div>
              )}
            </Link>
          </div>

          {/* Project Selector */}
          {!sidebarCollapsed ? (
            <div className="shrink-0 p-3 mx-3">
              <DropdownMenu>
                <DropdownMenuTrigger
                  className="w-full rounded-lg border border-sidebar-border/50 bg-sidebar-accent/50 p-3 text-left cursor-pointer transition-colors hover:bg-sidebar-accent focus:outline-none focus:ring-2 focus:ring-sidebar-ring"
                >
                  <span className="block text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    {dash?.workspace_name || "Workspace"}
                  </span>
                  <span className="flex items-center justify-between mt-1">
                    <span className="text-sm font-semibold text-sidebar-foreground truncate">
                      {selectedProject?.name || "No project"}
                    </span>
                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0 ml-2" />
                  </span>
                  <span className="block text-[10px] text-muted-foreground/70 mt-0.5">
                    {(dash?.projects || []).length} project{(dash?.projects || []).length !== 1 ? "s" : ""}
                  </span>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-64 p-1" side="right">
                  <DropdownMenuGroup>
                    <DropdownMenuLabel className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60 px-2 pt-1">
                      {dash?.workspace_name || "Workspace"}
                    </DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    {(dash?.projects || []).map((project) => {
                      const isSelected = selectedProject?.id === project.id;
                      return (
                        <DropdownMenuItem
                          key={project.id}
                          className={cn(
                            "flex items-center gap-2 cursor-pointer py-2 px-3",
                            isSelected && "bg-primary/10 text-primary"
                          )}
                          onClick={() => {
                            setStoredProjectId(project.id);
                          }}
                        >
                          {isSelected && <Check className="h-4 w-4 shrink-0" />}
                          {!isSelected && <span className="w-4 shrink-0" />}
                          <span className="truncate text-sm">{project.name}</span>
                        </DropdownMenuItem>
                      );
                    })}
                    {(dash?.projects || []).length === 0 && (
                      <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                        No projects yet
                      </div>
                    )}
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ) : (
            <div className="shrink-0 flex justify-center py-3">
              <DropdownMenu>
                <DropdownMenuTrigger
                  className="h-8 w-8 rounded-md bg-sidebar-accent/50 border border-sidebar-border/50 flex items-center justify-center cursor-pointer transition-colors hover:bg-sidebar-accent focus:outline-none focus:ring-2 focus:ring-sidebar-ring"
                  title={selectedProject?.name || "No project"}
                >
                  <span className="text-[10px] font-bold text-sidebar-primary">
                    {(selectedProject?.name || "N")[0]}
                  </span>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-64 p-1" side="right">
                  <DropdownMenuGroup>
                    <DropdownMenuLabel className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60 px-2 pt-1">
                      {dash?.workspace_name || "Workspace"}
                    </DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    {(dash?.projects || []).map((project) => {
                      const isSelected = selectedProject?.id === project.id;
                      return (
                        <DropdownMenuItem
                          key={project.id}
                          className={cn(
                            "flex items-center gap-2 cursor-pointer py-2 px-3",
                            isSelected && "bg-primary/10 text-primary"
                          )}
                          onClick={() => {
                            setStoredProjectId(project.id);
                          }}
                        >
                          {isSelected && <Check className="h-4 w-4 shrink-0" />}
                          {!isSelected && <span className="w-4 shrink-0" />}
                          <span className="truncate text-sm">{project.name}</span>
                        </DropdownMenuItem>
                      );
                    })}
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          )}

          {/* Navigation */}
          <nav className="flex-1 overflow-y-auto py-3 sidebar-nav">
            {NAV_SECTIONS.map((section) => {
              const isCollapsed = collapsedSections.has(section.title);
              const SectionIcon = section.icon;
              return (
                <div key={section.title} className="mb-1">
                  {/* Section header */}
                  <button
                    type="button"
                    onClick={() => toggleSection(section.title)}
                    className={cn(
                      "w-full flex items-center gap-2 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground cursor-pointer transition-colors hover:text-sidebar-foreground no-underline border-none bg-transparent",
                      sidebarCollapsed ? "justify-center px-0" : ""
                    )}
                    title={sidebarCollapsed ? section.title : undefined}
                  >
                    {!sidebarCollapsed && (
                      isCollapsed
                        ? <ChevronRight className="h-3 w-3 shrink-0" />
                        : <ChevronDown className="h-3 w-3 shrink-0" />
                    )}
                    {sidebarCollapsed ? (
                      <SectionIcon className="h-3.5 w-3.5" />
                    ) : (
                      <span>{section.title}</span>
                    )}
                  </button>

                  {/* Section items */}
                  {!isCollapsed && !sidebarCollapsed && (
                    <div className="mt-0.5">
                      {section.items.map((item) => {
                        const isActive = pathname === item.href;
                        const ItemIcon = item.icon;
                        return (
                          <Link
                            key={item.href}
                            href={item.href}
                            className={cn(
                              "flex items-center gap-2.5 rounded-md mx-1 px-2.5 py-2 text-sm text-sidebar-foreground/80 no-underline transition-all duration-150 hover:bg-sidebar-accent hover:text-sidebar-foreground",
                              isActive && "bg-coral-glow text-primary font-medium"
                            )}
                            onClick={() => setSidebarOpen(false)}
                          >
                            <ItemIcon className={cn(
                              "h-4 w-4 shrink-0 transition-colors",
                              isActive && "text-primary"
                            )} />
                            <span className="flex-1 truncate">{item.label}</span>
                          </Link>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </nav>

          {/* Footer: collapse toggle + sign out */}
          <div className="shrink-0 border-t border-sidebar-border/50 p-2 flex items-center gap-1">
            {/* Collapse toggle */}
            <button
              type="button"
              onClick={toggleSidebarCollapsed}
              className="flex items-center justify-center h-8 w-8 rounded-md text-muted-foreground cursor-pointer transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground border-none bg-transparent shrink-0"
              title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {sidebarCollapsed
                ? <ChevronRight className="h-4 w-4" />
                : <ChevronLeft className="h-4 w-4" />
              }
            </button>

            {/* Sign out */}
            <Button
              variant="ghost"
              className={cn(
                "text-muted-foreground text-xs h-8 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground",
                sidebarCollapsed ? "w-8 px-0 justify-center" : "flex-1 justify-start"
              )}
              onClick={handleLogout}
              title="Sign out"
            >
              <LogOut className="h-3.5 w-3.5 shrink-0" />
              {!sidebarCollapsed && <span className="ml-2">Sign out</span>}
            </Button>
          </div>

          {/* Resize handle (only when expanded) */}
          {!sidebarCollapsed && (
            <div
              className="absolute inset-y-0 right-0 w-1 cursor-col-resize z-50 group"
              onMouseDown={handleMouseDown}
            >
              <div className="absolute inset-y-1 left-0 w-[2px] bg-transparent group-hover:bg-sidebar-primary/30 group-active:bg-sidebar-primary/50 rounded-full transition-colors" />
            </div>
          )}
        </aside>

        {/* Main content */}
        <main
          id="main-content"
          className="rf-main-content relative flex-1 flex flex-col min-w-0"
          style={{
            ["--sidebar-w" as string]: `${effectiveWidth}px`,
          }}
        >
        {/* Topbar */}
        <div className="sticky top-0 z-10 flex items-center justify-between h-14 px-4 md:px-6 border-b border-border bg-card/80 backdrop-blur-sm shadow-[0_1px_2px_rgba(120,113,108,0.04)]">
          <div>
            <h1 className="text-lg font-semibold text-foreground">{currentTitle}</h1>
          </div>
          <div className="flex items-center gap-3">
            <ThemeToggle className="h-8 w-8 rounded-md flex items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground transition-colors" />
            {/* Notification popover (hidden on mobile) */}
            <div className="hidden md:block">
              <Popover open={desktopNotifOpen} onOpenChange={setDesktopNotifOpen}>
                <span className="relative inline-flex">
                  <PopoverTrigger
                    className="relative flex items-center justify-center h-[34px] px-2.5 rounded-lg border border-border bg-transparent hover:bg-muted cursor-pointer text-foreground"
                  >
                    <Bell className="h-4 w-4" />
                    <span
                      aria-hidden="true"
                      className={cn(
                        "absolute -top-1 -right-1 h-4 w-4 rounded-full bg-destructive text-destructive-foreground flex items-center justify-center text-[10px] font-bold",
                        notifCount === 0 && "hidden"
                      )}
                    >
                      {notifCount > 0 ? (notifCount > 9 ? "9+" : notifCount) : ""}
                    </span>
                  </PopoverTrigger>
                  <span
                    aria-live="polite"
                    aria-atomic="true"
                    className="sr-only"
                  >
                    {notifCount > 0 ? `${notifCount} new notifications` : ""}
                  </span>
                </span>
                <PopoverContent align="end" className="w-80 p-0">
                  <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                    <strong className="text-sm">Notifications</strong>
                    {notifications.some((n) => !isNotificationRead(n)) && (
                      <Button
                        variant="ghost"
                        size="xs"
                        className="text-xs text-primary"
                        onClick={() => void markAllAsRead()}
                      >
                        Mark all read
                      </Button>
                    )}
                  </div>
                  <div className="max-h-[380px] overflow-y-auto">
                    {notificationGroups.length === 0 ? (
                      <div className="px-6 py-6 text-center text-muted-foreground text-xs">
                        No notifications yet
                      </div>
                    ) : (
                      notificationGroups.map((group) => (
                        <div key={group.label}>
                          <div className="px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/60 bg-muted/30">
                            {group.label}
                          </div>
                          {group.items.map((notif) => (
                            <div
                              key={notif.id}
                              role="button"
                              tabIndex={0}
                              onClick={() => handleNotificationClick(notif)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault();
                                  handleNotificationClick(notif);
                                }
                              }}
                              className={`px-4 py-2.5 border-b border-border last:border-b-0 transition-colors ${
                                notif.link ? "cursor-pointer hover:bg-muted/50" : "cursor-default"
                              } ${!isNotificationRead(notif) ? "bg-primary/[0.04] border-l-[3px] border-l-primary dark:bg-primary/[0.08]" : ""}`}
                            >
                              <div className="font-semibold text-[13px] mb-0.5">{notif.title}</div>
                              <div className="text-xs text-muted-foreground leading-snug">{notif.message}</div>
                              <div className="text-[11px] text-muted-foreground mt-1 opacity-70">
                                {new Date(notif.created_at).toLocaleString()}
                              </div>
                            </div>
                          ))}
                        </div>
                      ))
                    )}
                  </div>
                </PopoverContent>
              </Popover>
            </div>

            {/* Mobile notification bell (simplified) */}
            <div className="md:hidden">
              <Popover open={mobileNotifOpen} onOpenChange={setMobileNotifOpen}>
                <span className="relative inline-flex">
                  <PopoverTrigger
                    className="relative flex items-center justify-center h-8 w-8 rounded-lg bg-transparent border-none cursor-pointer text-foreground"
                  >
                    <Bell className="h-4 w-4" />
                    <span
                      aria-hidden="true"
                      className={cn(
                        "absolute -top-0.5 -right-0.5 h-3 w-3 rounded-full bg-destructive",
                        notifCount === 0 && "hidden"
                      )}
                    />
                  </PopoverTrigger>
                  <span
                    aria-live="polite"
                    aria-atomic="true"
                    className="sr-only"
                  >
                    {notifCount > 0 ? `${notifCount} new notifications` : ""}
                  </span>
                </span>
                <PopoverContent align="end" className="w-72 p-0">
                  <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                    <strong className="text-sm">Notifications</strong>
                    {notifications.some((n) => !isNotificationRead(n)) && (
                      <Button
                        variant="ghost"
                        size="xs"
                        className="text-xs text-primary"
                        onClick={() => void markAllAsRead()}
                      >
                        Mark all read
                      </Button>
                    )}
                  </div>
                  <div className="max-h-[320px] overflow-y-auto">
                    {notificationGroups.length === 0 ? (
                      <div className="px-6 py-6 text-center text-muted-foreground text-xs">
                        No notifications yet
                      </div>
                    ) : (
                      notificationGroups.map((group) => (
                        <div key={group.label}>
                          <div className="px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/60 bg-muted/30">
                            {group.label}
                          </div>
                          {group.items.map((notif) => (
                            <div
                              key={notif.id}
                              role="button"
                              tabIndex={0}
                              onClick={() => handleNotificationClick(notif)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault();
                                  handleNotificationClick(notif);
                                }
                              }}
                              className={`px-4 py-2.5 border-b border-border last:border-b-0 transition-colors ${
                                notif.link ? "cursor-pointer hover:bg-muted/50" : "cursor-default"
                              } ${!isNotificationRead(notif) ? "bg-primary/[0.04] border-l-[3px] border-l-primary dark:bg-primary/[0.08]" : ""}`}
                            >
                              <div className="font-semibold text-[13px] mb-0.5">{notif.title}</div>
                              <div className="text-xs text-muted-foreground leading-snug">{notif.message}</div>
                              <p className="text-xs text-muted-foreground">{new Date(notif.created_at).toLocaleString()}</p>
                            </div>
                          ))}
                        </div>
                      ))
                    )}
                  </div>
                </PopoverContent>
              </Popover>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-auto pb-14 md:pb-0">
          <div className="mx-auto w-full max-w-7xl p-4 md:p-6 lg:p-8">
            {children}
          </div>
        </div>

        {/* Mobile bottom tab bar */}
        <MobileNav />
      </main>
    </div>
    </TooltipProvider>
  );
}
