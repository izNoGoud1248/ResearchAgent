import { type FormEvent, useState } from "react";
import { type ApiClient, ApiError } from "../api/apiClient";
import type { FollowUpAnswer } from "../api/types";
import { MarkdownView } from "./MarkdownView";

interface Exchange {
  question: string;
  result: FollowUpAnswer;
}

export function FollowUpBox({ client, runId }: { client: ApiClient; runId: string }) {
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);

  const ask = async (event: FormEvent) => {
    event.preventDefault();
    const asked = question.trim();
    if (!asked) return;
    setAsking(true);
    setError("");
    try {
      const result = await client.askFollowUp(runId, asked);
      setExchanges((previous) => [...previous, { question: asked, result }]);
      setQuestion("");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not get an answer.");
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="followUp">
      <h3>Ask a follow-up</h3>
      <p className="muted">Answered from the full text of the papers this report cites, section by section.</p>
      {exchanges.map((exchange, index) => (
        <div key={index} className="exchange">
          <p className="exchangeQuestion">{exchange.question}</p>
          <MarkdownView markdown={exchange.result.answer} />
          {exchange.result.sources.length > 0 && (
            <details className="sources">
              <summary>
                {exchange.result.sources.length} passages from {exchange.result.papersWithFullText} papers read in full
              </summary>
              <ul>
                {exchange.result.sources.map((source, sourceIndex) => (
                  <li key={sourceIndex}>
                    <a className="citation" href={`https://arxiv.org/abs/${source.paperId}`} target="_blank" rel="noreferrer noopener">
                      arXiv:{source.paperId} · {source.section}
                    </a>{" "}
                    <span className="muted">
                      {source.title} · matched by {source.matchedBy.join(" and ")}
                    </span>
                    <blockquote>{source.excerpt}…</blockquote>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {(exchange.result.ungroundedCitations?.length ?? 0) > 0 && (
            <p className="alert">This answer cites papers it was not given: {exchange.result.ungroundedCitations?.join(", ")}</p>
          )}
        </div>
      ))}
      <form className="followUpForm" onSubmit={(event) => void ask(event)}>
        <input
          value={question}
          maxLength={1000}
          placeholder="e.g. Which of these methods work without retraining the model?"
          onChange={(event) => setQuestion(event.target.value)}
        />
        <button className="primary" type="submit" disabled={asking || !question.trim()}>
          {asking ? "Reading papers..." : "Ask"}
        </button>
      </form>
      {error && <p className="errorText">{error}</p>}
    </div>
  );
}
