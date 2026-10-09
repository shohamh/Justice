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
import { UnsavedChangesProvider } from "./contexts/UnsavedChangesContext";
import { ModalStackProvider } from "./contexts/ModalStackContext";
import { installChunkLoadRecovery } from "./chunkLoadRecovery";
import { installGlobalErrorReporting } from "./errorReporting";
import { shouldRetryQuery } from "./api/queryRetry";

installGlobalErrorReporting();
installChunkLoadRecovery();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: shouldRetryQuery },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ModalStackProvider>
          <UnsavedChangesProvider>
            <NavigationHistoryProvider>
              <AlgorithmSeenProvider>
                <App />
              </AlgorithmSeenProvider>
            </NavigationHistoryProvider>
          </UnsavedChangesProvider>
        </ModalStackProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
