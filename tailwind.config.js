/** Tailwind 3.4.17 — gerado OFFLINE por scripts/build_tailwind.py.
 *
 *  Nao ha build step no runtime nem no deploy: o CSS resultante e commitado
 *  em src/web/static/v4-tailwind.css e o CI faz `git diff --exit-code` pra
 *  impedir drift. Node so existe na maquina do dev e no runner do CI.
 *
 *  A versao esta fixada em 3.4.17 porque e exatamente a que o Play CDN
 *  servia ate 2026-08-11. Nao subir pra v4 (config CSS-first, quebra tudo).
 *
 *  As cores apontam pra var(--v4-*) de v4-tokens.css, que passa a ser a
 *  fonte unica — antes o hex vivia duplicado aqui e no CSS. Seguro porque
 *  nenhuma template usa opacity modifier (bg-v4-red/50), o unico caso em
 *  que var() sem <alpha-value> quebraria.
 */
module.exports = {
  content: ['./src/web/templates/**/*.html'],
  theme: {
    extend: {
      colors: {
        'v4-red': {
          DEFAULT: 'var(--v4-red)',
          medium: 'var(--v4-red-medium)',
          dark: 'var(--v4-red-dark)',
          soft: 'var(--v4-red-soft)',
        },
        'v4-gray': {
          50: 'var(--v4-gray-50)',
          100: 'var(--v4-gray-100)',
          200: 'var(--v4-gray-200)',
          300: 'var(--v4-gray-300)',
          500: 'var(--v4-gray-500)',
          700: 'var(--v4-gray-700)',
          800: 'var(--v4-gray-800)',
          900: 'var(--v4-gray-900)',
        },
        'v4-green': { DEFAULT: 'var(--v4-green)', soft: 'var(--v4-green-soft)' },
        'v4-gold': { DEFAULT: 'var(--v4-gold)', soft: 'var(--v4-gold-soft)' },
      },
      fontFamily: {
        sans: ['Montserrat', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Consolas', 'monospace'],
      },
      fontSize: {
        display: ['56px', { lineHeight: '1.0', letterSpacing: '-0.025em' }],
      },
      transitionTimingFunction: {
        'v4-out': 'cubic-bezier(0.2, 0.8, 0.2, 1)',
        'v4-spring': 'cubic-bezier(0.34, 1.56, 0.64, 1)',
      },
    },
  },
}
