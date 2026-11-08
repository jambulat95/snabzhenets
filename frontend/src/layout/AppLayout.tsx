// Каркас кабинета (раздел 3.7): меню слева по роли, белая шапка с компанией, ролью и песочницей, футер-строка
import { useEffect, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Badge, Button, Layout, Menu } from "antd";
import {
  AlertOutlined,
  AppstoreOutlined,
  AuditOutlined,
  CompassOutlined,
  BarChartOutlined,
  FileAddOutlined,
  GoldOutlined,
  LogoutOutlined,
  SettingOutlined,
  ShopOutlined,
  ToolOutlined,
} from "@ant-design/icons";

import { api, type Escalation } from "../api";
import { useAuth } from "../auth";
import { BUYER_ROLES, ROLE_TITLES, SUPPLIER_ROLES } from "../labels";
import Logo, { BRAND_NAME } from "../components/Logo";
import StatusTag from "../components/StatusTag";

const { Sider, Header, Content, Footer } = Layout;

export default function AppLayout() {
  const { me, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [waiting, setWaiting] = useState(0);

  // Счётчик «Ждут меня»: раз в 15 секунд
  useEffect(() => {
    let alive = true;
    const load = () =>
      api<Escalation[]>("/escalations?status=open")
        .then((list) => alive && setWaiting(list.length))
        .catch(() => undefined);
    load();
    const t = setInterval(load, 15000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (!me) return null;
  const role = me.role;

  const items = [
    { key: "/start", icon: <CompassOutlined />, label: <Link to="/start">С чего начать</Link> },
    { key: "/deals", icon: <AppstoreOutlined />, label: <Link to="/deals">Сделки</Link> },
    {
      key: "/escalations",
      icon: <AlertOutlined />,
      label: (
        <Link to="/escalations" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
          <span>Ждут меня</span>
          {waiting > 0 && <Badge count={waiting} color="#F13535" title={`Ждут вашего решения: ${waiting}`} />}
        </Link>
      ),
    },
    ...(role === "buyer"
      ? [{ key: "/new-request", icon: <FileAddOutlined />, label: <Link to="/new-request">Новый запрос</Link> }]
      : []),
    // Витрина (US-26, Э13): товары поставщиков площадки с ценой для своей компании
    ...(role === "buyer"
      ? [{ key: "/showcase", icon: <GoldOutlined />, label: <Link to="/showcase">Витрина</Link> }]
      : []),
    ...(SUPPLIER_ROLES.includes(role)
      ? [{ key: "/catalog", icon: <ShopOutlined />, label: <Link to="/catalog">Каталог</Link> }]
      : []),
    ...(me.company_id !== null
      ? [{ key: "/rules", icon: <SettingOutlined />, label: <Link to="/rules">Правила и мандат</Link> }]
      : []),
    { key: "/journal", icon: <AuditOutlined />, label: <Link to="/journal">Журнал</Link> },
    // Счётчик считает операции поставщика (матрица ОП, ТЗ §8): у покупателя он всегда пуст
    ...(me.company_id !== null && !BUYER_ROLES.includes(role)
      ? [{ key: "/autonomy", icon: <BarChartOutlined />, label: <Link to="/autonomy">Счётчик автономии</Link> }]
      : []),
    ...(role === "operator"
      ? [{ key: "/operator", icon: <ToolOutlined />, label: <Link to="/operator">Песочница</Link> }]
      : []),
  ];
  const selected = items.map((i) => i.key).find((k) => location.pathname.startsWith(k)) ?? "/deals";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider
        width={240}
        theme="light"
        style={{
          borderRight: "1px solid var(--c-border)",
          position: "sticky",
          top: 0,
          height: "100vh",
          overflow: "auto",
        }}
      >
        <div style={{ padding: "18px 20px 22px" }}>
          <Logo to="/start" compact />
        </div>
        <Menu className="app-menu" mode="inline" selectedKeys={[selected]} items={items} style={{ borderInlineEnd: 0, paddingInline: 8 }} />
      </Sider>
      <Layout style={{ minWidth: 0 }}>
        <Header
          style={{
            borderBottom: "1px solid var(--c-border)",
            display: "flex",
            justifyContent: "flex-end",
            alignItems: "center",
            gap: 16,
            paddingInline: 24,
            lineHeight: "normal",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
            <span style={{ fontSize: 14, lineHeight: "20px", fontWeight: 500, color: "var(--c-text-primary)" }}>
              {me.company_name ?? "Площадка"}
            </span>
            <span style={{ fontSize: 12, lineHeight: "16px", color: "var(--c-text-secondary)" }}>
              {me.full_name === ROLE_TITLES[role] ? me.full_name : `${me.full_name} · ${ROLE_TITLES[role] ?? role}`}
            </span>
          </div>
          <StatusTag
            outlined
            tooltip="Своя песочница: сделки, правила и журнал не пересекаются с другими. Данные вымышленные"
          >
            Песочница {me.sandbox}
          </StatusTag>
          <Button
            className="btn-outlined"
            icon={<LogoutOutlined />}
            onClick={async () => {
              await logout();
              navigate("/");
            }}
          >
            Выйти
          </Button>
        </Header>
        <Content style={{ padding: 24, minWidth: 0, overflowX: "auto" }}>
          <div style={{ maxWidth: 1584, margin: "0 auto" }}>
            <Outlet />
          </div>
        </Content>
        <Footer
          style={{
            margin: "0 8px 8px",
            padding: "14px 24px",
            background: "var(--c-bg-dark)",
            border: "1px solid var(--c-border-dark)",
            borderRadius: 8,
            color: "#BCC6C3",
            fontSize: 12,
            lineHeight: "16px",
            display: "flex",
            justifyContent: "space-between",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <span>© 2026 {BRAND_NAME}</span>
          <span>Прототип для RLT.Startup. Компании и данные вымышленные</span>
        </Footer>
      </Layout>
    </Layout>
  );
}
