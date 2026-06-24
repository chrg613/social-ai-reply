"use client";

import Link from "next/link";

const footerLinks: Record<string, { label: string; href: string; placeholder?: boolean }[]> = {
  Product: [
    { label: "Features", href: "/#features" },
    { label: "Pricing", href: "/#pricing" },
    { label: "Changelog", href: "#", placeholder: true },
    { label: "Documentation", href: "#", placeholder: true },
  ],
  Company: [
    { label: "About", href: "#", placeholder: true },
    { label: "Blog", href: "#", placeholder: true },
    { label: "Careers", href: "#", placeholder: true },
    { label: "Contact", href: "#", placeholder: true },
  ],
  Legal: [
    { label: "Privacy Policy", href: "#", placeholder: true },
    { label: "Terms of Service", href: "#", placeholder: true },
    { label: "Cookie Policy", href: "#", placeholder: true },
  ],
};

export function Footer() {
  return (
    <footer className="border-t border-border py-12">
      <div className="mx-auto max-w-7xl px-6">
        <div className="grid gap-8 md:grid-cols-4">
          <div>
            <div className="text-lg font-bold tracking-tight text-foreground">
              SignalFlow
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              AI visibility and community engagement for modern brands.
            </p>
          </div>

          {Object.entries(footerLinks).map(([title, links]) => (
            <div key={title}>
              <div className="mb-3 text-sm font-semibold text-foreground">
                {title}
              </div>
              <ul className="space-y-2">
                {links.map((link) =>
                  link.placeholder ? (
                    <li key={link.label}>
                      <a
                        href="#"
                        aria-disabled="true"
                        className="text-sm text-muted-foreground/50 cursor-not-allowed pointer-events-none"
                        tabIndex={-1}
                      >
                        {link.label}
                      </a>
                    </li>
                  ) : (
                    <li key={link.label}>
                      <Link
                        href={link.href}
                        className="text-sm transition-colors duration-200 text-muted-foreground hover:text-primary"
                      >
                        {link.label}
                      </Link>
                    </li>
                  )
                )}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col items-center justify-between gap-4 border-t border-border pt-8 md:flex-row">
          <p className="text-xs text-muted-foreground">
            &copy; {new Date().getFullYear()} SignalFlow. All rights reserved.
          </p>
          <div className="flex gap-4">
            {["Twitter", "LinkedIn", "Reddit"].map((social) => (
              <a
                key={social}
                href="#"
                aria-disabled="true"
                className="text-xs text-muted-foreground/50 cursor-not-allowed pointer-events-none"
                tabIndex={-1}
              >
                {social}
              </a>
            ))}
          </div>
        </div>
      </div>
    </footer>
  );
}
