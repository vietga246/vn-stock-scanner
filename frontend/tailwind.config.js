/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-space-grotesk)', 'system-ui', 'sans-serif'],
      },
      colors: {
        background: '#05080a',
        foreground: '#e8edf2',
        primary: '#00d4ff',
        secondary: '#a855f7',
        success: '#00ff88',
        danger: '#ff3366',
        warning: '#ffcc00',
        muted: '#4a5a6a',
        border: '#1e2832',
        card: '#0a0f14',
        'card-hover': '#0f1519',
      },
    },
  },
  plugins: [],
};
