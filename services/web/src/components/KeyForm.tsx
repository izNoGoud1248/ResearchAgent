import { type FormEvent, useState } from "react";

interface KeyFormProps {
  onSubmit: (apiKey: string) => void;
  error: string;
  checking: boolean;
}

export function KeyForm({ onSubmit, error, checking }: KeyFormProps) {
  const [apiKey, setApiKey] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (apiKey.trim()) onSubmit(apiKey.trim());
  };

  return (
    <div className="center">
      <form className="card keyForm" onSubmit={submit}>
        <span className="brand">
          <span className="brandMark" aria-hidden="true" />
          ResearchDesk
        </span>
        <div>
          <h1>
            Research with an <span className="gradientText">agent team</span>
          </h1>
          <p className="muted">
            Enter your API key. USER_API_KEY asks questions; APPROVER_API_KEY can also approve sensitive reports.
          </p>
        </div>
        <label className="field">
          <span>API key</span>
          <input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} />
        </label>
        {error && <p className="errorText">{error}</p>}
        <button className="primary" type="submit" disabled={checking || !apiKey.trim()}>
          {checking ? "Checking..." : "Continue"}
        </button>
      </form>
    </div>
  );
}
