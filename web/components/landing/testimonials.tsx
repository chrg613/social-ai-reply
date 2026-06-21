"use client";

import { m } from "framer-motion";

const testimonials = [
  {
    quote: "SignalFlow showed us that ChatGPT was recommending our competitor in 8 out of 10 queries. Within a month of targeted engagement, we flipped that to 7 out of 10 mentioning us.",
    name: "Sarah Chen",
    role: "Head of Growth",
    company: "TechStack",
  },
  {
    quote: "The opportunity scoring is incredible. It surfaces exactly the conversations where our expertise adds value — and the AI drafts are surprisingly natural. Saves us 10+ hours a week.",
    name: "Marcus Rivera",
    role: "SEO Lead",
    company: "Growth Agency Co.",
  },
  {
    quote: "We went from invisible in AI search results to being the #1 recommended tool in our category on Perplexity. SignalFlow made it systematic instead of random.",
    name: "Aisha Patel",
    role: "Founder",
    company: "ClearView Analytics",
  },
];

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.15 } },
};

const cardVariants = {
  hidden: { opacity: 0, y: 30 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

export function Testimonials() {
  return (
    <section id="testimonials" aria-labelledby="testimonials-heading" className="py-20 md:py-28">
      <div className="mx-auto max-w-7xl px-6">
        <m.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.5 }}
          className="text-center"
        >
          <span
            className="mb-4 inline-block text-xs font-semibold uppercase tracking-widest text-primary"
          >
            Testimonials
          </span>
          <h2
            id="testimonials-heading"
            className="text-3xl font-bold tracking-tight md:text-4xl text-foreground"
          >
            Trusted by growth teams everywhere
          </h2>
        </m.div>

        <m.div
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-100px" }}
          className="mt-14 grid gap-6 md:grid-cols-3"
        >
          {testimonials.map((t) => (
            <m.div
              key={t.name}
              variants={cardVariants}
              whileHover={{ y: -4 }}
              className="flex flex-col rounded-2xl border border-border bg-background p-6"
            >
              <div className="mb-4 flex gap-1 text-primary">
                {Array.from({ length: 5 }).map((_, i) => (
                  <svg key={i} width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                  </svg>
                ))}
              </div>
              <p className="flex-1 text-sm leading-relaxed text-muted-foreground">
                &ldquo;{t.quote}&rdquo;
              </p>
              <div className="mt-6 flex items-center gap-3">
                <div
                  className="flex h-10 w-10 items-center justify-center rounded-full text-sm font-bold text-white bg-primary"
                >
                  {t.name.charAt(0)}
                </div>
                <div>
                  <div className="text-sm font-semibold text-foreground">{t.name}</div>
                  <div className="text-xs text-muted-foreground">{t.role}, {t.company}</div>
                </div>
              </div>
            </m.div>
          ))}
        </m.div>
      </div>
    </section>
  );
}
