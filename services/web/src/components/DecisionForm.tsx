import { useState } from "react";
import { type ApiClient, ApiError } from "../api/apiClient";
import type { ReviewAction } from "../api/types";

interface DecisionFormProps {
  client: ApiClient;
  runId: string;
  revisionsLeft: number;
  onDecided: (action: ReviewAction) => void;
}

export function DecisionForm({ client, runId, revisionsLeft, onDecided }: DecisionFormProps) {
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  const decide = async (action: ReviewAction) => {
    setSending(true);
    setError("");
    try {
      await client.decide(runId, action, note);
      onDecided(action);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not send the decision.");
    } finally {
      setSending(false);
    }
  };

  const canRevise = revisionsLeft > 0;

  return (
    <div className="decision">
      <label className="field">
        <span>{canRevise ? "Note for the writer or the record (required to request changes)" : "Note for the record (optional)"}</span>
        <textarea
          rows={3}
          value={note}
          maxLength={2000}
          placeholder={canRevise ? "e.g. Add a short section on limitations and cut the second paragraph." : ""}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      {error && <p className="errorText">{error}</p>}
      <div className="actions">
        <button className="primary" disabled={sending} onClick={() => void decide("approve")}>
          Approve and save
        </button>
        {canRevise && (
          <button
            className="secondary"
            disabled={sending || !note.trim()}
            title={note.trim() ? "Send the note to the writer, then review the new draft" : "Write what should change first"}
            onClick={() => void decide("revise")}
          >
            Request changes
            <span className="buttonHint">{revisionsLeft} left</span>
          </button>
        )}
        <button className="danger" disabled={sending} onClick={() => void decide("reject")}>
          Reject
        </button>
      </div>
      {!canRevise && <p className="muted">This report has used all its revision rounds. Approve or reject it.</p>}
    </div>
  );
}
