// Цены по позициям: источник, регион, цена за единицу, вердикт методики, доказательство, решение человека.
import { useState } from "react";
import { Button, Card, Empty, Input, Modal, Table, Tooltip, Typography } from "antd";
import { CheckCircleFilled, CloseCircleFilled, ExclamationCircleFilled } from "@ant-design/icons";
import dayjs from "dayjs";

import { api, type Procurement, type Quote } from "../api";
import EvidenceButton from "./EvidenceButton";
import StatusTag from "./StatusTag";

const STATUS = {
  ok: { tone: "success", text: "В расчёт", icon: <CheckCircleFilled /> },
  review: { tone: "attention", text: "Проверить", icon: <ExclamationCircleFilled /> },
  rejected: { tone: "error", text: "Не подходит", icon: <CloseCircleFilled /> },
} as const;
const CHANNEL = { site: "Сайт", email: "Письмо", eis_contract: "Контракт ЕИС" } as const;

type Run = (fn: () => Promise<Procurement>, ok?: string) => void;

export default function PricesCard({ p, run }: { p: Procurement; run: Run }) {
  const [decide, setDecide] = useState<{ q: Quote; decision: "include" | "exclude" } | null>(null);
  const [reason, setReason] = useState("");
  const verdicts = p.analysis.quotes ?? {};
  const canDecide = p.status === "collecting" || p.status === "analysis";

  if (p.quotes.length === 0) {
    return (
      <Card title="Цены">
        <Empty description="Агент собирает цены: сначала открытые цены с сайтов, затем ответы поставщиков" />
      </Card>
    );
  }
  const verdictTag = (q: Quote) => {
    const v = verdicts[String(q.id)];
    const s = v ? (v.admitted ? STATUS.ok : v.verdicts.some((x) => x.verdict === "deny") ? STATUS.rejected : STATUS.review)
      : STATUS[q.status];
    const lines = v ? v.verdicts.map((x) => `${x.code}: ${x.reason}`) : [q.match.reason ?? "", ...q.notes];
    return (
      <Tooltip title={<div>{lines.filter(Boolean).map((l) => <div key={l}>• {l}</div>)}</div>}>
        <span>
          <StatusTag tone={s.tone} icon={s.icon}>
            {v ? (v.admitted ? "В расчёте" : s === STATUS.rejected ? "Не в расчёте" : "Решает человек") : s.text}
          </StatusTag>
        </span>
      </Tooltip>
    );
  };

  return (
    <Card title="Цены" extra={<Typography.Text type="secondary">Все цены приведены к цене с НДС 22 %</Typography.Text>}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 16 }}>
        {p.items.map((item) => {
          const rows = p.quotes.filter((q) => q.spec_item_id === item.id);
          return (
            <div key={item.id}>
              <Typography.Text strong>
                {item.line_no}. {item.name}
              </Typography.Text>{" "}
              <Typography.Text type="secondary">
                · {item.quantity ? Number(item.quantity).toLocaleString("ru-RU") : "—"} {item.unit} · КТРУ {item.ktru_code}
              </Typography.Text>
              <Table<Quote>
                size="small"
                rowKey="id"
                pagination={false}
                dataSource={rows}
                style={{ marginTop: 8 }}
                tableLayout="fixed"
                locale={{ emptyText: "Цен пока нет" }}
                rowClassName={(q) => (verdicts[String(q.id)] && !verdicts[String(q.id)].admitted ? "row-muted" : "")}
                columns={[
                  {
                    title: "Источник",
                    width: 230,
                    render: (_, q) => (
                      <div>
                        <div>
                          {q.source_name} <StatusTag outlined size="s">{CHANNEL[q.channel]}</StatusTag>
                        </div>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {q.region ?? "регион не указан"} · цена от {dayjs(q.captured_at).format("DD.MM.YYYY")}
                        </Typography.Text>
                      </div>
                    ),
                  },
                  { title: "Товар в источнике", dataIndex: "offer_name", ellipsis: true },
                  {
                    title: "Цена за ед., ₽",
                    dataIndex: "unit_price",
                    width: 120,
                    align: "right",
                    render: (v: string) => <span className="tabular">{Number(v).toLocaleString("ru-RU")}</span>,
                  },
                  { title: "Методика", width: 150, render: (_, q) => verdictTag(q) },
                  {
                    title: "",
                    width: 250,
                    render: (_, q) => (
                      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", flexWrap: "wrap" }}>
                        <EvidenceButton quote={q} />
                        {canDecide &&
                          (q.human_decision ? (
                            <Tooltip title={`Решение человека: ${q.human_reason}`}>
                              <Button
                                size="small"
                                onClick={() =>
                                  run(() =>
                                    api<Procurement>(`/procurements/${p.id}/quotes/${q.id}/decision`, {
                                      body: { decision: "clear", reason: "решение отменено" },
                                    }),
                                  )
                                }
                              >
                                Отменить решение
                              </Button>
                            </Tooltip>
                          ) : verdicts[String(q.id)]?.admitted ?? q.status === "ok" ? (
                            <Button size="small" onClick={() => setDecide({ q, decision: "exclude" })}>
                              Исключить
                            </Button>
                          ) : (
                            <Button size="small" onClick={() => setDecide({ q, decision: "include" })}>
                              Допустить
                            </Button>
                          ))}
                      </div>
                    ),
                  },
                ]}
              />
            </div>
          );
        })}
      </div>
      <Modal
        open={decide !== null}
        title={
          decide &&
          `${decide.decision === "exclude" ? "Исключить из расчёта" : "Допустить в расчёт"}: ${decide.q.source_name}, ${Number(
            decide.q.unit_price,
          ).toLocaleString("ru-RU")} ₽`
        }
        okText={decide?.decision === "exclude" ? "Исключить" : "Допустить"}
        okButtonProps={{ disabled: reason.trim().length < 3 }}
        onCancel={() => setDecide(null)}
        onOk={() => {
          if (!decide) return;
          const { q, decision } = decide;
          setDecide(null);
          run(
            () => api<Procurement>(`/procurements/${p.id}/quotes/${q.id}/decision`, { body: { decision, reason } }),
            "Решение записано, методика пересчитана",
          );
          setReason("");
        }}
      >
        <Typography.Paragraph type="secondary">
          Причина попадёт в журнал и в обоснование НМЦК. Цену старше 6 месяцев или без доказательства допустить нельзя.
        </Typography.Paragraph>
        <Input.TextArea
          autoFocus
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Например: предложен проектор другого класса — цена несопоставима"
          autoSize={{ minRows: 2 }}
        />
      </Modal>
    </Card>
  );
}
