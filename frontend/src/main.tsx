import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import "./i18n";
import "./styles/globals.css";
import "katex/dist/katex.min.css";
import { AlgorithmSeenProvider } from "./contexts/AlgorithmSeenContext";
import { NavigationHistoryProvider } from "./hooks/useNavigationHistory";
import { installGlobalErrorReporting } from "./errorReporting";

installGlobalErrorReporting();

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <NavigationHistoryProvider>
          <AlgorithmSeenProvider>
            <App />
          </AlgorithmSeenProvider>
        </NavigationHistoryProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
