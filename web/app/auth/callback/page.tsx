"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Loader2, RefreshCw } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { apiRequest, isSetupRequired, type AuthPayload } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { Button, buttonVariants } from "@/components/ui/button";

export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    async function resolveSession(accessToken: string, retries = 0) {
      if (cancelled) return;
      try {
        const payload = await apiRequest<AuthPayload>(
          "/v1/auth/me",
          {},
          accessToken,
        );
        const stored = { ...payload, access_token: accessToken };
        useAuthStore.getState().persist(stored);
        router.replace("/app/dashboard");
      } catch (err) {
        if (isSetupRequired(err)) {
          router.replace("/auth/setup");
        } else if (retries < 1) {
          // Retry once after a brief delay for transient errors
          timeoutId = setTimeout(() => resolveSession(accessToken, retries + 1), 2000);
        } else {
          setError(
            err instanceof Error
              ? err.message
              : "Authentication failed. Please try again.",
          );
        }
      }
    }

    async function handleCallback() {
      const {
        data: { session },
        error: sessionError,
      } = await supabase.auth.getSession();

      if (sessionError || !session?.access_token) {
        // Fallback: listen for the auth state change event.
        const {
          data: { subscription },
        } = supabase.auth.onAuthStateChange(async (event, newSession) => {
          if (cancelled) return;
          if (event === "SIGNED_IN" && newSession?.access_token) {
            subscription.unsubscribe();
            await resolveSession(newSession.access_token);
          }
        });

        const retryTimer = setTimeout(() => {
          if (!cancelled) {
            subscription.unsubscribe();
            setError("Authentication timed out. Please try again.");
          }
        }, 10000);
        timeoutId = retryTimer;

        return;
      }

      await resolveSession(session.access_token);
    }

    handleCallback();

    return () => {
      cancelled = true;
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [router]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-4">
        <div className="w-full max-w-sm text-center">
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-destructive/10">
            <span className="text-2xl text-destructive">!</span>
          </div>
          <h2 className="text-xl font-semibold">Sign-in Failed</h2>
          <p className="mt-2 text-sm text-muted-foreground">{error}</p>
          <div className="mt-6 flex flex-col gap-3">
            <Button
              onClick={() => {
                setError(null);
                window.location.reload();
              }}
              className="w-full"
              size="lg"
            >
              <RefreshCw className="h-4 w-4" />
              Try Again
            </Button>
            <Link
              href="/login"
              className={`${buttonVariants({ variant: "outline", size: "lg" })} w-full`}
            >
              Back to Login
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background p-4">
      <Link href="/" className="mb-6 text-2xl font-bold text-primary">
        SignalFlow
      </Link>
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
      <p className="mt-4 text-sm text-muted-foreground">
        Completing sign-in...
      </p>
    </div>
  );
}
