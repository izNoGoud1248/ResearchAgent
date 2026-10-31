import { type FormEvent, useState } from "react";
import { type ApiClient, ApiError } from "../api/apiClient";
import { HashRouter } from "../routing";

const pipeline = ["plan", "research x N", "fact-check · A2A", "write", "critique", "approve", "save · MCP"];

const examples = [
  "What are the latest approaches to prompt injection defense?",
  "How are LLM agents evaluated on multi-step tool use?",
  "What methods reduce hallucination in retrieval-augmented generation?",
];

export function AskPage({ client }: { client: ApiClient }) {
  const [question, setQuestion] = useState("");
  const [sensitive, setSensitive] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<{ title: string; detail: string } | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSending(true);
    setError(null);
    try {
      const { runId } = await client.ask(question, sensitive);
      HashRouter.go({ page: "run", runId });
    } catch (caught) {
      setError(AskErrors.explain(caught));
    } finally {
      setSending(false);
    }
  };

  return (
    <section className="askPage">
      <header className="hero">
        <span className="eyebrow">Multi-agent research</span>
        <h1>
          Ask anything. <span className="gradientText">The agents do the reading.</span>
        </h1>
        <p className="muted">
          A planner splits your question, researchers search arXiv in parallel, an independent fact-checker verifies the
          claims, and a writer and critic produce the brief.
        </p>
        <div className="pipeline" aria-label="Pipeline">
          {pipeline.map((step, index) => (
            <span key={step} className="pipelineGroup">
              {index > 0 && <span className="pipelineArrow"> → </span>}
              <span className="pipelineStep">{step}</span>
            </span>
          ))}
        </div>
      </header>
      <form className="card" onSubmit={(event) => void submit(event)}>
        <label className="field">
          <span>Question</span>
          <textarea rows={4} maxLength={2000} value={question} onChange={(event) => setQuestion(event.target.value)} />
        </label>
        <div className="examples">
          {examples.map((example) => (
            <button type="button" key={example} className="chip" onClick={() => setQuestion(example)}>
              {example}
            </button>
          ))}
        </div>
        <label className="toggle">
          <input type="checkbox" checked={sensitive} onChange={(event) => setSensitive(event.target.checked)} />
          <span>Sensitive: hold the report for human approval before it is saved</span>
        </label>
        {error && (
          <div className="alert">
            <strong>{error.title}</strong>
            <span>{error.detail}</span>
          </div>
        )}
        <button className="primary" type="submit" disabled={sending || !question.trim()}>
          {sending ? "Sending..." : "Start research"}
        </button>
      </form>
    </section>
  );
}

class AskErrors {
  static explain(caught: unknown): { title: string; detail: string } {
    if (!(caught instanceof ApiError)) return { title: "Could not reach the API", detail: "Check that the API service is running." };
    if (caught.status === 400) return { title: "Blocked by the input guard", detail: caught.detail };
    if (caught.status === 429) return { title: "Slow down", detail: `Rate limit reached. Try again in ${caught.retryAfter ?? 10} seconds.` };
    if (caught.status === 503) return { title: "System busy", detail: `The queue is full. Try again in ${caught.retryAfter ?? 30} seconds.` };
    return { title: `Request failed (${caught.status})`, detail: caught.detail };
  }
}
