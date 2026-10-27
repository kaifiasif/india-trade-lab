import { Component, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Mascot } from "@/mascots/Mascot";

/** Keeps one broken page from blanking the whole dashboard. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidUpdate(previous: { resetKey: string }) {
    if (previous.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex flex-col items-center gap-4 rounded-xl border bg-card p-10 text-center">
        <Mascot kind="scout" size={88} mood="alert" />
        <div>
          <p className="font-semibold">This page hit a problem</p>
          <p className="mt-1 max-w-md text-sm text-muted-foreground">Your data is safe; nothing was changed. Reload, and if it happens again, check the server log.</p>
          <p className="mt-2 font-mono text-xs text-muted-foreground">{this.state.error.message}</p>
        </div>
        <Button variant="outline" onClick={() => window.location.reload()}>
          Reload
        </Button>
      </div>
    );
  }
}
