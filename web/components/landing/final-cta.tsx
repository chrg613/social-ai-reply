"use client";

import Link from "next/link";
import { m } from "framer-motion";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function FinalCta() {
  return (
    <section className="py-20 md:py-28">
      <div className="mx-auto max-w-7xl px-6">
        <m.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6 }}
          className="relative overflow-hidden rounded-3xl px-8 py-16 text-center md:px-16 md:py-20"
          style={{
            background: "linear-gradient(135deg, var(--primary) 0%, var(--color-coral-hover) 100%)",
          }}
        >
          <div
            className="pointer-events-none absolute -right-20 -top-20 h-80 w-80 rounded-full opacity-20"
            style={{ background: "radial-gradient(circle, white 0%, transparent 70%)" }}
          />
          <div
            className="pointer-events-none absolute -bottom-20 -left-20 h-60 w-60 rounded-full opacity-10"
            style={{ background: "radial-gradient(circle, white 0%, transparent 70%)" }}
          />

          <div className="relative">
            <h2 className="text-3xl font-bold tracking-tight text-white md:text-5xl">
              Ready to Own Your AI Visibility?
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed" style={{ color: "rgba(255,255,255,0.85)" }}>
              Start tracking how AI models talk about your brand and discover the conversations that shape their answers.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-4 sm:flex-row">
              <Link
                href="/register"
                className={cn(
                  buttonVariants({ variant: "secondary", size: "default" }),
                  "h-12 rounded-xl bg-white px-8 text-base font-semibold text-primary hover:scale-[1.02] hover:shadow-[0_10px_40px_rgba(0,0,0,0.2)]"
                )}
              >
                Get Started Free
              </Link>
              <a
                href="mailto:hello@signalflow.com"
                className="inline-flex h-12 items-center justify-center rounded-xl border border-white/30 px-8 text-base font-semibold text-white transition-all duration-200 hover:border-white hover:scale-[1.02]"
              >
                Schedule Demo
              </a>
            </div>
          </div>
        </m.div>
      </div>
    </section>
  );
}
