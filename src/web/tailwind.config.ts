import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        "bg-base": "var(--bg-base)",
        "bg-surface": "var(--bg-surface)",
        "bg-elevated": "var(--bg-elevated)",
        "bg-deep": "var(--bg-deep)",
        border: "var(--border)",
        "border-faint": "var(--border-faint)",
        accent: "var(--accent)",
        "accent-dim": "var(--accent-dim)",
        "accent-ring": "var(--accent-ring)",
        alert: "var(--alert)",
        "alert-dim": "var(--alert-dim)",
        "alert-ring": "var(--alert-ring)",
        warn: "var(--warn)",
        "warn-dim": "var(--warn-dim)",
        "text-primary": "var(--text-primary)",
        "text-muted": "var(--text-muted)",
        "text-faint": "var(--text-faint)",
      },
      borderRadius: {
        control: "var(--r)",
        card: "var(--r-lg)",
        badge: "var(--r-sm)",
      },
      fontFamily: {
        sans: [
          "var(--font-jakarta)",
          "Plus Jakarta Sans",
          "system-ui",
          "sans-serif",
        ],
        mono: ["var(--font-mono)", "DM Mono", "Courier New", "monospace"],
      },
      spacing: {
        "sidebar-w": "var(--sidebar-w)",
        "topbar-h": "var(--topbar-h)",
      },
      fontSize: {
        "page-title": ["22px", { lineHeight: "1.3", fontWeight: "700" }],
        "section-heading": ["15px", { lineHeight: "1.4", fontWeight: "600" }],
        "body-default": ["13px", { lineHeight: "1.5", fontWeight: "400" }],
        "label-nav": [
          "11px",
          { lineHeight: "1.3", fontWeight: "500", letterSpacing: "0.07em" },
        ],
        "data-value": ["13px", { lineHeight: "1.4", fontWeight: "400" }],
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "slide-in-right": {
          from: { transform: "translateX(100%)" },
          to: { transform: "translateX(0)" },
        },
        "slide-out-right": {
          from: { transform: "translateX(0)" },
          to: { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-in": "fade-in 260ms ease",
        "slide-in-right": "slide-in-right 200ms ease",
        "slide-out-right": "slide-out-right 200ms ease",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
