"use client";

import Link from "next/link";
import { m } from "framer-motion";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const features = [
  "Unlimited projects",
  "Unlimited keywords & scans",
  "Unlimited communities",
  "AI visibility tracking",
  "Smart opportunity discovery",
  "Content studio & reply drafting",
  "Analytics & reporting",
  "Auto-pipeline setup",
];

export function Pricing() {
  return (
    <section id="pricing" aria-labelledby="pricing-heading" className="py-20 md:py-28">
      <div className="mx-auto max-w-4xl px-6">
        <m.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.5 }}
          className="text-center"
        >
          <span className="mb-4 inline-block text-xs font-semibold uppercase tracking-widest text-primary">
            Pricing
          </span>
          <h2
            id="pricing-heading"
            className="text-3xl font-bold tracking-tight md:text-4xl text-foreground"
          >
            Free for everyone
          </h2>
          <p className="mx-auto mt-4 max-w-lg text-base text-muted-foreground">
            SignalFlow is 100% free while we&apos;re in early access — no limits,
            no credit card, every feature unlocked.
          </p>
        </m.div>

        <m.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.5, ease: "easeOut" }}
          className="mx-auto mt-12 max-w-md"
        >
          <div
            className="relative flex flex-col rounded-2xl border border-primary p-8 bg-background"
            style={{ boxShadow: "0 10px 40px var(--color-coral-glow)" }}
          >
            <div className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-primary px-3 py-1 text-xs font-semibold text-white">
              Early Access
            </div>

            <div className="text-lg font-semibold text-foreground">Free forever</div>
            <p className="mt-1 text-sm text-muted-foreground">
              Everything unlocked. Every feature. No paywalls.
            </p>

            <div className="mt-6">
              <span className="text-5xl font-bold tracking-tight text-foreground">$0</span>
              <span className="ml-1 text-sm text-muted-foreground">/ forever</span>
            </div>

            <ul className="mt-6 flex-1 space-y-3">
              {features.map((feature) => (
                <li key={feature} className="flex items-center gap-2 text-sm text-muted-foreground">
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    style={{ color: "var(--primary)" }}
                  >
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  {feature}
                </li>
              ))}
            </ul>

            <Link
              href="/register"
              className={cn(
                buttonVariants({ variant: "default", size: "default" }),
                "mt-8 h-12 rounded-xl px-8 text-sm font-semibold hover:scale-[1.02]",
              )}
            >
              Get started — it&apos;s free
            </Link>
          </div>
        </m.div>
      </div>
    </section>
  );
}
