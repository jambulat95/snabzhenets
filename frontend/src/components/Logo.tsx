// Логотип площадки — свой (ТЗ, раздел 10): знак «два агента обмениваются» + название.
// Название и подпись — константы, дизайнер меняет их здесь.
import { Link } from "react-router-dom";

export const BRAND_NAME = "A2A Маркет";
export const BRAND_TAGLINE = "агентный маркетплейс закупок";

export function LogoMark({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden="true" style={{ flex: "none" }}>
      <defs>
        <linearGradient id="a2a-logo-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2A852A" />
          <stop offset="1" stopColor="#00775A" />
        </linearGradient>
      </defs>
      <rect width="36" height="36" rx="8" fill="url(#a2a-logo-g)" />
      {/* Две встречные стрелки: агент покупателя ⇄ агент поставщика */}
      <path d="M9 14h15l-4-4" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M27 22H12l4 4" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="27" cy="14" r="2.4" fill="#50D04D" />
      <circle cx="9" cy="22" r="2.4" fill="#50D04D" />
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
