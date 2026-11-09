// Методика (приказ № 567): по позициям — сколько цен в расчёте, средняя, коэффициент вариации, НМЦК; итог;
// что мешает. Утверждает контрактный управляющий — вторая точка утверждения.
import { Alert, Button, Card, Descriptions, Space, Table, Typography } from "antd";
import { FileWordOutlined } from "@ant-design/icons";

import { api, type Procurement } from "../api";
import { useAuth } from "../auth";
import ConfirmAction from "./ConfirmAction";
import StatusTag from "./StatusTag";

const rub = (v: string | null | undefined) =>
  v ? `${Number(v).toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₽` : "—";

export default function AnalysisCard({ p, run }: { p: Procurement; run: (fn: () => Promise<Procurement>, ok?: string) => void }) {
  const { me } = useAuth();
  const a = p.analysis;
  const collecting = p.status === "collecting";
  if (!a.items) {
    return collecting ? (
      <Card title="Проверка по методике">
        <Typography.Paragraph type="secondary">
          Расчёт начнётся, когда ответят все поставщики, которым ушёл запрос, или истечёт срок сбора.
        </Typography.Paragraph>
        <ConfirmAction
          title="Завершить сбор цен и посчитать по тем, что есть"
          okText="Завершить сбор"
          buttonText="Завершить сбор досрочно"
          onConfirm={() => run(() => api<Procurement>(`/procurements/${p.id}/finish-collecting`, { method: "POST" }))}
        >
          Поставщики, которые ещё не ответили, в расчёт не попадут. Это будет записано в журнал.
        </ConfirmAction>
      </Card>
    ) : null;
  }
  const canApprove = p.status === "justification_review" && me?.role === "contract_manager";
  return (
    <Card
      title="Проверка по методике"
      extra={<Typography.Text type="secondary">{a.method}</Typography.Text>}
    >
      <Descriptions size="small" column={1} style={{ marginBottom: 12 }}>
        <Descriptions.Item label="Основание">{a.source}</Descriptions.Item>
        {a.general?.map((g) => (
          <Descriptions.Item key={g.code} label={g.code}>
            {g.reason}
          </Descriptions.Item>
        ))}
      </Descriptions>
      <Table
        size="small"
        rowKey="item_id"
        pagination={false}
        dataSource={a.items}
        tableLayout="fixed"
        columns={[
          { title: "№", dataIndex: "line_no", width: 44 },
          { title: "Позиция", dataIndex: "name" },
          { title: "Цен в расчёте", width: 120, render: (_, i) => `${i.admitted} из ${i.quotes}` },
          { title: "Средняя цена", width: 140, align: "right", render: (_, i) => <span className="tabular">{rub(i.mean)}</span> },
          {
            title: "CV",
            width: 80,
            align: "right",
            render: (_, i) => <span className="tabular">{i.cv_pct ? `${i.cv_pct.replace(".", ",")} %` : "—"}</span>,
          },
          { title: "НМЦК позиции", width: 150, align: "right", render: (_, i) => <span className="tabular">{rub(i.nmck)}</span> },
          {
            title: "Итог",
            width: 260,
            render: (_, i) =>
              i.ok ? (
                <StatusTag tone="success">Соответствует методике</StatusTag>
              ) : (
                <div style={{ display: "grid", gap: 4 }}>
                  {i.verdicts.map((v) => (
                    <Typography.Text key={v.code} type="danger" style={{ fontSize: 12 }}>
                      {v.code}: {v.reason}
                    </Typography.Text>
                  ))}
                </div>
              ),
          },
        ]}
      />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 16, gap: 16 }}>
        <Space size={16} wrap>
          <Typography.Title level={4} style={{ margin: 0 }}>
            НМЦК: {a.ready ? rub(a.total_nmck) : "не рассчитана"}
          </Typography.Title>
          {(p.status === "justification_review" || p.status === "approved") && (
            <Button icon={<FileWordOutlined />} href={`/api/procurements/${p.id}/justification.docx`}>
              {p.status === "approved" ? "Обоснование (DOCX)" : "Проект обоснования (DOCX)"}
            </Button>
          )}
          {p.status === "approved" && <StatusTag tone="success">Утверждено</StatusTag>}
        </Space>
        {p.status === "analysis" && !a.ready && (
          <Button onClick={() => run(() => api<Procurement>(`/procurements/${p.id}/reanalyse`, { method: "POST" }))}>
            Пересчитать
          </Button>
        )}
        {p.status === "justification_review" && (
          canApprove ? (
            <ConfirmAction
              title={`Утвердить обоснование НМЦК на ${rub(a.total_nmck)}`}
              okText="Утвердить"
              buttonText="Утвердить обоснование"
              button={{ type: "primary" }}
              onConfirm={() => run(() => api<Procurement>(`/procurements/${p.id}/approve`, { method: "POST" }), "Обоснование утверждено")}
            >
              Вы подтверждаете, что проверили цены, их источники и доказательства. Решение будет записано в журнал с вашим
              именем.
            </ConfirmAction>
          ) : (
            <Alert type="info" showIcon message="Обоснование утверждает контрактный управляющий" />
          )
        )}
      </div>
      {!a.ready && p.status === "analysis" && (
        <Alert
          style={{ marginTop: 12 }}
          type="warning"
          showIcon
          message="Расчёт не готов"
          description="Исключите выброс или допустите цену на проверке — с причиной. Решение записывается в журнал, методика пересчитывается сразу."
        />
      )}
    </Card>
  );
}
