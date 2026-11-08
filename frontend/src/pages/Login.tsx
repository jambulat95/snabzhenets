import { useState } from "react";
import { Alert, Button, Form, Input, Typography } from "antd";

import { useAuth } from "../auth";
import AuthShell from "../layout/AuthShell";

export default function Login() {
  const { login } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <AuthShell
      aside={
        <div>
          <Typography.Title level={4} style={{ marginTop: 0 }}>
            Что умеет агент
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            Сотрудник описывает потребность обычным текстом. Агент составляет спецификацию с кодами КТРУ, находит поставщиков
            с опытом госконтрактов, собирает цены с доказательствами и готовит обоснование НМЦК по приказу № 567. Спецификацию
            и обоснование утверждает человек.
          </Typography.Paragraph>
        </div>
      }
    >
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        Вход
      </Typography.Title>
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
      <Form
        layout="vertical"
        onFinish={async (v: { email: string; password: string }) => {
          setBusy(true);
          setError(null);
          try {
            await login(v.email, v.password);
          } catch (e) {
            setError(e instanceof Error ? e.message : "Не удалось войти");
          } finally {
            setBusy(false);
          }
        }}
      >
        <Form.Item name="email" label="Почта" rules={[{ required: true, message: "Введите почту" }]}>
          <Input autoComplete="username" autoFocus />
        </Form.Item>
        <Form.Item name="password" label="Пароль" rules={[{ required: true, message: "Введите пароль" }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={busy} block>
          Войти
        </Button>
      </Form>
    </AuthShell>
  );
}
