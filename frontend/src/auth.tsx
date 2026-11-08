// Кто вошёл: GET /api/auth/me при запуске; вход и выход. Компании песочницы — для подписей «кто прислал».
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, type Company, type Me } from "./api";

interface AuthState {
  me: Me | null;
  loading: boolean;
  companies: Record<number, Company>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [companies, setCompanies] = useState<Record<number, Company>>({});

  const loadCompanies = useCallback(async () => {
    const list = await api<Company[]>("/companies");
    setCompanies(Object.fromEntries(list.map((c) => [c.id, c])));
  }, []);

  useEffect(() => {
    api<Me>("/auth/me")
      .then(async (m) => {
        setMe(m);
        await loadCompanies();
      })
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401)) console.error(e);
        setMe(null);
      })
      .finally(() => setLoading(false));
  }, [loadCompanies]);

  const login = useCallback(
    async (email: string, password: string) => {
      const m = await api<Me>("/auth/login", { body: { email, password } });
      setMe(m);
      await loadCompanies();
    },
    [loadCompanies],
  );

  const logout = useCallback(async () => {
    await api("/auth/logout", { method: "POST" });
    setMe(null);
    setCompanies({});
  }, []);

  return (
    <AuthContext.Provider value={{ me, loading, companies, login, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth вне AuthProvider");
  return ctx;
}

/** Название компании по id; своя — «вы». */
export function useCompanyName() {
  const { companies, me } = useAuth();
  return (id: number | null | undefined) => {
    if (id === null || id === undefined) return "—";
    const name = companies[id]?.name ?? `Компания ${id}`;
    return id === me?.company_id ? `${name} (вы)` : name;
  };
}
