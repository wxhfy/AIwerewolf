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
        border: "rgba(139,90,43,0.12)",
        textPrimary: "#2D2A24",
        textSecondary: "#5B564D",
        danger: "#EF4444",
        success: "#10B981",
        warning: "#F59E0B",
        info: "#3B82F6",
        nightBackground: "#0A0F1D",
        nightCardBackground: "rgba(15,23,42,0.9)",
        nightBorder: "rgba(255,255,255,0.08)",
        nightTextPrimary: "#E2E8F0",
        nightTextSecondary: "#94A3B8",
      },
      borderRadius: {
        card: "12px",
        button: "8px",
        badge: "14px",
      },
    },
  },
  plugins: [],
  darkMode: "class",
};

export default config;
