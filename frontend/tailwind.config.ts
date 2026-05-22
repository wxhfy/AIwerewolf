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
        primary: "#8B5A2B",
        primaryHover: "#A67C52",
        secondary: "#2E7D32",
        accent: "#D4AF37",
        background: "#F8F5F0",
        cardBackground: "#FAF7F2",
        border: "rgba(139,90,43,0.10)",
        textPrimary: "#2D2A24",
        textSecondary: "#5B564D",
        danger: "#B91C1C",
        success: "#2E7D32",
        warning: "#D4AF37",
        info: "#3B82F6",
        nightBackground: "#E8E2D8",
        nightCardBackground: "#EDE8E0",
        nightBorder: "rgba(139,90,43,0.15)",
        nightTextPrimary: "#1A1816",
        nightTextSecondary: "#4A4540",
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
    },
  },
  plugins: [],
  darkMode: "class",
};

export default config;
