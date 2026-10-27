import { useCallback, useEffect, useRef, useState } from "react";

export function usePoll<T>(fetcher: () => Promise<T>, intervalMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const saved = useRef(fetcher);
  saved.current = fetcher;
  const refresh = useCallback(async () => {
    try {
      setData(await saved.current());
      setError(null);
    } catch (caught) {
      setError(caught as Error);
    }
  }, []);
  useEffect(() => {
    refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs, refresh]);
  return { data, error, refresh };
}

const read = (key: string) => {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
};
const write = (key: string, value: string) => {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* Private windows may refuse storage; the theme still works for this visit. */
  }
};

export type Theme = "light" | "dark" | "system";

export function applyTheme(theme: Theme) {
  const dark =
    theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

export function initialTheme(): Theme {
  const stored = read("itl-theme");
  return stored === "light" || stored === "dark" || stored === "system" ? stored : "system";
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  useEffect(() => {
    applyTheme(theme);
    write("itl-theme", theme);
    if (theme !== "system") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const follow = () => applyTheme("system");
    query.addEventListener("change", follow);
    return () => query.removeEventListener("change", follow);
  }, [theme]);
  return { theme, setTheme };
}

export function useRoute(): [string, URLSearchParams] {
  const parse = () => {
    const raw = window.location.hash.replace(/^#\/?/, "");
    const [path, query = ""] = raw.split("?");
    return [path || "today", new URLSearchParams(query)] as [string, URLSearchParams];
  };
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const update = () => setRoute(parse());
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}

export function useNow(ms = 30_000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), ms);
    return () => window.clearInterval(timer);
  }, [ms]);
  return now;
}

/** The NSE session phase in IST, from the clock alone (holidays come from the server's calendar). */
export function marketPhase(now: Date): { label: string; tone: "success" | "warning" | "outline" } {
  const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  const day = ist.getDay();
  const minutes = ist.getHours() * 60 + ist.getMinutes();
  if (day === 0 || day === 6) return { label: "Weekend", tone: "outline" };
  if (minutes < 9 * 60) return { label: "Before pre-open", tone: "outline" };
  if (minutes < 9 * 60 + 15) return { label: "Pre-open", tone: "warning" };
  if (minutes < 15 * 60 + 30) return { label: "Market open", tone: "success" };
  return { label: "Market closed", tone: "outline" };
}
