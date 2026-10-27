import React from "react";
import ReactDOM from "react-dom/client";
import "./fonts.css";
import "./index.css";
import { applyTheme, initialTheme } from "./lib/hooks";
import App from "./App";

applyTheme(initialTheme());

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
