import type { ReactNode } from "react";

type Block =
  | { type: "heading"; level: 1 | 2 | 3; text: string }
  | { type: "list"; ordered: boolean; start: number; items: string[] }
  | { type: "table"; header: string[]; rows: string[][] }
  | { type: "figure"; caption: string; src: string; source: string }
  | { type: "paragraph"; text: string };

/** A small Markdown subset rendered as React elements, never as raw HTML, because reports contain model output. */
export class MarkdownParser {
  static readonly arxivId = String.raw`\d{4}\.\d{4,5}(?:v\d+)?`;

  // ![caption](https://arxiv.org/html/... "arXiv:id §Section"). Images from anywhere else are dropped, not shown:
  // reports are model output, and an image link elsewhere could track readers.
  static readonly figureLine = /^!\[([^\]]*)\]\((https:\/\/arxiv\.org\/html\/[\w./-]+)(?:\s+"([^"]*)")?\)$/;

  // Order matters: a full Markdown link wins over a bare citation that starts at the same bracket.
  static readonly inlinePattern = new RegExp(
    [
      String.raw`\*\*(.+?)\*\*`,
      String.raw`\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)`,
      String.raw`\[(?:arXiv:\s?)?(${MarkdownParser.arxivId})(?:\s*§\s*([^\]]+))?\]`,
      String.raw`\barXiv:\s?(${MarkdownParser.arxivId})`,
    ].join("|"),
    "g",
  );

  static blocks(markdown: string): Block[] {
    const blocks: Block[] = [];
    let paragraph: string[] = [];
    let list: { ordered: boolean; start: number; items: string[] } | null = null;
    let table: string[][] = [];
    const flush = () => {
      if (paragraph.length) blocks.push({ type: "paragraph", text: paragraph.join(" ") });
      if (list) blocks.push({ type: "list", ...list });
      if (table.length) {
        const [header = [], ...rows] = table;
        blocks.push({ type: "table", header, rows });
      }
      paragraph = [];
      list = null;
      table = [];
    };
    for (const rawLine of markdown.split("\n")) {
      const line = rawLine.trim();
      const heading = /^(#{1,3})\s+(.*)$/.exec(line);
      const item = /^([-*]|\d+\.)\s+(.*)$/.exec(line);
      const figure = MarkdownParser.figureLine.exec(line);
      if (!line) {
        flush();
      } else if (line.startsWith("![")) {
        flush();
        if (figure?.[2]) blocks.push({ type: "figure", caption: figure[1] ?? "", src: figure[2], source: figure[3] ?? "" });
      } else if (line.startsWith("|")) {
        if (!table.length) flush();
        // Skip the |---|---| row under the header.
        if (!/^\|[\s:|-]+\|?$/.test(line)) table.push(MarkdownParser.cells(line));
      } else if (heading?.[1] && heading[2] !== undefined) {
        flush();
        blocks.push({ type: "heading", level: heading[1].length as 1 | 2 | 3, text: heading[2] });
      } else if (item?.[1] && item[2] !== undefined) {
        const ordered = /\d/.test(item[1]);
        if (paragraph.length || table.length || (list && list.ordered !== ordered)) flush();
        // Models often put blank lines between numbered items, so each new list keeps the item's own number.
        list ??= { ordered, start: ordered ? Number.parseInt(item[1], 10) : 1, items: [] };
        list.items.push(item[2]);
      } else {
        if (list || table.length) flush();
        paragraph.push(line);
      }
    }
    flush();
    return blocks;
  }

  static cells(line: string): string[] {
    return line
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => cell.trim());
  }

  static inline(text: string): ReactNode[] {
    const nodes: ReactNode[] = [];
    let cursor = 0;
    for (const match of text.matchAll(MarkdownParser.inlinePattern)) {
      nodes.push(text.slice(cursor, match.index));
      const [, bold, linkText, linkUrl, bracketedId, section, bareId] = match;
      if (bold !== undefined) {
        nodes.push(<strong key={match.index}>{MarkdownParser.inline(bold)}</strong>);
      } else if (linkText !== undefined && linkUrl !== undefined) {
        nodes.push(
          <a key={match.index} href={linkUrl} target="_blank" rel="noreferrer noopener">
            {linkText}
          </a>,
        );
      } else {
        const paperId = bracketedId ?? bareId ?? "";
        nodes.push(
          <a
            key={match.index}
            className="citation"
            href={`https://arxiv.org/abs/${paperId}`}
            target="_blank"
            rel="noreferrer noopener"
            title={`Open arXiv:${paperId}`}
          >
            arXiv:{paperId}
            {section ? ` · ${section.trim()}` : ""}
          </a>,
        );
      }
      cursor = match.index + match[0].length;
    }
    nodes.push(text.slice(cursor));
    return nodes;
  }
}

export function MarkdownView({ markdown }: { markdown: string }) {
  return (
    <article className="report">
      {MarkdownParser.blocks(markdown).map((block, index) => {
        if (block.type === "heading") {
          const Heading = `h${block.level + 1}` as "h2" | "h3" | "h4";
          return <Heading key={index}>{MarkdownParser.inline(block.text)}</Heading>;
        }
        if (block.type === "list") {
          const List = block.ordered ? "ol" : "ul";
          return (
            <List key={index} start={block.ordered ? block.start : undefined}>
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{MarkdownParser.inline(item)}</li>
              ))}
            </List>
          );
        }
        if (block.type === "figure") {
          return (
            <figure key={index} className="reportFigure">
              <img src={block.src} alt={block.caption} loading="lazy" referrerPolicy="no-referrer" />
              <figcaption>
                {MarkdownParser.inline(block.caption)}
                {block.source && <> {MarkdownParser.inline(`[${block.source}]`)}</>}
              </figcaption>
            </figure>
          );
        }
        if (block.type === "table") {
          return (
            <div key={index} className="reportTable">
              <table>
                <thead>
                  <tr>
                    {block.header.map((cell, cellIndex) => (
                      <th key={cellIndex}>{MarkdownParser.inline(cell)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex}>{MarkdownParser.inline(cell)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        return <p key={index}>{MarkdownParser.inline(block.text)}</p>;
      })}
    </article>
  );
}
