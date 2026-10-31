import { useState } from "react";
import { type ApiClient, ApiError } from "../api/apiClient";
import type { ClarifyingQuestion } from "../api/types";

interface ClarifyFormProps {
  client: ApiClient;
  runId: string;
  question: ClarifyingQuestion;
  onAnswered: () => void;
}

export function ClarifyForm({ client, runId, question, onAnswered }: ClarifyFormProps) {
  const [answer, setAnswer] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  const send = async (text: string) => {
    setSending(true);
    setError("");
    try {
      await client.clarify(runId, text);
      onAnswered();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not send the answer.");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="decision">
      <p>{question.question}</p>
      {(question.options ?? []).length > 0 && (
        <div className="clarifyOptions">
          {(question.options ?? []).map((option) => (
            <button key={option} className="secondary" disabled={sending} onClick={() => void send(option)}>
              {option}
            </button>
          ))}
        </div>
      )}
      <label className="field">
        <span>Or answer in your own words</span>
        <input value={answer} maxLength={500} onChange={(event) => setAnswer(event.target.value)} />
      </label>
      {error && <p className="errorText">{error}</p>}
      <div className="actions">
        <button className="primary" disabled={sending || !answer.trim()} onClick={() => void send(answer.trim())}>
          Send answer
        </button>
        <button className="secondary" disabled={sending} onClick={() => void send("use your best judgement")}>
          Use your best judgement
        </button>
      </div>
    </div>
  );
}
