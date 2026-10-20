import type { Config } from 'tailwindcss'
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: { extend: { colors: { slate: Object.fromEntries(
    [50,100,200,300,400,500,600,700,800,900,950].map(shade => [shade, `rgb(var(--slate-${shade}) / <alpha-value>)`])
  ) } } },
  plugins: [],
} satisfies Config
