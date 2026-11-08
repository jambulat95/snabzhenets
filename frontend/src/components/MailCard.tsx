// Переписка с поставщиками: исходящие запросы и напоминания, входящие ответы (вложения, пометка инъекций).
import { Alert, Card, Collapse, Empty, Space, Typography } from "antd";
import { MailOutlined, PaperClipOutlined, SendOutlined } from "@ant-design/icons";
import dayjs from "dayjs";

import type { MessageRow, Procurement } from "../api";
import StatusTag from "./StatusTag";

const KIND: Record<string, string> = { request: "Запрос цен", reminder: "Напоминание", answer: "Ответ поставщику" };

export default function MailCard({ p }: { p: Procurement }) {
  const name = (m: MessageRow) => p.candidates.find((c) => c.id === m.candidate_id)?.name ?? m.address;
  if (p.messages.length === 0) {
    return (
      <Card title="Переписка">
        <Empty description="Писем пока нет" />
      </Card>
    );
  }
  return (
    <Card title="Переписка" extra={<Typography.Text type="secondary">Ящик заказчика: только почтовая песочница</Typography.Text>}>
      <Collapse
        size="small"
        items={p.messages.map((m) => ({
          key: m.id,
          label: (
            <Space size={8} wrap>
              {m.direction === "out" ? <SendOutlined /> : <MailOutlined />}
              <span>
                {m.direction === "out" ? "→" : "←"} {name(m)}
              </span>
              <Typography.Text type="secondary">{m.direction === "out" ? KIND[m.kind] ?? m.kind : m.subject}</Typography.Text>
              {m.attachments.length > 0 && (
                <StatusTag size="s" icon={<PaperClipOutlined />}>
                  {m.attachments.length}
                </StatusTag>
              )}
              {m.suspicious.length > 0 && (
                <StatusTag size="s" tone="error">
                  Похоже на команду агенту
                </StatusTag>
              )}
              {m.status === "blocked" && (
                <StatusTag size="s" tone="error">
                  Не отправлено: адрес вне песочницы
                </StatusTag>
              )}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {m.at ? dayjs(m.at).format("DD.MM HH:mm") : ""}
              </Typography.Text>
            </Space>
          ),
          children: (
            <div>
              {m.suspicious.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 8 }}
                  message="В письме есть текст, похожий на команды агенту"
                  description="Агент такие фрагменты не выполняет; цены из этого письма проверит человек."
                />
              )}
              <div className="pre-wrap" style={{ fontSize: 13 }}>
                {m.body}
              </div>
              {m.attachments.map((a) => (
                <div key={a.sha256} style={{ marginTop: 8 }}>
                  <PaperClipOutlined /> {a.filename} ({Math.round(a.size / 1024)} КБ) ·{" "}
                  <Typography.Text code>{a.sha256.slice(0, 12)}</Typography.Text>
                </div>
              ))}
            </div>
          ),
        }))}
      />
    </Card>
  );
}
