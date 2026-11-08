// Ход работы агента вместо спиннера (раздел 4.4). Показываем только известные этапы, которые отдаёт API
// (статус черновика, импорта, объекта), — шаги таймером не имитируем. Под шагами — время с начала;
// дольше 60 с — «Агент работает дольше обычного».
import { useEffect, useState } from "react";
import { CheckOutlined, CloseOutlined } from "@ant-design/icons";

export interface AgentStep {
  title: string;
  /** done — готово, current — идёт сейчас, wait — впереди, error — ошибка (в detail — причина) */
  status: "done" | "current" | "wait" | "error";
  detail?: string;
}

function Mark({ status }: { status: AgentStep["status"] }) {
  const box = { width: 20, height: 20, flex: "none", display: "grid", placeItems: "center", borderRadius: "50%" } as const;
  if (status === "done")
    return (
      <span style={{ ...box, background: "var(--c-success-bg)", color: "var(--c-brand)" }}>
        <CheckOutlined style={{ fontSize: 12 }} />
      </span>
    );
  if (status === "error")
    return (
      <span style={{ ...box, background: "var(--c-error-bg)", color: "var(--c-error)" }}>
        <CloseOutlined style={{ fontSize: 12 }} />
      </span>
    );
  if (status === "current")
    return (
      <span style={box}>
        <span className="pulse-dot" />
      </span>
    );
  return (
    <span style={box}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", border: "1.5px solid var(--c-border-strong)" }} />
    </span>
  );
}

export default function AgentProgress({
  steps,
  startedAt,
  title = "Агент работает",
}: {
  steps: AgentStep[];
  /** Начало работы (ISO или Date.now()); без него время не показываем. */
  startedAt?: string | number | null;
  title?: string;
}) {
  const [now, setNow] = useState(Date.now());
  const running = steps.some((s) => s.status === "current");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [running]);
  const start = startedAt ? new Date(startedAt).getTime() : null;
  const seconds = start ? Math.max(0, Math.round((now - start) / 1000)) : null;

  return (
    <div role="status" aria-live="polite" style={{ background: "var(--c-bg-subtle)", borderRadius: 8, padding: "20px 24px", maxWidth: 560 }}>
      <div style={{ fontSize: 16, lineHeight: "24px", color: "var(--c-text-primary)", marginBottom: 12 }}>{title}</div>
      <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
        {steps.map((s) => (
          <li key={s.title} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <Mark status={s.status} />
            <span>
              <span
                style={{
                  color: s.status === "wait" ? "var(--c-text-secondary)" : "var(--c-text-primary)",
                  fontWeight: s.status === "current" ? 500 : 400,
                }}
              >
                {s.title}
                {s.status === "current" ? "…" : ""}
              </span>
              {s.detail && (
                <div style={{ fontSize: 12, lineHeight: "16px", color: s.status === "error" ? "var(--c-error)" : "var(--c-text-secondary)" }}>
                  {s.detail}
                </div>
              )}
            </span>
          </li>
        ))}
      </ol>
      {seconds !== null && (
        <div className="tabular" style={{ marginTop: 12, fontSize: 12, lineHeight: "16px", color: "var(--c-text-secondary)" }}>
          {seconds} с{running && seconds > 60 ? " · Агент работает дольше обычного" : ""}
        </div>
      )}
    </div>
  );
}
