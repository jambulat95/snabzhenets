// Токены дизайн-системы для кода (то же, что CSS-переменные в global.css, раздел 3.3).
// В разметке предпочтительнее var(--c-...), здесь — для темы AntD и вычисляемых стилей.

export const T = {
  brand: "#08A553", // иконки, рамки, индикаторы, крупные цифры ≥ 24 px
  brandText: "#07843F", // ссылки и зелёный текст (AA)
  brandBg: "#E6F6EE",

  textPrimary: "#031912",
  textBody: "#214237",
  textSecondary: "#5D7069",
  textDisabled: "#BCC6C3",

  bgSubtle: "#F2F5F4",
  bgDark: "#031912",

  border: "#ECECEC",
  borderStrong: "#BCC6C3",
  divider: "#E6E6E6",
  borderDark: "#2B3234",

  font: '"Golos Text", -apple-system, "Segoe UI", Roboto, Arial, sans-serif',
} as const;

/** Тона статусных меток (раздел 4): цвет текста, фон, «сплошной» цвет точки. */
export type Tone = "success" | "attention" | "warning" | "error" | "neutral" | "brand";

export const TONES: Record<Tone, { text: string; bg: string; solid: string; border?: string }> = {
  success: { text: "#067A3D", bg: "#E6F6EE", solid: "#08A553" },
  attention: { text: "#886815", bg: "#FCF7E9", solid: "#E3AE23" },
  warning: { text: "#A34E00", bg: "#FDF1E6", solid: "#EC7100" },
  error: { text: "#C42727", bg: "#FEEBEB", solid: "#F13535" },
  neutral: { text: "#5D7069", bg: "#F2F5F4", solid: "#BCC6C3" },
  // «Зелёный контур»: состояния сделки до заказа
  brand: { text: "#07843F", bg: "#FFFFFF", solid: "#08A553", border: "#08A553" },
};
