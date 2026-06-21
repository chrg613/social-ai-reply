"use client";

import Link from "next/link";
import { type Variants, m, useScroll, useTransform } from "framer-motion";
import { useRef } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const containerVariants: Variants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.12 },
  },
};

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 30 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: "easeOut" } },
};

export function Hero() {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const imageY = useTransform(scrollYProgress, [0, 1], [0, 30]);

  return (
    <section ref={ref} aria-labelledby="hero-heading" className="relative overflow-hidden pb-8 pt-32 md:pb-16 md:pt-44">
      {/* Decorative gradient orbs */}
      <div
        className="pointer-events-none absolute -top-40 left-1/2 h-[600px] w-[600px] -translate-x-1/2 rounded-full opacity-20 blur-3xl"
        style={{ background: "radial-gradient(circle, var(--primary) 0%, transparent 70%)" }}
      />

      <m.div
        className="relative mx-auto max-w-7xl px-6 text-center"
        variants={containerVariants}
        initial="hidden"
        animate="visible"
      >
        {/* Eyebrow */}
        <m.div variants={fadeUp}>
          <span
            className="mb-6 inline-block rounded-full bg-coral-glow px-4 py-1.5 text-xs font-semibold uppercase tracking-widest text-primary"
          >
            AI Visibility Platform
          </span>
        </m.div>

        {/* Headline */}
        <m.h1
          id="hero-heading"
          variants={fadeUp}
          className="mx-auto max-w-4xl text-4xl font-bold leading-tight tracking-tight text-foreground md:text-5xl lg:text-6xl"
        >
          See How AI Talks About{" "}
          <span
            className="bg-clip-text text-transparent"
            style={{
              backgroundImage: "linear-gradient(135deg, var(--primary), var(--color-coral-hover))",
            }}
          >
            Your Brand
          </span>
        </m.h1>

        {/* Subtitle */}
        <m.p
          variants={fadeUp}
          className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground md:text-xl"
        >
          SignalFlow tracks your brand across Reddit, X, Instagram, LinkedIn, and TikTok — then uses
          AI to find the conversations that shape what people say about you.
        </m.p>

        {/* CTA Buttons */}
        <m.div variants={fadeUp} className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
          <Link
            href="/register"
            className={cn(buttonVariants({ size: "default" }), "h-12 rounded-xl px-8 text-base font-semibold hover:scale-[1.02]")}
          >
            Start Free Trial
          </Link>
          <a
            href="#features"
            className={cn(buttonVariants({ variant: "outline", size: "default" }), "h-12 rounded-xl px-8 text-base font-semibold hover:scale-[1.02]")}
          >
            Watch Demo
          </a>
        </m.div>

        {/* Product Screenshot Mockup */}
        <m.div
          variants={fadeUp}
          style={{ y: imageY }}
          className="relative mx-auto mt-16 max-w-5xl"
        >
          <div
            className="overflow-hidden rounded-2xl border border-border p-1"
            style={{
              boxShadow: "var(--shadow-lg), 0 0 80px var(--color-coral-glow)",
            }}
          >
            <div
              className="rounded-xl bg-background p-6"
            >
              {/* Mock dashboard UI */}
              <div className="flex items-center gap-2 pb-4">
                <div className="h-3 w-3 rounded-full bg-red-400" />
                <div className="h-3 w-3 rounded-full bg-yellow-400" />
                <div className="h-3 w-3 rounded-full bg-green-400" />
                <div
                  className="ml-4 h-6 flex-1 rounded-md bg-muted"
                />
              </div>
              <div className="grid grid-cols-4 gap-4">
                <div
                  className="col-span-1 rounded-lg bg-muted p-4"
                >
                  <div className="text-xs font-medium text-muted-foreground">
                    Visibility Score
                  </div>
                  <div className="mt-2 text-3xl font-bold text-primary">
                    87
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    +12% this week
                  </div>
                </div>
                {["ChatGPT", "Perplexity", "Gemini"].map((model) => (
                  <div
                    key={model}
                    className="rounded-lg bg-muted p-4"
                  >
                    <div className="text-xs font-medium text-muted-foreground">
                      {model}
                    </div>
                    <div className="mt-2 text-lg font-bold text-foreground">
                      {model === "ChatGPT" ? "Mentioned" : model === "Perplexity" ? "Cited" : "Detected"}
                    </div>
                    <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-border">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: model === "ChatGPT" ? "92%" : model === "Perplexity" ? "78%" : "65%",
                          backgroundColor: "var(--primary)",
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3">
                {["r/SaaS — Best CRM for startups?", "r/Marketing — AI tools comparison 2025"].map((title) => (
                  <div
                    key={title}
                    className="rounded-lg border border-border bg-muted p-3"
                  >
                    <div className="text-sm font-medium text-foreground">
                      {title}
                    </div>
                    <div className="mt-1 flex items-center gap-2">
                      <span
                        className="rounded-full bg-coral-glow px-2 py-0.5 text-xs font-medium text-primary"
                      >
                        High Intent
                      </span>
                      <span className="text-xs text-muted-foreground">
                        Score: 94
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </m.div>
      </m.div>
    </section>
  );
}
