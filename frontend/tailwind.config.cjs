module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Heebo", "Arial", "sans-serif"],
        cinzel: ["Cinzel", "serif"],
      },
      colors: {
        approved: "#16a34a",
        pending: "#d97706",
        rejected: "#dc2626",
        cancelled: "#6b7280",
      },
    },
  },
  plugins: [require("tailwindcss-rtl")],
};
