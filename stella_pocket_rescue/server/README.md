# Сервер для удаленного доступа к коробке

Коробка Stella Pocket сама подключается к вашему серверу, как только у нее появляется интернет
(кабель к роутеру или телефон по USB в режиме модема). Белый IP у коробки и проброс портов на роутере не нужны.

```
Телефон где угодно ──https──▶ ваш сервер (nginx + сертификат Let's Encrypt)
                                 ДОМЕН_САЙТА    → рекламный сайт (копия папки site/)
                                 ДОМЕН_КОРОБКИ  → 127.0.0.1:18080 ──SSH-туннель──▶ коробка
                                                  если коробка не в сети: страница «коробка не в сети»
```

Без интернета все то же самое открывается рядом с коробкой: в Wi-Fi SOS-STELLA-RESCUE коробка сама отвечает
на оба домена.

## Что нужно

- сервер с Ubuntu или Debian, nginx и OpenSSH 7.8 или новее (на сервере может уже работать что угодно);
- два домена, у обоих запись A указывает на IP сервера (например `box.example.kz` и `example.kz`);
- открытые порты 80 и 443 (сайт) и порт SSH (обычно 22).

## Тестовая версия без коробки

Если коробку пока не хочется обновлять, на сервере можно запустить тестовую версию. Там работают чат,
консоль спасателя, страница настроек, проверка узла и рекламный сайт. Вызовы в ней учебные, ИИ отвечает
по правилам, вверху каждой страницы плашка «Тестовая версия. Это не служба спасения: звоните 112».
Кнопки настроек только показываются. Раз в сутки версия начинается заново, с чистой базой.

На сервере, в папке проекта `stella_pocket_rescue`:

```
sudo bash server/stella-server.sh install --box-domain box.example.kz --promo-domain example.kz --email вы@почта.kz
sudo bash server/stella-server.sh demo on
```

Первая команда настраивает домены и сертификат (ключ коробки пока не нужен). Вторая ставит тестовую
версию и печатает адреса, PIN консоли и пароль настроек. Показать их снова: `demo status`.

Когда будете подключать настоящую коробку, сначала выключите тест: `sudo bash server/stella-server.sh demo off`.

## Настройка по шагам

1. **На коробке** (по SSH или с клавиатурой):

   ```
   sudo stella remote key
   ```

   Команда покажет ключ коробки вида `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA stella@orangepi` (длинная строка). Он не секретный.

2. **На сервере.** Скачайте проект (архив с GitHub), распакуйте и в его папке `stella_pocket_rescue` выполните:

   ```
   sudo bash server/stella-server.sh check --box-domain box.example.kz --promo-domain example.kz
   sudo bash server/stella-server.sh install --box-domain box.example.kz --promo-domain example.kz \
        --box-key 'ключ из шага 1' --email вы@почта.kz
   ```

   `check` ничего не меняет, только проверяет: nginx, DNS, sshd, не занят ли домен другим сайтом.
   `install` создает пользователя `stella-tunnel` (вход только по ключу коробки, без пароля и оболочки),
   кладет рекламный сайт в `/var/www/stella-site`, получает сертификат и пишет один файл nginx
   `stella-rescue.conf`. В конце скрипт напечатает строку `STELLA-PAIR`.

3. **На коробке:**

   ```
   sudo stella remote pair 'STELLA-PAIR строка из шага 2'
   sudo stella remote on
   sudo stella tls sync
   ```

   `remote on` включает туннель (он поднимается сам после перезагрузки и при смене интернета).
   `tls sync` забирает сертификат, чтобы домены открывались по HTTPS и без интернета.

4. Откройте `https://box.example.kz/admin` с телефона по мобильному интернету.
   Пароль администратора показывает команда на коробке `sudo stella admin password`.

## Что может ключ коробки на сервере

Только держать туннель на `127.0.0.1:18080` (и `127.0.0.1:18022` для SSH, если включить `stella remote ssh on`)
и выполнить одну из трех команд: `ping`, `reset` (снять зависший старый туннель), `certs` (отдать сертификат).
Ни оболочки, ни других портов, ни чтения файлов сервера. Это задано в
`/var/lib/stella-tunnel/.ssh/authorized_keys` и проверено тестами.

## Частые случаи

**Домен уже настроен в nginx.** `check` покажет файл, где он указан. Либо уберите домен оттуда, либо добавьте
в свой блок `server` для домена коробки:

```
location / {
    proxy_pass http://127.0.0.1:18080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 130s;
}
```

и запустите `install` с другим, свободным доменом коробки.

**Оператор связи блокирует порт 22.** Добавьте в `/etc/ssh/sshd_config` вторую строку `Port 2222`,
перезапустите sshd (`sudo systemctl restart ssh`) и запустите `install` с `--ssh-port 2222`.

**В sshd задан AllowUsers или AllowGroups.** Добавьте туда `stella-tunnel`.

**nginx работает в Docker.** Скрипт рассчитан на nginx прямо на сервере. В Docker укажите в своем
reverse proxy адрес `host.docker.internal:18080` (или IP хоста) для домена коробки.

**Коробку переустановили.** На коробке `sudo stella remote key`, на сервере
`sudo bash server/stella-server.sh key 'новый ключ'`, на коробке `sudo stella remote on`.

## Другие команды

```
sudo bash server/stella-server.sh status      # на связи ли коробка, до какого числа сертификат
sudo bash server/stella-server.sh promo       # обновить рекламный сайт из папки site/
sudo bash server/stella-server.sh pair        # снова показать строку STELLA-PAIR
sudo bash server/stella-server.sh uninstall   # убрать все, что поставил скрипт
```
