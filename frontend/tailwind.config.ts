import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Colors reference CSS custom properties so Tailwind classes
        // automatically track day↔night variable changes in globals.css.
        // RGB-channel variables (--color-*-rgb) use space-separated format
        // so Tailwind's /opacity syntax (bg-primary/10) continues to work.
        primary: "rgb(var(--color-primary-rgb) / <alpha-value>)",
        primaryHover: "var(--color-primary-hover)",
        secondary: "rgb(var(--color-village-rgb) / <alpha-value>)",
        accent: "rgb(var(--color-gold-rgb) / <alpha-value>)",
        background: "var(--color-bg)",
        cardBackground: "var(--color-card)",
        border: "var(--color-border)",
        textPrimary: "rgb(var(--color-text-rgb) / <alpha-value>)",
        textSecondary: "rgb(var(--color-text-sub-rgb) / <alpha-value>)",
        "text-sub": "rgb(var(--color-text-sub-rgb) / <alpha-value>)",
        danger: "rgb(var(--color-danger-rgb) / <alpha-value>)",
        success: "rgb(var(--color-village-rgb) / <alpha-value>)",
        warning: "rgb(var(--color-gold-rgb) / <alpha-value>)",
        info: "rgb(var(--color-info-rgb) / <alpha-value>)",
      },
      boxShadow: {
        card: "0 4px 24px rgb(0 0 0 / 0.05)",
        modal: "0 16px 48px rgb(0 0 0 / 0.12)",
        float: "0 4px 24px rgb(0 0 0 / 0.12)",
        "float-hover": "0 6px 32px rgb(0 0 0 / 0.16)",
        "modal-strong": "0 16px 64px rgb(0 0 0 / 0.25)",
        accent: "0 0 16px rgb(var(--color-gold-rgb) / 0.25)",
      },
      backgroundImage: {
        "night-overlay": "radial-gradient(ellipse at 50% 0%, rgb(25 25 35 / 0.25) 0%, rgb(0 0 0 / 0.55) 100%)",
      },
      borderRadius: {
        card: "12px",
        button: "8px",
        badge: "14px",
      },
      fontFamily: {
        display: ['"Noto Serif SC"', "serif"],
        body: ['"Noto Sans SC"', "-apple-system", "BlinkMacSystemFont", "sans-serif"],
      },
      animation: {
        "dot-1": "dotPulse 1.4s ease-in-out infinite",
        "dot-2": "dotPulse 1.4s ease-in-out 0.2s infinite",
        "dot-3": "dotPulse 1.4s ease-in-out 0.4s infinite",
      },
      keyframes: {
        dotPulse: {
          "0%, 80%, 100%": { opacity: "0.2" },
          "40%": { opacity: "1" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
