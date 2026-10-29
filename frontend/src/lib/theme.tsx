import { useEffect, useState, type PropsWithChildren } from 'react';
import { ThemeContext } from './theme-context';

function initialTheme(): 'light' | 'dark' {
  try {
    const stored = localStorage.getItem('zero-ticket-theme');
    if (stored === 'dark' || stored === 'light') return stored;
  } catch {
    /* Storage can be disabled by browser policy. */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function ThemeProvider({ children }: PropsWithChildren) {
  const [theme, setTheme] = useState(initialTheme);
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    document.documentElement.style.colorScheme = theme;
    try {
      localStorage.setItem('zero-ticket-theme', theme);
    } catch {
      /* Theme still works without storage. */
    }
  }, [theme]);
  return (
    <ThemeContext.Provider
      value={{ theme, toggle: () => setTheme((value) => (value === 'light' ? 'dark' : 'light')) }}
    >
      {children}
    </ThemeContext.Provider>
  );
}
