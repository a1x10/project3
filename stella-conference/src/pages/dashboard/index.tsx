import { useEffect, useState } from "react";
import { PageLayout } from "@/layouts";
import { getStellaConfig, StellaConfig } from "@/lib/functions/stella.api";

// Stella Conference dashboard: which Stella account / server / models are used
const Dashboard = () => {
  const [cfg, setCfg] = useState<StellaConfig | null>(null);
  const [status, setStatus] = useState<{ ready?: boolean; stt?: string; model?: string; error?: string } | null>(null);

  useEffect(() => {
    (async () => {
      const c = await getStellaConfig();
      setCfg(c);
      if (!c) return;
      try {
        const r = await fetch(c.server.replace(/\/+$/, "") + "/api/conf/status", { headers: { authorization: "Bearer " + c.token } });
        setStatus(await r.json());
      } catch (e) {
        setStatus({ error: e instanceof Error ? e.message : String(e) });
      }
    })();
  }, []);

  return (
    <PageLayout title="Stella Conference" description="Помощник на созвонах: слушает разговор, показывает текст и подсказывает ответы">
      <div className="rounded-lg border p-4 space-y-2 text-sm">
        {cfg ? (
          <>
            <div>Аккаунт Stella: <b>{cfg.user || "—"}</b></div>
            <div>Сервер: {cfg.server}</div>
            {status?.ready ? (
              <>
                <div className="text-green-600">✓ Модели Stella подключены</div>
                <div>Ответы: {status.model} · Распознавание речи: {status.stt}</div>
              </>
            ) : (
              <div className="text-amber-600">
                ⚠ {status?.error || (status ? "На сервере не задан ключ Gemini для конференций (установщик с GEMINI=1)" : "Проверяю сервер…")}
              </div>
            )}
          </>
        ) : (
          <div className="text-amber-600">
            ⚠ Нет аккаунта Stella. Откройте Stella.exe и включите переключатель «Конференция».
          </div>
        )}
      </div>
      <div className="rounded-lg border p-4 text-sm text-muted-foreground space-y-1">
        <div className="font-medium text-foreground">Как пользоваться</div>
        <div>• Панель сверху экрана: напишите вопрос или нажмите на микрофон / звук системы.</div>
        <div>• «Звук системы» — слушает собеседников (Zoom, Meet, Teams, Telegram) и подсказывает ответ.</div>
        <div>• Скриншот — Stella объяснит то, что на экране.</div>
        <div>• Говорите в наушниках и предупреждайте участников, что разговор расшифровывается.</div>
      </div>
    </PageLayout>
  );
};

export default Dashboard;
