import type { Config } from "tailwindcss";

// Every color is a token from src/styles/tokens.css. `colors` replaces Tailwind's palette
// instead of extending it, so `bg-red-500` and friends don't exist.
const token = (name: string) => `var(--${name})`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    colors: {
      transparent: "transparent",
      field: token("bg-field"),
      panel: token("bg-panel"),
      deep: token("bg-deep"),
      inset: token("bg-inset"),
      line: token("line"),
      "line-dashed": token("line-dashed"),
      bulb: token("bulb"),
      "bulb-dim": token("bulb-dim"),
      "bulb-dark": token("bulb-dark"),
      text: token("text"),
      muted: token("text-muted"),
      good: token("good"),
      bad: token("bad"),
      mid: token("mid"),
    },
    fontFamily: {
      sans: ['"Inter"', "system-ui", "sans-serif"],
      mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
    },
    fontWeight: { normal: "400", medium: "500" },
    fontSize: {
      label: ["11px", { lineHeight: "16px" }],
      meta: ["12px", { lineHeight: "18px" }],
      body: ["14px", { lineHeight: "1.6" }],
      team: ["15px", { lineHeight: "22px", letterSpacing: "0.5px" }],
      delta: ["17px", { lineHeight: "24px" }],
      card: ["17px", { lineHeight: "24px" }],
      stat: ["21px", { lineHeight: "28px" }],
      section: ["26px", { lineHeight: "32px" }],
      score: ["32px", { lineHeight: "36px" }],
      title: ["32px", { lineHeight: "38px", letterSpacing: "-0.5px" }],
    },
    borderRadius: { none: "0", control: "6px", card: "8px", full: "9999px" },
    extend: {
      letterSpacing: { label: "1.5px", wide: "2px", ticker: "1px" },
    },
  },
  plugins: [],
} satisfies Config;
