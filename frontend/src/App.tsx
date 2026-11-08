import { Navigate, Route, Routes } from "react-router-dom";
import { Spin } from "antd";

import { useAuth } from "./auth";
import AppLayout from "./layout/AppLayout";
import Login from "./pages/Login";
import Deals from "./pages/Deals";
import DealPage from "./pages/Deal";
import Escalations from "./pages/Escalations";
import Journal from "./pages/Journal";
import Autonomy from "./pages/Autonomy";
import NewRequest from "./pages/NewRequest";
import Showcase from "./pages/Showcase";
import Catalog from "./pages/Catalog";
import Rules from "./pages/Rules";
import Operator from "./pages/Operator";
import Register from "./pages/Register";
import Start from "./pages/Start";
import Landing from "./pages/Landing";

export default function App() {
  const { me, loading } = useAuth();

  if (loading) {
    return (
      <div style={{ display: "grid", placeItems: "center", height: "100vh" }}>
        <Spin size="large" />
      </div>
    );
  }
  if (!me) {
    return (
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        {/* Прямая ссылка на экран кабинета: форма входа на том же адресе, после входа — сразу туда */}
        <Route path="*" element={<Login />} />
      </Routes>
    );
  }
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/start" replace />} />
        <Route path="/start" element={<Start />} />
        <Route path="/register" element={<Navigate to="/start" replace />} />
        <Route path="/login" element={<Navigate to="/start" replace />} />
        <Route path="/deals" element={<Deals />} />
        <Route path="/deals/:id" element={<DealPage />} />
        <Route path="/escalations" element={<Escalations />} />
        <Route path="/journal" element={<Journal />} />
        <Route path="/autonomy" element={<Autonomy />} />
        <Route path="/new-request" element={<NewRequest />} />
        <Route path="/new-request/:draftId" element={<NewRequest />} />
        <Route path="/catalog" element={<Catalog />} />
        <Route path="/showcase" element={<Showcase />} />
        <Route path="/rules" element={<Rules />} />
        <Route path="/operator" element={<Operator />} />
        <Route path="*" element={<Navigate to="/deals" replace />} />
      </Route>
    </Routes>
  );
}
