// Обёртка страниц входа и регистрации: белая шапка с логотипом, форма на серой подложке, футер-строка.
import type { ReactNode } from "react";

import Logo, { BRAND_NAME } from "../components/Logo";

export default function AuthShell({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", background: "#fff" }}>
      <header style={{ borderBottom: "1px solid var(--c-border)" }}>
        <div style={{ maxWidth: 1584, margin: "0 auto", padding: "14px 20px 16px" }}>
          <Logo />
        </div>
      </header>
      <main style={{ flex: 1, display: "grid", placeItems: "center", padding: "40px 16px" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: aside ? "minmax(0, 480px) minmax(0, 420px)" : "minmax(0, 480px)",
            gap: 24,
            width: "100%",
            justifyContent: "center",
          }}
        >
          <div style={{ border: "1px solid var(--c-border)", borderRadius: 8, padding: 32, background: "#fff" }}>{children}</div>
          {aside && <div style={{ background: "var(--c-bg-subtle)", borderRadius: 8, padding: 32 }}>{aside}</div>}
        </div>
      </main>
      <footer
        style={{
          margin: 8,
          padding: "14px 24px",
          background: "var(--c-bg-dark)",
          border: "1px solid var(--c-border-dark)",
          borderRadius: 8,
          color: "#BCC6C3",
          fontSize: 12,
          display: "flex",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <span>© 2026 {BRAND_NAME}</span>
        <span>Прототип. Демо-режим: письма уходят только в почтовую песочницу</span>
      </footer>
    </div>
  );
}
