// Поставщики заявки: откуда найдены, проверки (ЕГРЮЛ, РНП, аффилированность), выбран ли и почему, статус запроса.
import { Card, Empty, Table, Tooltip, Typography } from "antd";

import type { CandidateRow, Procurement } from "../api";
import StatusTag from "./StatusTag";

const VERDICT = {
  allow: { tone: "success", text: "Проверки пройдены" },
  warn: { tone: "attention", text: "Есть замечания" },
  human: { tone: "warning", text: "Решает человек" },
  deny: { tone: "error", text: "Исключён" },
} as const;
const REQUEST = {
  none: { tone: "neutral", text: "Не запрашивали" },
  queued: { tone: "neutral", text: "В очереди" },
  sent: { tone: "brand", text: "Запрос отправлен" },
  reminded: { tone: "attention", text: "Напомнили" },
  replied: { tone: "success", text: "Ответил" },
} as const;

export default function SuppliersCard({ p }: { p: Procurement }) {
  const eis = p.journal.find((j) => j.action === "eis_searched");
  const selected = p.candidates.filter((c) => c.selected).length;
  return (
    <Card
      title="Поставщики"
      extra={
        <Typography.Text type="secondary">
          Запрос отправлен {selected} из {p.candidates.length}
        </Typography.Text>
      }
    >
      {eis?.decision === "empty" && (
        <Typography.Paragraph type="secondary">
          Реестр контрактов ЕИС: срез не подключён — поставщики из демо-справочника (вымышленные компании, письма уходят
          только в почтовую песочницу).
        </Typography.Paragraph>
      )}
      <Table<CandidateRow>
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={p.candidates}
        tableLayout="fixed"
        rowClassName={(c) => (c.selected ? "" : "row-muted")}
        locale={{ emptyText: <Empty description="Агент ищет поставщиков" /> }}
        columns={[
          { title: "№", dataIndex: "rank", width: 44 },
          {
            title: "Поставщик",
            render: (_, c) => (
              <div>
                <div>{c.name}</div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {c.city ?? c.region} · контрактов по 44-ФЗ за 3 года: {c.contracts_44fz_3y}
                  {c.source === "demo" ? " (демо)" : ""}
                </Typography.Text>
              </div>
            ),
          },
          {
            title: "Позиции",
            width: 90,
            render: (_, c) => p.items.filter((i) => c.item_ids.includes(i.id)).map((i) => i.line_no).join(", "),
          },
          {
            title: "Проверки",
            width: 190,
            render: (_, c) => (
              <Tooltip
                title={c.checks.map((ch) => (
                  <div key={ch.code + ch.reason}>
                    {ch.code}: {ch.reason}
                  </div>
                ))}
              >
                <span>
                  <StatusTag tone={VERDICT[c.verdict].tone}>{VERDICT[c.verdict].text}</StatusTag>
                </span>
              </Tooltip>
            ),
          },
          { title: "Почему", dataIndex: "reason", ellipsis: { showTitle: true } },
          {
            title: "Запрос",
            width: 150,
            render: (_, c) => <StatusTag tone={REQUEST[c.request_status].tone}>{REQUEST[c.request_status].text}</StatusTag>,
          },
        ]}
      />
    </Card>
  );
}
