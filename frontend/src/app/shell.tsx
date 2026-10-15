import { Outlet } from 'react-router';
import { Button } from '../components/ui/button';
import { useTheme } from '../lib/theme-context';

export function Shell() {
  const { theme, toggle } = useTheme();
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <span className="font-semibold">0-Ticket SOC</span>
        <Button variant="outline" onClick={toggle}>
          {theme === 'light' ? '다크 모드' : '라이트 모드'}
        </Button>
      </header>
      <main className="p-6">
        <Outlet />
      </main>
    </div>
  );
}
