import { createContext, useContext } from 'react';

export const ThemeContext = createContext<{ theme: 'light' | 'dark'; toggle: () => void } | null>(
  null,
);
export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error('ThemeProvider is required');
  return context;
}
