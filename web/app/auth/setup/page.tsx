"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Loader2, User } from "lucide-react";
import { useAuth } from "@/components/auth/auth-provider";
import { supabase } from "@/lib/supabase";
import { useToast } from "@/stores/toast";
import { getErrorMessage } from "@/types/errors";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { BrandPanel } from "@/components/shared/brand-panel";

function SetupForm() {
  const router = useRouter();
  const { completeOAuthSetup } = useAuth();
  const { success, error } = useToast();
  const [workspace, setWorkspace] = useState("");
  const [loading, setLoading] = useState(false);
  const [userInfo, setUserInfo] = useState<{ email: string; name: string }>({
    email: "",
    name: "",
  });
  const [fieldError, setFieldError] = useState("");

  useEffect(() => {
    async function loadUser() {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (!session) {
        router.replace("/login");
        return;
      }
      const meta = (session.user?.user_metadata ?? {}) as Record<string, unknown>;
      setUserInfo({
        email: session.user?.email ?? "",
        name:
          (meta.full_name as string | undefined) ??
          (meta.name as string | undefined) ??
          "",
      });
    }
    loadUser();
  }, [router]);

  function validateWorkspace(value: string): string {
    if (!value.trim()) return "Workspace name is required.";
    if (value.trim().length < 2) return "Must be at least 2 characters.";
    return "";
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const err = validateWorkspace(workspace);
    if (err) {
      setFieldError(err);
      return;
    }
    setLoading(true);
    try {
      await completeOAuthSetup(workspace.trim());
      success("Account created!", "Your workspace is ready.");
      router.push("/app/dashboard");
    } catch (err: unknown) {
      error("Setup failed", getErrorMessage(err) || "Could not create workspace.");
    }
    setLoading(false);
  }

  return (
    <div className="flex min-h-screen">
      {/* Left branded panel */}
      <BrandPanel />

      {/* Right form panel */}
      <div className="flex w-full flex-col items-center justify-center px-6 py-12 md:w-1/2">
        {/* Mobile-only slim header */}
        <div className="mb-8 md:hidden">
          <Link href="/" className="text-xl font-bold text-primary">
            SignalFlow
          </Link>
        </div>

        <div className="w-full max-w-sm">
          <div className="mb-8 text-center">
            <h1 className="text-2xl font-bold tracking-tight">
              Finish setting up
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              One more step to get started
            </p>
          </div>

          {userInfo.email && (
            <div className="mb-6 flex items-center gap-3 rounded-lg border bg-muted/50 px-4 py-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10">
                <User className="h-4 w-4 text-primary" />
              </div>
              <div className="min-w-0 text-left">
                <div className="truncate text-sm font-semibold">
                  {userInfo.name || "Welcome!"}
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {userInfo.email}
                </div>
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div className="space-y-2">
              <Label htmlFor="workspace">Workspace Name</Label>
              <Input
                id="workspace"
                type="text"
                value={workspace}
                onChange={(e) => {
                  setWorkspace(e.target.value);
                  setFieldError("");
                }}
                onBlur={() => setFieldError(validateWorkspace(workspace))}
                placeholder="Your company name"
                autoFocus
                required
                aria-invalid={!!fieldError}
              />
              {fieldError ? (
                <p className="text-xs text-destructive">{fieldError}</p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  This is your team&apos;s shared workspace
                </p>
              )}
            </div>
            <Button
              type="submit"
              disabled={loading}
              className="w-full"
              size="lg"
            >
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Creating workspace...
                </>
              ) : (
                "Create Workspace"
              )}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default function AuthSetupPage() {
  return <SetupForm />;
}
