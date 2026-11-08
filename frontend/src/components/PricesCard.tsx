// Цены по позициям: источник, регион, цена за единицу, сверка товара, доказательство.
import { Card, Empty, Table, Tooltip, Typography } from "antd";
import { CheckCircleFilled, CloseCircleFilled, ExclamationCircleFilled } from "@ant-design/icons";
import dayjs from "dayjs";

import type { Procurement, Quote } from "../api";
import EvidenceButton from "./EvidenceButton";
import StatusTag from "./StatusTag";

const STATUS = {
  ok: { tone: "success", text: "В расчёт", icon: <CheckCircleFilled /> },
  review: { tone: "attention", text: "Проверить", icon: <ExclamationCircleFilled /> },
  rejected: { tone: "error", text: "Не подходит", icon: <CloseCircleFilled /> },
} as const;
const CHANNEL = { site: "Сайт", email: "Письмо", eis_contract: "Контракт ЕИС" } as const;

export default function PricesCard({ p }: { p: Procurement }) {
  if (p.quotes.length === 0) {
    return (
      <Card title="Цены">
        <Empty description="Агент собирает цены: сначала открытые цены с сайтов, затем ответы поставщиков" />
      </Card>
    );
  }
  return (
    <Card title="Цены" extra={<Typography.Text type="secondary">Цены с сайтов — розничные, с НДС</Typography.Text>}>
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
                columns={[
                  {
                    title: "Источник",
                    width: 220,
                    render: (_, q) => (
                      <div>
                        <div>
                          {q.source_name} <StatusTag outlined size="s">{CHANNEL[q.channel]}</StatusTag>
                        </div>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {q.region ?? "регион не указан"} · {dayjs(q.captured_at).format("DD.MM.YYYY")}
                        </Typography.Text>
                      </div>
                    ),
                  },
                  { title: "Товар в источнике", dataIndex: "offer_name", ellipsis: true },
                  {
                    title: "Цена за ед., ₽",
                    dataIndex: "unit_price",
                    width: 130,
                    align: "right",
                    render: (v: string) => <span className="tabular">{Number(v).toLocaleString("ru-RU")}</span>,
                  },
                  {
                    title: "Сверка товара",
                    width: 170,
                    render: (_, q) => {
                      const s = STATUS[q.status];
                      return (
                        <Tooltip
                          title={
                            <div>
                              <div>{q.match.reason ?? "Модель не сверяла"}</div>
                              {(q.match.differences ?? []).map((d) => (
                                <div key={d}>• {d}</div>
                              ))}
                              {q.notes.map((n) => (
                                <div key={n}>— {n}</div>
                              ))}
                            </div>
                          }
                        >
                          <span>
                            <StatusTag tone={s.tone} icon={s.icon}>
                              {s.text}
                            </StatusTag>
                          </span>
                        </Tooltip>
                      );
                    },
                  },
                  { title: "", width: 150, render: (_, q) => <EvidenceButton quote={q} /> },
                ]}
              />
            </div>
          );
        })}
      </div>
    </Card>
  );
}
