import type { ProcStatus } from "./api";
import type { Tone } from "./theme/tokens";

export const STATUS_TONE: Record<ProcStatus, Tone> = {
  draft: "neutral",
  spec_review: "attention",
  sourcing: "brand",
  collecting: "brand",
  analysis: "brand",
  justification_review: "attention",
  approved: "success",
  closed: "neutral",
  needs_human: "error",
  cancelled: "neutral",
};

/** Этапы конвейера в порядке прохождения (для шкалы хода работы). */
export const STAGES: { key: ProcStatus; title: string; human?: boolean }[] = [
  { key: "draft", title: "Разбор заявки" },
  { key: "spec_review", title: "Проверка спецификации", human: true },
  { key: "sourcing", title: "Поиск поставщиков" },
  { key: "collecting", title: "Сбор цен" },
  { key: "analysis", title: "Проверка по методике" },
  { key: "justification_review", title: "Проверка обоснования", human: true },
  { key: "approved", title: "Утверждено" },
];

export const ACTION_TITLES: Record<string, string> = {
  created: "Заявка создана",
  model_call: "Вызов модели",
  spec_parsed: "Агент разобрал заявку",
  status: "Смена этапа",
  spec_item_edited: "Позиция изменена",
  spec_item_added: "Позиция добавлена",
  spec_item_deleted: "Позиция удалена",
};

export const ACTOR_TITLES = { human: "Человек", agent: "Агент", system: "Система" } as const;
