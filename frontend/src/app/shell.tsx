import { useEffect, useRef } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router';
import { Icon, type IconName } from '../components/icon';
import { Button } from '../components/ui/button';
import { useTheme } from '../lib/theme-context';
import { cn } from '../lib/utils';

const menu: { to: string; label: string; icon: IconName }[] = [
  { to: '/', label: '대시보드', icon: 'dashboard' },
  { to: '/review', label: 'L1 결과', icon: 'inbox' },
  { to: '/tickets', label: '전체 티켓', icon: 'ticket' },
  { to: '/incidents', label: 'Incident', icon: 'incident' },
  { to: '/cases', label: 'Case', icon: 'case' },
  { to: '/hunts', label: '헌팅', icon: 'hunt' },
  { to: '/rules', label: '룰 제안', icon: 'rule' },
];

// On narrow screens the menu is a horizontal strip that can overflow. Bring a link fully into
// the strip by moving only its horizontal scroll, never the page. A no-op in the vertical sidebar.
function reveal(nav: HTMLElement | null, link: Element | null | undefined) {
  if (!nav || !link) return;
  const outer = nav.getBoundingClientRect();
  const inner = link.getBoundingClientRect();
  if (inner.left < outer.left) nav.scrollLeft -= outer.left - inner.left + 10;
  else if (inner.right > outer.right) nav.scrollLeft += inner.right - outer.right + 10;
}

export function Shell() {
  const { theme, toggle } = useTheme();
  const nav = useRef<HTMLElement>(null);
  const { pathname } = useLocation();
  useEffect(() => {
    reveal(nav.current, nav.current?.querySelector('[aria-current="page"]'));
  }, [pathname]);
  return (
    <div className="min-h-screen bg-background font-sans text-sm text-foreground md:grid md:grid-cols-[224px_minmax(0,1fr)]">
      <aside className="relative z-10 flex flex-col bg-sidebar text-sidebar-foreground md:sticky md:top-0 md:h-screen">
        <div className="flex h-14 items-center gap-2.5 border-b border-white/10 px-4 md:h-16">
          <span className="grid size-8 place-items-center rounded-md bg-[#356fd1] text-white shadow-[inset_0_0_0_1px_rgb(255_255_255/14%)]">
            <Icon name="shield" size={18} />
          </span>
          <span className="flex flex-col leading-tight">
            <span className="text-[15px] font-semibold">0-Ticket SOC</span>
            <span className="text-[10px] tracking-[0.17em] text-sidebar-muted">SOC CONSOLE</span>
          </span>
        </div>
        <nav
          ref={nav}
          aria-label="주 메뉴"
          className="flex gap-1 overflow-x-auto px-2.5 py-2 md:flex-1 md:flex-col md:py-4"
        >
          <p
            aria-hidden="true"
            className="hidden px-2.5 pb-2 text-[10px] font-bold tracking-[0.16em] text-sidebar-muted md:block"
          >
            OPERATIONS
          </p>
          {menu.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              onFocus={(event) => reveal(nav.current, event.currentTarget)}
              className={({ isActive }) =>
                cn(
                  'flex h-9 shrink-0 items-center gap-2.5 rounded-md px-2.5 font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                  isActive
                    ? 'bg-sidebar-active text-white shadow-[inset_2px_0_var(--ring)]'
                    : 'text-sidebar-muted hover:bg-white/5 hover:text-sidebar-foreground',
                )
              }
            >
              <Icon name={item.icon} />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="absolute top-3 right-3 md:static md:border-t md:border-white/10 md:p-2.5">
          <Button
            variant="ghost"
            size="sm"
            className="text-sidebar-muted hover:bg-white/5 hover:text-sidebar-foreground md:h-9 md:w-full md:justify-start md:text-sm"
            onClick={toggle}
          >
            <Icon name={theme === 'light' ? 'moon' : 'sun'} />
            {theme === 'light' ? '다크 모드' : '라이트 모드'}
          </Button>
        </div>
      </aside>
      <main className="min-w-0">
        <div className="mx-auto w-full max-w-[1600px] px-4 pt-6 pb-12 md:px-7">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
