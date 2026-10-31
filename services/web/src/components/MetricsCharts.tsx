import { useState } from "react";

export interface Series<Row> {
  key: keyof Row & string;
  label: string;
  color: string;
}

const height = 170;
const axisWidth = 34;
const barGap = 10;

/** Rounded only at the top, so a bar or the top segment of a stack stays anchored to the baseline. */
class BarShape {
  static path(x: number, y: number, width: number, barHeight: number, rounded: boolean): string {
    const radius = rounded ? Math.min(4, width / 2, barHeight) : 0;
    return `M${x},${y + barHeight} V${y + radius} Q${x},${y} ${x + radius},${y} H${x + width - radius} Q${x + width},${y} ${x + width},${y + radius} V${y + barHeight} Z`;
  }

  static niceMax(value: number): number {
    if (value <= 0) return 1;
    const step = 10 ** Math.floor(Math.log10(value));
    return Math.ceil(value / step) * step;
  }
}

/** Daily stacked bars with a legend that carries each series' total, and a tooltip per day. */
export function StackedDays<Row extends { day: string }>({
  rows,
  series,
  format = (value) => String(value),
}: {
  rows: Row[];
  series: Series<Row>[];
  format?: (value: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const totals = rows.map((row) => series.reduce((sum, item) => sum + Number(row[item.key] ?? 0), 0));
  const max = BarShape.niceMax(Math.max(0, ...totals));
  const width = 560;
  const slot = (width - axisWidth) / Math.max(1, rows.length);
  const barWidth = Math.max(6, slot - barGap);
  const scale = (value: number) => (value / max) * height;

  return (
    <div className="chart">
      <ul className="chartLegend">
        {series.map((item) => (
          <li key={item.key}>
            <span className="legendSwatch" style={{ background: item.color }} />
            {item.label} <strong>{format(rows.reduce((sum, row) => sum + Number(row[item.key] ?? 0), 0))}</strong>
          </li>
        ))}
      </ul>
      <div className="chartFrame">
        <svg viewBox={`0 0 ${width} ${height + 22}`} role="img" aria-label={`${series.map((item) => item.label).join(", ")} per day`}>
          {[0, 0.5, 1].map((share) => (
            <g key={share}>
              <line className="gridLine" x1={axisWidth} x2={width} y1={height - share * height} y2={height - share * height} />
              <text className="axisText" x={axisWidth - 6} y={height - share * height + 4} textAnchor="end">
                {format(max * share)}
              </text>
            </g>
          ))}
          {rows.map((row, index) => {
            const x = axisWidth + index * slot + barGap / 2;
            let top = height;
            const segments = series
              .map((item) => ({ item, value: Number(row[item.key] ?? 0) }))
              .filter((segment) => segment.value > 0);
            return (
              <g key={row.day} onMouseEnter={() => setHover(index)} onMouseLeave={() => setHover(null)}>
                {/* Hit target covers the whole column, larger than the bar itself. */}
                <rect x={x - barGap / 2} y={0} width={slot} height={height} fill="transparent" />
                {segments.map((segment, segmentIndex) => {
                  const segmentHeight = scale(segment.value);
                  top -= segmentHeight;
                  const isTop = segmentIndex === segments.length - 1;
                  // A 2px gap of surface between stacked segments keeps their edges readable.
                  const gap = segmentIndex === 0 ? 0 : 2;
                  return (
                    <path
                      key={segment.item.key}
                      d={BarShape.path(x, top, barWidth, Math.max(0, segmentHeight - gap), isTop)}
                      fill={segment.item.color}
                      opacity={hover === null || hover === index ? 1 : 0.45}
                    />
                  );
                })}
                <text className="axisText" x={x + barWidth / 2} y={height + 16} textAnchor="middle">
                  {row.day.slice(5).replace("-", "/")}
                </text>
              </g>
            );
          })}
        </svg>
        {hover !== null && rows[hover] && (
          <div className="chartTooltip" style={{ left: `${((axisWidth + hover * slot + slot / 2) / width) * 100}%` }}>
            <strong>{rows[hover].day}</strong>
            {series.map((item) => (
              <span key={item.key}>
                <span className="legendSwatch" style={{ background: item.color }} />
                {item.label}: {format(Number(rows[hover]?.[item.key] ?? 0))}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** Horizontal bars with the label and value as text, for a short ranked list. */
export function RankedBars({ items, color }: { items: { label: string; value: number }[]; color: string }) {
  const max = Math.max(1, ...items.map((item) => item.value));
  if (items.length === 0) return <p className="muted">Nothing in this period.</p>;
  return (
    <ul className="rankedBars">
      {items.map((item) => (
        <li key={item.label} title={`${item.label}: ${item.value}`}>
          <span className="rankedLabel">{item.label}</span>
          <span className="rankedTrack">
            <span className="rankedFill" style={{ width: `${(item.value / max) * 100}%`, background: color }} />
          </span>
          <span className="rankedValue">{item.value}</span>
        </li>
      ))}
    </ul>
  );
}
