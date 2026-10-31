import { useEffect, useState } from "react";

export type Route =
  | { page: "ask" }
  | { page: "run"; runId: string }
  | { page: "approvals" }
  | { page: "history" }
  | { page: "ops" }
  | { page: "security" };

export class HashRouter {
  static parse(hash: string): Route {
    const parts = hash.replace(/^#\/?/, "").split("/");
    const [page, runId] = parts;
    if (page === "runs" && runId) return { page: "run", runId: decodeURIComponent(runId) };
    if (page === "approvals" || page === "history" || page === "ops" || page === "security") return { page };
    return { page: "ask" };
  }

  static href(route: Route): string {
    return route.page === "run" ? `#/runs/${encodeURIComponent(route.runId)}` : `#/${route.page}`;
  }

  static go(route: Route): void {
    window.location.hash = HashRouter.href(route);
  }
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => HashRouter.parse(window.location.hash));
  useEffect(() => {
    const update = () => setRoute(HashRouter.parse(window.location.hash));
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}
