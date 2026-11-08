// Логотип «Снабженца»: знак «список закупки с отметкой» + название. Каркас — из A2A Маркет.
import { Link } from "react-router-dom";

export const BRAND_NAME = "Снабженец";
export const BRAND_TAGLINE = "ИИ-агент снабженца";

export function LogoMark({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden="true" style={{ flex: "none" }}>
      <defs>
        <linearGradient id="snab-logo-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2A852A" />
          <stop offset="1" stopColor="#00775A" />
        </linearGradient>
      </defs>
      <rect width="36" height="36" rx="8" fill="url(#snab-logo-g)" />
      {/* Лист заявки: строки и отметка «проверено» */}
      <path d="M11 11h10M11 16h14M11 21h7" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M20 24l3 3 6-7" fill="none" stroke="#50D04D" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function Logo({ to = "/", inverted = false, compact = false }: { to?: string; inverted?: boolean; compact?: boolean }) {
  return (
    <Link to={to} style={{ display: "inline-flex", alignItems: "center", gap: 10, textDecoration: "none" }} aria-label={BRAND_NAME}>
      <LogoMark size={compact ? 32 : 36} />
      <span style={{ display: "flex", flexDirection: "column" }}>
        <span
          style={{
            fontSize: compact ? 20 : 25,
            lineHeight: compact ? "24px" : "30px",
            fontWeight: 600,
            color: inverted ? "#fff" : "var(--c-text-primary)",
            whiteSpace: "nowrap",
          }}
        >
          {BRAND_NAME}
        </span>
        <span style={{ fontSize: 11, lineHeight: "13px", color: inverted ? "#BCC6C3" : "var(--c-text-secondary)", whiteSpace: "nowrap" }}>
          {BRAND_TAGLINE}
        </span>
      </span>
    </Link>
  );
}
