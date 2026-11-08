// Метка статуса по тону дизайн-системы (вместо Tag color="blue/purple/…"). Цвет всегда дублируется словом.
import type { CSSProperties, ReactNode } from "react";
import { Tooltip } from "antd";

import { TONES, type Tone } from "../theme/tokens";

export interface StatusTagProps {
  tone?: Tone;
  children: ReactNode;
  /** Точка 6 px слева (чипы автономии, статусы доставки). */
  dot?: boolean;
  icon?: ReactNode;
  /** «s» — для плотных таблиц. */
  size?: "s" | "m";
  /** Контурная метка: «Демо», «Из письма», «После срока». */
  outlined?: boolean;
  tooltip?: ReactNode;
  style?: CSSProperties;
}

export default function StatusTag({ tone = "neutral", children, dot, icon, size = "m", outlined, tooltip, style }: StatusTagProps) {
  const t = TONES[tone];
  const css: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    height: size === "s" ? 22 : 24,
    padding: "0 8px",
    borderRadius: 6,
    fontSize: 12,
    lineHeight: "16px",
    fontWeight: 500,
    whiteSpace: "nowrap",
    verticalAlign: "middle",
    color: outlined ? "var(--c-text-secondary)" : t.text,
    background: outlined ? "transparent" : t.bg,
    border: `1px solid ${outlined ? "var(--c-border-strong)" : (t.border ?? t.bg)}`,
    ...style,
  };
  const tag = (
    <span style={css}>
      {dot && <span style={{ width: 6, height: 6, borderRadius: "50%", background: t.solid, flex: "none" }} />}
      {icon}
      {children}
    </span>
  );
  return tooltip ? <Tooltip title={tooltip}>{tag}</Tooltip> : tag;
}
