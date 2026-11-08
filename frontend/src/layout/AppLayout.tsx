// Каркас кабинета: меню слева, белая шапка с организацией и ролью, футер-строка. Каркас — из A2A Маркет.
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Button, Layout, Menu } from "antd";
import { FileAddOutlined, LogoutOutlined, UnorderedListOutlined } from "@ant-design/icons";

import { useAuth } from "../auth";
import Logo, { BRAND_NAME } from "../components/Logo";
import StatusTag from "../components/StatusTag";

const { Sider, Header, Content, Footer } = Layout;

export default function AppLayout() {
  const { me, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  if (!me) return null;

  const items = [
    { key: "/procurements/new", icon: <FileAddOutlined />, label: <Link to="/procurements/new">Новая заявка</Link> },
    { key: "/procurements", icon: <UnorderedListOutlined />, label: <Link to="/procurements">Заявки</Link> },
  ];
  const selected = location.pathname === "/procurements/new" ? "/procurements/new" : "/procurements";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider
        width={240}
        theme="light"
        style={{ borderRight: "1px solid var(--c-border)", position: "sticky", top: 0, height: "100vh", overflow: "auto" }}
      >
        <div style={{ padding: "18px 20px 22px" }}>
          <Logo to="/procurements" compact />
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
            <span style={{ fontSize: 14, lineHeight: "20px", fontWeight: 500, color: "var(--c-text-primary)" }}>{me.org_name}</span>
            <span style={{ fontSize: 12, lineHeight: "16px", color: "var(--c-text-secondary)" }}>
              {me.full_name.includes(me.role_title) ? me.full_name : `${me.full_name} · ${me.role_title}`}
            </span>
          </div>
          <StatusTag outlined tooltip="Письма уходят только в почтовую песочницу; данные ЕИС и магазинов — записанный срез">
            Демо-режим
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
          <div style={{ maxWidth: 1400, margin: "0 auto" }}>
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
          <span>Прототип. Расчёты и проверки по методике делает код; решения утверждает человек</span>
        </Footer>
      </Layout>
    </Layout>
  );
}
