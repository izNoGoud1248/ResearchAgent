import type { ApiClient } from "./apiClient";
import type { RunEvent } from "./types";

export class SseParser {
  private buffer = "";

  feed(chunk: string): RunEvent[] {
    this.buffer += chunk.replace(/\r\n/g, "\n");
    const events: RunEvent[] = [];
    let boundary = this.buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const event = this.parseBlock(this.buffer.slice(0, boundary));
      this.buffer = this.buffer.slice(boundary + 2);
      if (event) {
        events.push(event);
      }
      boundary = this.buffer.indexOf("\n\n");
    }
    return events;
  }

  private parseBlock(block: string): RunEvent | null {
    let id = "";
    let kind = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      const colon = line.indexOf(":");
      if (colon <= 0) {
        continue; // comments (keep-alive pings) and malformed lines
      }
      const field = line.slice(0, colon);
      const value = line.slice(colon + 1).replace(/^ /, "");
      if (field === "id") id = value;
      else if (field === "event") kind = value;
      else if (field === "data") dataLines.push(value);
    }
    if (!id || dataLines.length === 0) {
      return null;
    }
    return { id, kind, data: JSON.parse(dataLines.join("\n")) as Record<string, unknown> };
  }
}

export class EventStream {
  static readonly finalKinds: ReadonlySet<string> = new Set(["runFinished", "runFailed"]);

  constructor(private readonly client: ApiClient) {}

  /** Follows a run's events, reconnecting from the last seen id if the connection drops. */
  async follow(runId: string, onEvent: (event: RunEvent) => void, signal: AbortSignal): Promise<void> {
    let lastId = "0";
    let delay = 1000;
    while (!signal.aborted) {
      try {
        const response = await fetch(this.client.url(`/runs/${encodeURIComponent(runId)}/events`), {
          headers: { "Last-Event-ID": lastId },
          credentials: "same-origin",
          signal,
        });
        if (response.status >= 400 && response.status < 500) {
          return; // unknown run or bad key: retrying will not help
        }
        if (!response.ok || !response.body) {
          throw new Error(`event stream failed with ${response.status}`);
        }
        const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
        const parser = new SseParser();
        delay = 1000;
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          for (const event of parser.feed(value)) {
            lastId = event.id;
            onEvent(event);
            if (EventStream.finalKinds.has(event.kind)) return;
          }
        }
      } catch {
        if (signal.aborted) return;
      }
      await this.wait(delay, signal);
      delay = Math.min(delay * 2, 15000);
    }
  }

  private wait(milliseconds: number, signal: AbortSignal): Promise<void> {
    return new Promise((resolve) => {
      const timer = setTimeout(resolve, milliseconds);
      signal.addEventListener("abort", () => {
        clearTimeout(timer);
        resolve();
      });
    });
  }
}
