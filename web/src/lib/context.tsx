import { createContext, useContext } from "react";
import type { DashboardState, SetupStatus } from "./types";

export interface AppData {
  state: DashboardState | null;
  setup: SetupStatus | null;
  refreshState: () => Promise<void>;
  refreshSetup: () => Promise<void>;
  offline: boolean;
}

export const DataContext = createContext<AppData>({
  state: null,
  setup: null,
  refreshState: async () => {},
  refreshSetup: async () => {},
  offline: false,
});

export const useData = () => useContext(DataContext);
