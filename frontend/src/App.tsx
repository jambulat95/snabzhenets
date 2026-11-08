import { Navigate, Route, Routes } from "react-router-dom";
import { Spin } from "antd";

import { useAuth } from "./auth";
import AppLayout from "./layout/AppLayout";
import Login from "./pages/Login";
import Procurements from "./pages/Procurements";
import NewProcurement from "./pages/NewProcurement";
import ProcurementPage from "./pages/Procurement";

export default function App() {
  const { me, loading } = useAuth();
  if (loading) {
    return (
      <div style={{ display: "grid", placeItems: "center", height: "100vh" }}>
        <Spin size="large" />
      </div>
    );
  }
  if (!me) return <Login />;
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/procurements" replace />} />
        <Route path="/procurements" element={<Procurements />} />
        <Route path="/procurements/new" element={<NewProcurement />} />
        <Route path="/procurements/:id" element={<ProcurementPage />} />
        <Route path="*" element={<Navigate to="/procurements" replace />} />
      </Route>
    </Routes>
  );
}
