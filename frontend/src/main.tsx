import './i18n';
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { Toaster } from "sonner";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { router } from "./router";
import { initSpotlight } from "./lib/spotlight";
// Self-hosted fonts (VT-006): vendor the woff2 files locally instead of the
// Google Fonts CDN. Weights match tailwind.config.ts (Inter 300/400/500/600/700,
// JetBrains Mono 400/500/700). 300 carries the display voice — without the real
// weight the browser would synthesise it and the headlines lose their thinness.
import "@fontsource/inter/300.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/700.css";
import "highlight.js/styles/github-dark-dimmed.min.css";
import "./index.css";

initSpotlight();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <RouterProvider router={router} />
      <Toaster position="bottom-right" richColors closeButton duration={3500} />
    </ErrorBoundary>
  </StrictMode>
);
