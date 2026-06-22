import { useEffect, useRef } from "react";
import * as echarts from "echarts";

interface Props {
  option: echarts.EChartsOption;
  height?: number;
  /** Re-create the instance when this changes (e.g. chart type swap). */
  resetKey?: string | number;
  onEvents?: Record<string, (params: any) => void>;
}

/** Thin lifecycle wrapper around an ECharts instance: init once, setOption on
 *  change, resize with the container, dispose on unmount. */
export default function EChart({ option, height = 320, resetKey, onEvents }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  // (re)create the instance
  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current);
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, [resetKey]);

  // push option (notMerge so removed series/axes clear cleanly)
  useEffect(() => {
    chart.current?.setOption(option, true);
  }, [option]);

  // (re)bind handlers
  useEffect(() => {
    const c = chart.current;
    if (!c || !onEvents) return;
    for (const [evt, fn] of Object.entries(onEvents)) c.on(evt, fn);
    return () => {
      for (const evt of Object.keys(onEvents)) c.off(evt);
    };
  }, [onEvents, resetKey]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}
