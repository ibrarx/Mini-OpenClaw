/**
 * AnimatedEdge — Custom React Flow edge with draw-in animation.
 *
 * Supports three visual styles:
 *   - normal: solid line, neutral color
 *   - error: dashed red line
 *   - delegate: dotted purple line
 *
 * Edges animate in with stroke-dashoffset on mount.
 */

import { memo, useRef, useEffect, useState } from "react";
import { getBezierPath, type EdgeProps } from "@xyflow/react";

const EDGE_COLORS = {
  normal: "var(--text-faint)",
  error: "#ef4444",
  delegate: "#7c3aed",
};

const EDGE_DASH = {
  normal: "none",
  error: "6 4",
  delegate: "3 3",
};

function AnimatedEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  data,
}: EdgeProps) {
  const edgeType = (data?.edgeType as string) || "normal";
  const color = EDGE_COLORS[edgeType as keyof typeof EDGE_COLORS] || EDGE_COLORS.normal;
  const dash = EDGE_DASH[edgeType as keyof typeof EDGE_DASH] || EDGE_DASH.normal;

  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  // Animation: draw-in effect via stroke-dashoffset
  const pathRef = useRef<SVGPathElement>(null);
  const [animated, setAnimated] = useState(false);

  useEffect(() => {
    const el = pathRef.current;
    if (!el || animated) return;

    const length = el.getTotalLength();
    el.style.strokeDasharray = `${length}`;
    el.style.strokeDashoffset = `${length}`;

    // Trigger reflow so the browser registers the initial state
    el.getBoundingClientRect();

    el.style.transition = "stroke-dashoffset 0.5s ease-out";
    el.style.strokeDashoffset = "0";

    const timer = setTimeout(() => {
      // After animation, apply the intended dash pattern
      el.style.transition = "";
      el.style.strokeDasharray = dash === "none" ? "" : dash;
      el.style.strokeDashoffset = "";
      setAnimated(true);
    }, 550);

    return () => clearTimeout(timer);
  }, [animated, dash]);

  return (
    <path
      ref={pathRef}
      id={id}
      d={edgePath}
      fill="none"
      stroke={color}
      strokeWidth={edgeType === "error" ? 1 : 0.75}
      strokeLinecap="round"
      style={{
        ...style,
        opacity: edgeType === "delegate" ? 0.6 : 0.5,
      }}
    />
  );
}

export default memo(AnimatedEdge);
