import { Theme, AlwaysOnTopToggle, AutostartToggle } from "./components";
import { PageLayout } from "@/layouts";

const Settings = () => {
  return (
    <PageLayout title="Settings" description="Manage your settings">
      {/* Theme */}
      <Theme />

      {/* Autostart Toggle */}
      <AutostartToggle />

      {/* Always On Top Toggle */}
      <AlwaysOnTopToggle />

      {/* About / legal notices (GPL-3.0 §5: appropriate legal notices) */}
      <div className="rounded-lg border p-4 text-sm text-muted-foreground space-y-1">
        <div className="font-medium text-foreground">О программе</div>
        <div>Stella Conference — помощник на созвонах для Stella. Модели: Gemini (Antigravity) через ваш сервер Stella.</div>
        <div>
          Основано на Pluely © Srikanth Nani (https://github.com/iamsrikanthnani/pluely), изменено для Stella.
        </div>
        <div>
          Лицензия GNU GPL v3.0: программа распространяется без каких-либо гарантий; вы можете распространять и изменять её на условиях GPL-3.0.
          Исходный код этой версии: https://github.com/a1x10/project3 (папка stella-conference).
        </div>
      </div>
    </PageLayout>
  );
};

export default Settings;
