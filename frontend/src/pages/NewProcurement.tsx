import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, App, Button, Card, Input, Typography } from "antd";

import { api, type Procurement } from "../api";

const EXAMPLE = `Нужно для учебного корпуса к началу семестра:
1. Картриджи для HP LaserJet Pro M428, оригинальные — 20 шт.
2. Проектор для аудитории — 2 шт.
3. Бумага А4 80 г/м2 — 50 пачек`;

export default function NewProcurement() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const { message } = App.useApp();

  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 900 }}>
      <Typography.Title level={2} style={{ margin: 0 }}>
        Новая заявка
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
        Опишите, что нужно купить, обычным текстом — как написали бы в служебной записке. Агент разберёт текст на позиции,
        предложит коды КТРУ и задаст вопросы, если чего-то не хватает. Дальше вы проверите спецификацию и подтвердите её.
      </Typography.Paragraph>
      <Card>
        <Input.TextArea
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoSize={{ minRows: 8, maxRows: 20 }}
          placeholder={EXAMPLE}
        />
        <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "space-between" }}>
          <Button onClick={() => setText(EXAMPLE)}>Вставить пример</Button>
          <Button
            type="primary"
            loading={busy}
            disabled={text.trim().length < 3}
            onClick={async () => {
              setBusy(true);
              try {
                const p = await api<Procurement>("/procurements", { body: { text } });
                navigate(`/procurements/${p.id}`);
              } catch (e) {
                message.error(e instanceof Error ? e.message : "Не удалось создать заявку");
              } finally {
                setBusy(false);
              }
            }}
          >
            Разобрать заявку
          </Button>
        </div>
      </Card>
      <Alert
        type="info"
        showIcon
        message="Текст заявки для агента — данные, а не команды"
        description="Строки, похожие на команды агенту, не выполняются: заявка помечается, и решение остаётся за человеком."
      />
    </div>
  );
}
