"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { components } from "./api-types";

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);
type Point = components["schemas"]["Point"];

export function fiscalLabel(year: number, quarter?: number | null) {
  return quarter ? `FY${year} Q${quarter}` : `FY${year}`;
}

export function FlowChart({ points }: { points: Point[] }) {
  const target = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!target.current || !points.some((point) => point.value !== null)) return;
    const node = target.current;
    const chart = echarts.init(node);
    // Each contiguous reporting scope gets its own line. Missing values break the line.
    const runs: { scope: string; indices: number[] }[] = [];
    points.forEach((point, index) => {
      const last = runs.at(-1);
      if (last?.scope === point.scope_key) last.indices.push(index);
      else runs.push({ scope: point.scope_key, indices: [index] });
    });
    chart.setOption({
      animation: false,
      grid: { left: 57, right: 24, top: 24, bottom: 44 },
      tooltip: { trigger: "axis", valueFormatter: (value: unknown) =>
        typeof value === "number" ? `$${value.toLocaleString("en-US", { maximumFractionDigits: 2 })}M` : "Unavailable" },
      xAxis: {
        type: "category", boundaryGap: true,
        data: points.map(({ fiscal_year, quarter }) => fiscalLabel(fiscal_year, quarter)),
        axisLabel: { color: "#64748b", fontSize: 12, hideOverlap: true, margin: 13 },
        axisTick: { show: false }, axisLine: { lineStyle: { color: "#d9e1e7" } },
      },
      yAxis: {
        type: "value", axisLabel: { color: "#64748b", fontSize: 12, formatter: "${value}M" },
        splitLine: { lineStyle: { color: "#e8eef1", type: "dashed" } },
      },
      series: runs.map(({ indices }, run) => ({
        type: "line", name: "Free cash flow", connectNulls: false,
        data: points.map(({ value }, index) => indices.includes(index) && value !== null ? Number(value) / 1e6 : null),
        symbol: "circle", symbolSize: 7, lineStyle: { width: 2.6 },
        itemStyle: { color: run % 2 === 0 ? "#087f73" : "#4268b7" },
        areaStyle: { color: run % 2 === 0 ? "#e3f4ee" : "#edf2fd", opacity: 0.45 },
      })),
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(node);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [points]);
  if (!points.some((point) => point.value !== null)) {
    return <div className="chart-empty">Free cash flow is unavailable for these periods.</div>;
  }
  return <div ref={target} className="chart" aria-hidden="true" data-testid="fcf-chart" />;
}
