import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          base: "#0B0D10",
          surface: "#12151A",
          elevated: "#1A1E24",
        },
        border: {
          subtle: "#242A32",
        },
        text: {
          primary: "#F2F4F7",
          secondary: "#B4BCC8",
          muted: "#7A8494",
        },
        accent: {
          DEFAULT: "#3DDC84",
          dim: "#2CA863",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains)", "ui-monospace", "monospace"],
      },
      spacing: {
        "0.5": "4px",
        "1": "8px",
        "2": "16px",
        "3": "24px",
        "4": "32px",
        "5": "40px",
        "6": "48px",
        "8": "64px",
        "10": "80px",
        "12": "96px",
        "16": "128px",
        "20": "160px",
        "24": "192px",
      },
      borderRadius: {
        sm: "4px",
        DEFAULT: "8px",
        lg: "12px",
        xl: "16px",
      },
      fontSize: {
        xs: ["12px", { lineHeight: "16px" }],
        sm: ["14px", { lineHeight: "20px" }],
        base: ["16px", { lineHeight: "24px" }],
        lg: ["18px", { lineHeight: "28px" }],
        xl: ["20px", { lineHeight: "28px" }],
        "2xl": ["24px", { lineHeight: "32px" }],
        "3xl": ["32px", { lineHeight: "40px" }],
        "4xl": ["40px", { lineHeight: "48px" }],
        "5xl": ["56px", { lineHeight: "64px" }],
        "6xl": ["72px", { lineHeight: "80px" }],
      },
      boxShadow: {
        subtle: "0 1px 2px rgba(0,0,0,0.3)",
        elevated: "0 8px 32px rgba(0,0,0,0.35)",
        glow: "0 0 40px rgba(61, 220, 132, 0.18)",
      },
      backgroundImage: {
        "grid-fade":
          "radial-gradient(circle at 50% 0%, rgba(61,220,132,0.08), transparent 60%)",
      },
    },
  },
  plugins: [],
};

export default config;
