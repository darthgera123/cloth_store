import { Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import "./app.css";
import { DisplayApp } from "./display/DisplayApp";

/* The host bundle carries the question bank and game engine; the audience
   never downloads it. */
// Route-level split: the audience display must not download the host bundle.
const HostApp = lazy(() => import("./host/HostApp").then((module) => ({ default: module.HostApp })));
const JoinApp = lazy(() => import("./join/JoinApp").then((module) => ({ default: module.JoinApp })));

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root");

function resolveRoute(): "host" | "display" | "join" {
  const hash = window.location.hash.replace(/^#/, "");
  if (hash.startsWith("/host")) return "host";
  if (hash.startsWith("/join")) return "join";
  if (hash.startsWith("/display")) return "display";
  const path = window.location.pathname.replace(/\/+$/, "");
  if (path.endsWith("/host")) return "host";
  if (path.endsWith("/join")) return "join";
  return "display";
}

const route = resolveRoute();

window.addEventListener("hashchange", () => {
  if (resolveRoute() !== route) window.location.reload();
});

createRoot(root).render(
  route === "display" ? (
    <DisplayApp />
  ) : (
    <Suspense fallback={<div className="grid min-h-screen place-items-center bg-lavender" />}>
      {route === "host" ? <HostApp /> : <JoinApp />}
    </Suspense>
  ),
);
