import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { App, Button, Card, Empty, Space, Table, Typography } from "antd";
import { FileAddOutlined } from "@ant-design/icons";
import dayjs from "dayjs";

import { api, type Procurement } from "../api";
import StatusTag from "../components/StatusTag";
import { STATUS_TONE } from "../labels";
import { useAuth } from "../auth";
import ConfirmAction from "../components/ConfirmAction";

export default function Procurements() {
  const [rows, setRows] = useState<Procurement[] | null>(null);
  const navigate = useNavigate();
  const { me } = useAuth();
  const { message } = App.useApp();

  useEffect(() => {
    const load = () => api<Procurement[]>("/procurements").then(setRows).catch(() => setRows([]));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Typography.Title level={2} style={{ margin: 0 }}>
          Заявки
        </Typography.Title>
        <Space>
          {me?.demo_mode && me.role !== "initiator" && (
            <ConfirmAction
              title="Сбросить демо-сценарий"
              okText="Сбросить"
              danger
              buttonText="Сбросить демо"
              onConfirm={async () => {
                await api("/demo/reset", { method: "POST" });
                setRows([]);
                message.success("Демо сброшено: заявок нет, учётки и поставщики на месте");
              }}
            >
              Удалятся все заявки, цены, письма, доказательства и журнал. Учётные записи, демо-поставщики и записанные
              данные (страницы магазинов, ответы моделей) останутся.
            </ConfirmAction>
          )}
          <Button type="primary" icon={<FileAddOutlined />} onClick={() => navigate("/procurements/new")}>
            Новая заявка
          </Button>
        </Space>
      </div>
      <Card>
        <Table<Procurement>
          rowKey="id"
          loading={rows === null}
          dataSource={rows ?? []}
          className="table-clickable"
          onRow={(r) => ({ onClick: () => navigate(`/procurements/${r.id}`) })}
          locale={{ emptyText: <Empty description="Заявок пока нет — опишите, что нужно купить" /> }}
          pagination={false}
          columns={[
            { title: "Номер", dataIndex: "number", width: 130, render: (v, r) => <Link to={`/procurements/${r.id}`}>{v}</Link> },
            { title: "Заявка", dataIndex: "title" },
            {
              title: "Этап",
              dataIndex: "status_title",
              width: 220,
              render: (v, r) => <StatusTag tone={STATUS_TONE[r.status]}>{v}</StatusTag>,
            },
            { title: "Создана", dataIndex: "created_at", width: 150, render: (v) => dayjs(v).format("DD.MM.YYYY HH:mm") },
          ]}
        />
      </Card>
    </div>
  );
}
