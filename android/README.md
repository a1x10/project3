# Android: телефон и очки

Открыть папку `android/` в Android Studio (Hedgehog+), Sync, запустить модули:

- **phone** — мост: уведомления WhatsApp/Telegram/SMS → сервер, ответы из шторки (RemoteInput),
  SSE-канал 24/7 (foreground-сервис), голосовые WhatsApp через специальные возможности.
- **glasses** — полноэкранный WebView с HUD (`/hud`): меню, камера, голос, лица, совещание, 3D.

## Телефон: порядок настройки
1. «Сохранить и запустить» (адрес `https://…` и `STELLA_API_KEY`).
2. Доступ к уведомлениям → включить Stella.
3. Специальные возможности → Stella (нужно для голосовых в WhatsApp).
4. Поверх других окон → разрешить (иначе Android не даст открыть WhatsApp из фона).
5. Отключить оптимизацию батареи для приложения.

## Ограничения
- Приложения не собирались и не запускались (в среде разработки нет Android SDK) — возможны мелкие ошибки компиляции.
- Текстовый ответ работает, если у уведомления есть кнопка «Ответить» (WhatsApp, Telegram, Google Messages).
- Голосовое — автоматизация экрана WhatsApp: может сломаться после обновления приложения.
- Android 15 не даёт запускать foreground-сервис dataSync из BOOT_COMPLETED: после перезагрузки откройте приложение один раз.
- Rokid CXR SDK не подключён: очки ходят на сервер напрямую. Если очки не ставят обычный APK — откройте `https://<сервер>/hud` в их браузере.

## Установка на очки Rokid (YodaOS-Sprite) через ADB
Сборка: `./gradlew :glasses:assembleDebug` → `glasses/build/outputs/apk/debug/stella-glasses.apk`.
Пакет: `com.stels.stella`, главная активность `.MainActivity` (объявлена и как LAUNCHER, и как HOME).

```powershell
cd C:\platform-tools
.\adb devices                                   # должно быть "device" (иначе разрешите отладку в очках)
.\adb install -r stella-glasses.apk
.\adb shell am start -n com.stels.stella/.MainActivity
```
Первый запуск спросит доступ к камере и микрофону, затем адрес сервера (кнопка Menu — сменить адрес).

Стелла вместо родного меню (откат: `pm enable com.rokid.glass.launcher`):
```powershell
.\adb shell pm disable-user --user 0 com.rokid.glass.launcher
.\adb shell cmd package set-home-activity com.stels.stella/.MainActivity
```
Логи: `.\adb logcat | Select-String "Stella"` (тег `Stella`). Удаление: `.\adb shell pm uninstall com.stels.stella`.
Имя родного лончера (`com.rokid.glass.launcher`) проверьте через `pm list packages | Select-String rokid` — оно может отличаться.

## Очки без клавиатуры: адрес и ключ зашиваются в APK
Создайте файл `android/local.properties` (в git не попадает) и добавьте строки:
```
stella.url=https://stellaalex.duckdns.org
stella.key=ВАШ_STELLA_API_KEY
```
Пересоберите `glasses` — приложение откроется сразу с подключением, вводить ничего не нужно.
Ключ лежит внутри APK: не выкладывайте его в открытый доступ.
