import { useMemo, useState } from "react";
import { Toaster } from "@/lib/toast";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import {
  Bot,
  CalendarClock,
  ChartCandlestick,
  FlaskConical,
  LayoutDashboard,
  Menu,
  Monitor,
  Moon,
  Settings2,
  Sun,
  Wrench,
} from "lucide-react";
import { get } from "@/lib/api";
import { DataContext } from "@/lib/context";
import { marketPhase, usePoll, useNow, useRoute, useTheme, type Theme } from "@/lib/hooks";
import type { DashboardState, SetupStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Tip, TooltipProvider } from "@/components/ui/misc";
import { Mascot } from "@/mascots/Mascot";
import { TodayPage } from "@/pages/Today";
import { DeskPage } from "@/pages/Desk";
import { ReplayPage } from "@/pages/Replay";
import { ResearchPage } from "@/pages/Research";
import { AgentsPage } from "@/pages/Agents";
import { SetupPage } from "@/pages/Setup";
import { SettingsPage } from "@/pages/Settings";

const NAV = [
  { id: "today", label: "Today", icon: LayoutDashboard },
  { id: "desk", label: "Pre-market desk", icon: CalendarClock },
  { id: "replay", label: "Paper replay", icon: ChartCandlestick },
  { id: "research", label: "Research", icon: FlaskConical },
  { id: "agents", label: "Agents", icon: Bot },
  { id: "setup", label: "Setup", icon: Wrench },
  { id: "settings", label: "Settings", icon: Settings2 },
] as const;

function Brand() {
  return (
    <a href="#/today" className="flex items-center gap-2.5 px-2 py-1">
      <span className="grid size-9 place-items-center rounded-lg bg-primary text-primary-foreground">
        <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M4 17l5-6 4 4 7-9" />
          <path d="M15 6h5v5" />
        </svg>
      </span>
      <span className="leading-tight">
        <span className="block text-[15px] font-semibold tracking-tight">India Trade Lab</span>
        <span className="block text-xs text-muted-foreground">Paper research desk</span>
      </span>
    </a>
  );
}

function NavList({ route, setupLeft, onPick }: { route: string; setupLeft: number; onPick?: () => void }) {
  return (
    <nav aria-label="Main" className="grid gap-0.5">
      {NAV.map((item) => {
        const active = route === item.id;
        const Icon = item.icon;
        return (
          <a
            key={item.id}
            href={`#/${item.id}`}
            onClick={onPick}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
              active ? "bg-accent text-accent-foreground" : "text-sidebar-foreground/80 hover:bg-accent/60 hover:text-foreground",
            )}
          >
            <Icon className="size-4" aria-hidden />
            <span className="flex-1">{item.label}</span>
            {item.id === "setup" && setupLeft > 0 && (
              <Badge variant="solid" className="px-1.5 py-0 text-[11px]">
                {setupLeft}
              </Badge>
            )}
          </a>
        );
      })}
    </nav>
  );
}

function ThemeToggle({ theme, setTheme }: { theme: Theme; setTheme: (theme: Theme) => void }) {
  const next: Record<Theme, Theme> = { light: "dark", dark: "system", system: "light" };
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;
  const label = { light: "Light theme", dark: "Dark theme", system: "Match system theme" }[theme];
  return (
    <Tip label={`${label}. Click to change.`}>
      <Button variant="ghost" size="icon" aria-label={label} onClick={() => setTheme(next[theme])}>
        <Icon />
      </Button>
    </Tip>
  );
}

export default function App() {
  const [route] = useRoute();
  const { theme, setTheme } = useTheme();
  const now = useNow();
  const [menu, setMenu] = useState(false);
  const stateQuery = usePoll(() => get<DashboardState>("/api/state"), 2000);
  const setupQuery = usePoll(() => get<SetupStatus>("/api/setup/status"), 6000);
  const phase = marketPhase(now);
  const setupLeft = setupQuery.data ? setupQuery.data.steps.filter((step) => !step.done).length : 0;
  const offline = Boolean(stateQuery.error && !stateQuery.data);

  const value = useMemo(
    () => ({
      state: stateQuery.data,
      setup: setupQuery.data,
      refreshState: stateQuery.refresh,
      refreshSetup: setupQuery.refresh,
      offline,
    }),
    [stateQuery.data, setupQuery.data, stateQuery.refresh, setupQuery.refresh, offline],
  );

  const page = {
    today: <TodayPage />,
    desk: <DeskPage />,
    replay: <ReplayPage />,
    research: <ResearchPage />,
    agents: <AgentsPage />,
    setup: <SetupPage />,
    settings: <SettingsPage />,
  }[route] ?? <TodayPage />;
  const title = NAV.find((item) => item.id === route)?.label ?? "Today";

  return (
    <DataContext.Provider value={value}>
      <TooltipProvider>
        <div className="flex min-h-dvh">
          <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col gap-6 border-r bg-sidebar p-4 lg:flex">
            <Brand />
            <NavList route={route} setupLeft={setupLeft} />
            <div className="mt-auto rounded-lg border bg-card p-3">
              <div className="flex items-center gap-3">
                <Mascot kind="pilot" size={52} mood={offline ? "alert" : "idle"} />
                <div className="text-sm">
                  <p className="font-medium">Paper only</p>
                  <p className="text-xs text-muted-foreground">No real orders can be placed from here.</p>
                </div>
              </div>
            </div>
          </aside>
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b bg-background/85 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/70 sm:px-6">
              <Dialog open={menu} onOpenChange={setMenu}>
                <DialogTrigger asChild>
                  <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open menu">
                    <Menu />
                  </Button>
                </DialogTrigger>
                <DialogContent side="right" className="max-w-xs bg-sidebar">
                  <DialogTitle className="sr-only">Menu</DialogTitle>
                  <div className="grid gap-6">
                    <Brand />
                    <NavList route={route} setupLeft={setupLeft} onPick={() => setMenu(false)} />
                  </div>
                </DialogContent>
              </Dialog>
              <h1 className="truncate text-lg font-semibold tracking-tight">{title}</h1>
              <div className="ml-auto flex items-center gap-2">
                <Badge variant={phase.tone} className="hidden sm:inline-flex">
                  <span className={cn("size-1.5 rounded-full bg-current", phase.tone === "success" && "animate-pulse-dot")} />
                  {phase.label}
                </Badge>
                <span className="num hidden text-sm text-muted-foreground md:inline">
                  {now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" })} IST
                </span>
                <Badge variant="outline" className="hidden sm:inline-flex">
                  Paper only
                </Badge>
                <ThemeToggle theme={theme} setTheme={setTheme} />
              </div>
            </header>
            {offline && (
              <div role="alert" className="border-b bg-destructive/10 px-6 py-2 text-sm text-destructive">
                The dashboard server is not answering. Start it with <code className="font-mono">python3 scripts/observatory.py</code>, or reopen your SSH tunnel.
              </div>
            )}
            <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:py-8">
              <ErrorBoundary resetKey={route}>{page}</ErrorBoundary>
            </main>
          </div>
        </div>
        <Toaster />
      </TooltipProvider>
    </DataContext.Provider>
  );
}
