// Карточка заявки: ход работы агента, спецификация (правка на шаге проверки), журнал.
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Alert,
  App,
  Button,
  Card,
  Collapse,
  Empty,
  Input,
  InputNumber,
  Select,
  Space,
  Steps,
  Table,
  Tooltip,
  Typography,
} from "antd";
import { DeleteOutlined, PlusOutlined, QuestionCircleOutlined, RobotOutlined, UserOutlined } from "@ant-design/icons";
import dayjs from "dayjs";

import { api, type KtruCandidate, type Procurement, type SpecItem } from "../api";
import { useAuth } from "../auth";
import AgentProgress from "../components/AgentProgress";
import ConfirmAction from "../components/ConfirmAction";
import StatusTag from "../components/StatusTag";
import { ACTION_TITLES, ACTOR_TITLES, STAGES, STATUS_TONE } from "../labels";

const UNITS = ["шт", "упак", "пачка", "компл", "кг", "м", "л"];

export default function ProcurementPage() {
  const { id } = useParams();
  const { me } = useAuth();
  const { message } = App.useApp();
  const [p, setP] = useState<Procurement | null>(null);
  const [ktru, setKtru] = useState<KtruCandidate[]>([]);
  const [chain, setChain] = useState<{ ok: boolean; checked: number; reason: string | null } | null>(null);

  const load = useCallback(() => api<Procurement>(`/procurements/${id}`).then(setP), [id]);
  useEffect(() => {
    load();
    api<KtruCandidate[]>("/ktru").then(setKtru);
  }, [load]);
  // Пока агент работает — обновляем карточку
  useEffect(() => {
    if (!p || !["draft", "sourcing", "collecting", "analysis"].includes(p.status)) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [p, load]);

  if (!p) return <Card loading />;
  const editable = p.status === "spec_review";
  const run = async (fn: () => Promise<Procurement>, ok?: string) => {
    try {
      setP(await fn());
      if (ok) message.success(ok);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "Ошибка");
    }
  };
  const patch = (item: SpecItem, body: Record<string, unknown>) =>
    run(() => api<Procurement>(`/procurements/${p.id}/items/${item.id}`, { method: "PATCH", body }));

  const stageIndex = Math.max(0, STAGES.findIndex((s) => s.key === p.status));
  const openQuestions = p.items.flatMap((i) => i.questions.map((q) => `Позиция ${i.line_no}: ${q}`));
  const blockers = p.items.filter((i) => !i.quantity || !i.unit || !i.ktru_code).map((i) => i.line_no);
  const cost = p.journal.reduce((s, j) => s + (j.cost_rub ? Number(j.cost_rub) : 0), 0);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
        <div>
          <Typography.Text type="secondary">{p.number}</Typography.Text>
          <Typography.Title level={2} style={{ margin: 0 }}>
            {p.title}
          </Typography.Title>
        </div>
        <StatusTag tone={STATUS_TONE[p.status]}>{p.status_title}</StatusTag>
      </div>

      <Card size="small">
        <Steps
          size="small"
          labelPlacement="vertical"
          current={p.status === "needs_human" ? undefined : stageIndex}
          items={STAGES.map((s) => ({ title: s.title, icon: s.human ? <UserOutlined /> : undefined }))}
        />
      </Card>

      {p.status === "needs_human" && <Alert type="error" showIcon message="Нужен человек" description={p.hold_reason} />}

      {p.status === "draft" && (
        <AgentProgress
          startedAt={p.created_at}
          title="Агент разбирает заявку"
          steps={[
            { title: "Разбор текста на позиции", status: "current" },
            { title: "Подбор кодов КТРУ", status: "wait" },
            { title: "Вопросы по пробелам", status: "wait" },
          ]}
        />
      )}

      {p.parse_meta.suspicious && p.parse_meta.suspicious.length > 0 && (
        <Alert
          type="warning"
          showIcon
          message="В тексте заявки есть фрагменты, похожие на команды агенту"
          description="Агент их не выполняет. Проверьте позиции внимательно."
        />
      )}

      {p.status !== "draft" && (
        <Card
          title="Спецификация"
          extra={
            editable && (
              <Space>
                <Button
                  icon={<PlusOutlined />}
                  onClick={() =>
                    run(() => api<Procurement>(`/procurements/${p.id}/items`, { body: { name: "Новая позиция", unit: "шт" } }))
                  }
                >
                  Добавить позицию
                </Button>
                <ConfirmAction
                  title="Подтвердить спецификацию и запустить поиск поставщиков"
                  okText="Подтвердить"
                  buttonText="Подтвердить спецификацию"
                  button={{ type: "primary", disabled: blockers.length > 0 }}
                  onConfirm={() =>
                    run(() => api<Procurement>(`/procurements/${p.id}/confirm-spec`, { method: "POST" }), "Спецификация подтверждена")
                  }
                >
                  Агент найдёт поставщиков по выбранным кодам КТРУ и начнёт собирать цены. Позиции после этого не
                  редактируются: при изменении потребности создайте новую заявку.
                </ConfirmAction>
              </Space>
            )
          }
        >
          {editable && openQuestions.length > 0 && (
            <Alert
              type="warning"
              showIcon
              icon={<QuestionCircleOutlined />}
              style={{ marginBottom: 16 }}
              message="Агенту нужно уточнение"
              description={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {openQuestions.map((q) => (
                    <li key={q}>{q}</li>
                  ))}
                </ul>
              }
            />
          )}
          <Table<SpecItem>
            rowKey="id"
            pagination={false}
            dataSource={p.items}
            locale={{ emptyText: <Empty description="Позиций нет" /> }}
            rowClassName={(r) => (r.status === "needs_review" ? "row-unrecognized" : "")}
            tableLayout="fixed"
            columns={[
              { title: "№", dataIndex: "line_no", width: 48 },
              {
                title: "Наименование",
                dataIndex: "name",
                width: 340,
                render: (v: string, r) =>
                  editable ? (
                    <Input.TextArea
                      defaultValue={v}
                      autoSize
                      onBlur={(e) => e.target.value !== v && patch(r, { name: e.target.value })}
                    />
                  ) : (
                    <div>
                      <div>{v}</div>
                      {r.characteristics && <Typography.Text type="secondary">{r.characteristics}</Typography.Text>}
                    </div>
                  ),
              },
              {
                title: "Кол-во",
                dataIndex: "quantity",
                width: 110,
                align: "right",
                render: (v: string | null, r) =>
                  editable ? (
                    <InputNumber
                      min={0}
                      defaultValue={v ? Number(v) : undefined}
                      status={v ? undefined : "error"}
                      onBlur={(e) => {
                        const n = Number(e.target.value.replace(",", "."));
                        if (n > 0 && n !== Number(v)) patch(r, { quantity: n });
                      }}
                    />
                  ) : (
                    <span className="tabular">{v ? Number(v).toLocaleString("ru-RU") : "—"}</span>
                  ),
              },
              {
                title: "Ед.",
                dataIndex: "unit",
                width: 110,
                render: (v: string | null, r) =>
                  editable ? (
                    <Select
                      value={v ?? undefined}
                      status={v ? undefined : "error"}
                      style={{ width: 95 }}
                      options={[...new Set([...(v ? [v] : []), ...UNITS])].map((u) => ({ value: u, label: u }))}
                      onChange={(u) => patch(r, { unit: u })}
                    />
                  ) : (
                    v
                  ),
              },
              {
                title: "Код КТРУ",
                dataIndex: "ktru_code",
                render: (v: string | null, r) => {
                  const cands = r.ktru_candidates.map((c) => c.code);
                  const options = [...ktru].sort((a, b) => Number(cands.includes(b.code)) - Number(cands.includes(a.code)));
                  return (
                    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 4 }}>
                      {editable ? (
                        <Select
                          value={v ?? undefined}
                          placeholder="Выберите код"
                          status={v ? undefined : "error"}
                          style={{ width: "100%" }}
                          popupMatchSelectWidth={480}
                          options={options.map((c) => ({
                            value: c.code,
                            label: `${c.code} — ${c.name}${cands.includes(c.code) ? "" : " (не кандидат)"}`,
                          }))}
                          onChange={(code) => patch(r, { ktru_code: code })}
                        />
                      ) : (
                        <span className="tabular">{v}</span>
                      )}
                      {r.ktru_suggestion && (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          <RobotOutlined /> {r.ktru_suggestion.reason}
                        </Typography.Text>
                      )}
                    </div>
                  );
                },
              },
              ...(editable
                ? [
                    {
                      title: "",
                      width: 48,
                      render: (_: unknown, r: SpecItem) => (
                        <Tooltip title="Удалить позицию">
                          <Button
                            type="text"
                            icon={<DeleteOutlined />}
                            onClick={() =>
                              run(() => api<Procurement>(`/procurements/${p.id}/items/${r.id}`, { method: "DELETE" }))
                            }
                          />
                        </Tooltip>
                      ),
                    },
                  ]
                : []),
            ]}
          />
          {editable && blockers.length > 0 && (
            <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
              Чтобы подтвердить, заполните количество, единицу и код КТРУ в позициях: {blockers.join(", ")}.
            </Typography.Paragraph>
          )}
          {p.parse_meta.deadline_raw && (
            <Typography.Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
              Срок из заявки: <b>{p.parse_meta.deadline_raw}</b>
            </Typography.Paragraph>
          )}
        </Card>
      )}

      <Collapse
        items={[
          {
            key: "text",
            label: "Исходный текст заявки",
            children: <div className="pre-wrap">{p.source_text}</div>,
          },
          {
            key: "journal",
            label: `Журнал действий (${p.journal.length}) · стоимость моделей ${cost.toLocaleString("ru-RU", {
              maximumFractionDigits: 2,
            })} ₽`,
            extra: (
              <Button
                size="small"
                onClick={(e) => {
                  e.stopPropagation();
                  api("/journal/verify").then(setChain);
                }}
              >
                Проверить цепочку хешей
              </Button>
            ),
            children: (
              <>
                {chain && (
                  <Alert
                    style={{ marginBottom: 12 }}
                    type={chain.ok ? "success" : "error"}
                    showIcon
                    message={chain.ok ? `Цепочка цела: проверено записей — ${chain.checked}` : `Цепочка нарушена: ${chain.reason}`}
                  />
                )}
                <Table
                  size="small"
                  rowKey="seq"
                  pagination={false}
                  dataSource={p.journal}
                  columns={[
                    { title: "№", dataIndex: "seq", width: 56 },
                    { title: "Время", dataIndex: "created_at", width: 90, render: (v) => dayjs(v).format("HH:mm:ss") },
                    {
                      title: "Кто",
                      dataIndex: "actor_kind",
                      width: 100,
                      render: (v: keyof typeof ACTOR_TITLES) => ACTOR_TITLES[v] ?? v,
                    },
                    {
                      title: "Действие",
                      dataIndex: "action",
                      render: (v: string, r) => (
                        <span>
                          {ACTION_TITLES[v] ?? v}
                          {r.action === "status" && ` → ${STAGES.find((s) => s.key === r.decision)?.title ?? r.decision}`}
                          {r.prompt_version && (
                            <Typography.Text type="secondary"> · {r.prompt_version}, {r.model}</Typography.Text>
                          )}
                        </span>
                      ),
                    },
                    {
                      title: "₽",
                      dataIndex: "cost_rub",
                      width: 80,
                      align: "right",
                      render: (v) => (v ? Number(v).toFixed(2) : ""),
                    },
                    {
                      title: "Хеш",
                      dataIndex: "hash",
                      width: 110,
                      render: (v: string) => <Typography.Text code>{v.slice(0, 10)}</Typography.Text>,
                    },
                  ]}
                />
              </>
            ),
          },
        ]}
      />
      {me?.role === "initiator" && p.status === "justification_review" && (
        <Alert type="info" showIcon message="Обоснование утверждает контрактный управляющий" />
      )}
    </div>
  );
}
