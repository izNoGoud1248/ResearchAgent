import { useEffect, useMemo, useState } from "react";
import { ApiClient, ApiError } from "./api/apiClient";
import type { Role } from "./api/types";
import { KeyForm } from "./components/KeyForm";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { AskPage } from "./pages/AskPage";
import { HistoryPage } from "./pages/HistoryPage";
import { LiveRunPage } from "./pages/LiveRunPage";
import { OpsPage } from "./pages/OpsPage";
import { SecurityPage } from "./pages/SecurityPage";
import { HashRouter, type Route, useRoute } from "./routing";

const navigation: { route: Route; label: string; approverOnly?: boolean }[] = [
  { route: { page: "ask" }, label: "Ask" },
  { route: { page: "approvals" }, label: "Approvals", approverOnly: true },
  { route: { page: "history" }, label: "History" },
  { route: { page: "ops" }, label: "Ops" },
  { route: { page: "security" }, label: "Security" },
];

export function App() {
  const client = useMemo(() => new ApiClient(), []);
  const [role, setRole] = useState<Role | null>(null);
  const [checking, setChecking] = useState(true);
  const [keyError, setKeyError] = useState("");
  const route = useRoute();

  // An existing session cookie signs the user straight in.
  useEffect(() => {
    client
      .role()
      .then(setRole)
      .catch((error: unknown) => {
        if (!(error instanceof ApiError && error.status === 401)) setKeyError("Could not reach the API.");
      })
      .finally(() => setChecking(false));
  }, [client]);

  const signIn = (key: string) => {
    setChecking(true);
    setKeyError("");
    client
      .signIn(key)
      .then(setRole)
      .catch((error: unknown) => {
        setKeyError(error instanceof ApiError && error.status === 401 ? "That key was not accepted." : "Could not reach the API.");
      })
      .finally(() => setChecking(false));
  };

  const signOut = () => {
    void client.signOut().finally(() => setRole(null));
  };

  if (!role) {
    return <KeyForm onSubmit={signIn} error={keyError} checking={checking} />;
  }

  return (
    <div className="shell">
      <header className="topBar">
        <a className="brand" href={HashRouter.href({ page: "ask" })}>
          <span className="brandMark" aria-hidden="true" />
          ResearchDesk
          <span className="brandTag">agents</span>
        </a>
        <nav className="nav">
          {navigation
            .filter((item) => !item.approverOnly || role === "approver")
            .map((item) => (
              <a
                key={item.label}
                href={HashRouter.href(item.route)}
                className={route.page === item.route.page ? "navLink active" : "navLink"}
              >
                {item.label}
              </a>
            ))}
        </nav>
        <div className="who">
          <span className="liveDot" title="Connected to the API" />
          <span className="roleBadge">{role}</span>
          <button className="linkButton" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <main className="page">
        {route.page === "ask" && <AskPage client={client} />}
        {route.page === "run" && <LiveRunPage key={route.runId} client={client} runId={route.runId} role={role} />}
        {route.page === "approvals" && <ApprovalsPage client={client} role={role} />}
        {route.page === "history" && <HistoryPage client={client} />}
        {route.page === "ops" && <OpsPage client={client} />}
        {route.page === "security" && <SecurityPage client={client} />}
      </main>
    </div>
  );
}
