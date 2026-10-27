import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert, Info, X } from "lucide-react";
import { cn } from "./utils";

// A tiny toast system. (Library toasts inject <style> tags, which the dashboard's
// Content-Security-Policy refuses; these use the app's own stylesheet.)
type Tone = "success" | "error" | "info";
interface Item {
  id: number;
  tone: Tone;
  title: string;
  description?: string;
}
let items: Item[] = [];
let next = 1;
const listeners = new Set<(items: Item[]) => void>();
const emit = () => listeners.forEach((listener) => listener(items));

function push(tone: Tone, title: string, description?: string) {
  const id = next++;
  items = [...items.slice(-3), { id, tone, title, description }];
  emit();
  window.setTimeout(() => dismiss(id), tone === "error" ? 8000 : 4500);
}
function dismiss(id: number) {
  items = items.filter((item) => item.id !== id);
  emit();
}

export const toast = {
  success: (title: string, description?: string) => push("success", title, description),
  error: (title: string, description?: string) => push("error", title, description),
  info: (title: string, description?: string) => push("info", title, description),
};

export function Toaster() {
  const [list, setList] = useState<Item[]>(items);
  useEffect(() => {
    listeners.add(setList);
    return () => {
      listeners.delete(setList);
    };
  }, []);
  return (
    <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[60] grid w-[min(24rem,calc(100vw-2rem))] gap-2">
      {list.map((item) => {
        const Icon = item.tone === "success" ? CheckCircle2 : item.tone === "error" ? CircleAlert : Info;
        return (
          <div
            key={item.id}
            role={item.tone === "error" ? "alert" : "status"}
            className="pointer-events-auto flex gap-3 rounded-lg border bg-popover p-3.5 text-popover-foreground shadow-lg animate-in fade-in-0 slide-in-from-bottom-2"
          >
            <Icon
              className={cn(
                "mt-0.5 size-4 shrink-0",
                item.tone === "success" && "text-success",
                item.tone === "error" && "text-destructive",
                item.tone === "info" && "text-primary",
              )}
            />
            <div className="min-w-0 flex-1 text-sm">
              <p className="font-medium">{item.title}</p>
              {item.description && <p className="mt-0.5 text-muted-foreground">{item.description}</p>}
            </div>
            <button className="rounded p-0.5 text-muted-foreground hover:bg-accent cursor-pointer" aria-label="Dismiss" onClick={() => dismiss(item.id)}>
              <X className="size-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
