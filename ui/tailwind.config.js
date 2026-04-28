import animate from 'tailwindcss-animate';

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Helvetica Neue', 'Arial', 'sans-serif'],
        mono: ['JetBrains Mono', 'Cascadia Mono', 'Consolas', 'Menlo', 'monospace'],
      },
      colors: {
        // Mirror CSS vars from index.css so utilities like `bg-surface` work.
        base:       'var(--bg-base)',
        surface:    'var(--bg-surface)',
        elevated:   'var(--bg-elevated)',
        higher:     'var(--bg-higher)',
        line:       'var(--border)',
        'line-strong': 'var(--border-strong)',
        'line-hover': 'var(--border-hover)',
        ink:        'var(--text)',
        muted:      'var(--text-muted)',
        faint:      'var(--text-faint)',
        accent:     'var(--accent)',
        'accent-hover': 'var(--accent-hover)',
        success:    'var(--success)',
        warning:    'var(--warning)',
        danger:     'var(--danger)',
        // kind-* tokens for event categorisation
        'kind-file':     'var(--kind-file)',
        'kind-registry': 'var(--kind-registry)',
        'kind-process':  'var(--kind-process)',
        'kind-network':  'var(--kind-network)',
        'kind-custom':   'var(--kind-custom)',
      },
      borderRadius: {
        DEFAULT: 'var(--radius)',
        sm: 'var(--radius-sm)',
        lg: 'var(--radius-lg)',
      },
      boxShadow: {
        sm: 'var(--shadow-sm)',
        md: 'var(--shadow-md)',
        lg: 'var(--shadow-lg)',
      },
      transitionTimingFunction: {
        smooth: 'cubic-bezier(0.4, 0, 0.2, 1)',
      },
    },
  },
  plugins: [animate],
};
