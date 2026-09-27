# Харденинг Nginx на уровне системы: systemd-юнит, SELinux, AppArmor

> Помимо конфигурации самого Nginx (см. [Руководство по безопасности Nginx](./nginx_security_guide.md)) процесс и файлы демона защищаются на уровне ОС: **изоляция окружения через systemd-юнит**, а также **SELinux** (RHEL-семейство) или **AppArmor** (Debian/Ubuntu). Это отдельный слой защиты: даже при компрометации воркер-процесса ему будет затруднено чтение файловой системы, сетевые запросы за пределы сайта и поднятие привилегий. Полный справочник всех systemd-директив — в [Харденинге systemd](../../../Linux/Security/Concepts/systemd_security.md); здесь — только практически значимые для Nginx настройки и подводные камни.

## Определения

**systemd unit (юнит)** — файл описания сервиса (`.service`), управляющий запуском, окружением и ограничениями процесса. Через [ограничения системы (system calls, файлы, процессы)](../../../Linux/Security/Concepts/systemd_security.md) юнит изолирует демон без изменения его кода.

**ProtectSystem / ProtectHome / PrivateTmp** — systemd-директивы, делающие корневую ФС и домашние каталоги **read-only** для процесса (`ProtectSystem=strict` монтирует всю ФС, кроме явно исключённых путей) и изолирующие `/tmp`.

**CapabilityBoundingSet / AmbientCapabilities** — ограничение [Linux capabilities](../../../Linux/Security/Mechanisms/Capabilities.md): bounding set — максимальный набор, который процесс может получить; ambient — способность, остающаяся у процесса на протяжении всего жизненного цикла (необходима, чтобы не-root процесс мог забиндить порт 443).

**SELinux (Security-Enhanced Linux)** — модуль ядра, реализующий мандатное управление доступом (MAC) по меткам (domain `httpd_t`, типы `http_port_t`, `httpd_sys_content_t`). На RHEL-семействе демон Nginx работает в SELinux-домене `httpd_t` (общий с httpd), и его ограничения регулируются булевыми переключателями `httpd_*`.

**AppArmor** — альтернативная MAC-реализация в Debian/Ubuntu, ограничивающая процесс по файлам/сетям, которые он может посещать (профили вместо доменов). По умолчанию Nginx в свежей Ubuntu обычно работает **без профиля** (`unconfined`).

**MAC (Mandatory Access Control)** — принудительное управление доступом, которое администратор не может обойти, находясь внутри процесса; в отличие от DAC (права `rwx`), владелец не может «раздать» доступ сверх мандата.

## Основные концепции

### Привилегии процесса Nginx

- **Мастер-процесс** запускается от `root` (пакетные сборки): ему нужны `CAP_NET_BIND_SERVICE` (порт 80/443) и `CAP_SETUID`/`CAP_SETGID` (понижение привилегий воркеров до `user` из `nginx.conf`).
- **Воркер-процессы** понижаются до `www-data` (Debian/Ubuntu) или `nginx` (RHEL) — это и есть первая линия защиты.
- Два подхода к харденингу: (A) оставить root-мастер, но изолировать окружение и файлы; (B) запустить всё непривилегированным пользователем с одной capability — чище, но требует правки путей и владельцев.

### Two layers: юнит ≠ MAC-политика

| Слой | Что закрывает | Инструмент |
| :--- | :--- | :--- |
| systemd-юнит | изоляция окружения (ФС, /tmp, syscalls, процессы, capabilities) | директтивы `Protect*`, `Restrict*`, `User=`, `NoNewPrivileges` |
| SELinux/AppArmor | доступ к файлам, сокетам, портам «своими» процессами | булев `httpd_*`, контексты `httpd_sys_content_t`, `semanage port` |
| конфигурация Nginx | таймауты, лимиты, заголовки, интерфейсы `listen` | `worker_rlimit_*`, `listen 127.0.0.1:80`, `server_tokens` (см. [nginx_security_guide.md](./nginx_security_guide.md)) |

### Порт 80/443 без root

При привязке к привилегированным портам не-root-процесс использует capability `CAP_NET_BIND_SERVICE`. В systemd это через `AmbientCapabilities=CAP_NET_BIND_SERVICE` + `CapabilityBoundingSet=CAP_NET_BIND_SERVICE` — детали см. в [Capabilities](../../../Linux/Security/Mechanisms/Capabilities.md).

## Практические сценарии

### Сценарий 1. Харденинг стандартного юнита (основной)

Для пакетной установки (Debian/RHEL) — изолируем окружение, не ломая штатный root-мастер. Проверьте заводской юнит: `systemctl cat nginx`.

`/etc/systemd/system/nginx.service.d/hardening.conf`:

```ini
[Service]
# Файловая система
ProtectSystem=strict
ReadWritePaths=/var/log/nginx /var/cache/nginx /var/lib/nginx /run/nginx.pid
ProtectHome=true
PrivateTmp=true
PrivateDevices=true

# Ядро и syscalls
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
LockPersonality=true
RestrictRealtime=true
RestrictSUIDSGID=true
NoNewPrivileges=true

# Сети: только HTTP-проксирование (+ AF_UNIX для fastcgi_pass и PHP-FPM socket)
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
```

Применение и проверка слоя:

```bash
sudo systemctl daemon-reload && sudo systemctl restart nginx
curl -I https://example.com/          # сервис жив
systemctl is-enabled nginx            # автозапуск
journalctl -u nginx -n 50             # лог ошибок юнита
```

Замечания:
- `RestrictAddressFamilies` **обязательно** должен содержать `AF_UNIX`, иначе `fastcgi_pass unix:/run/php/php*.sock` и `proxy_pass` к unix-сокету перестанут работать.
- Если кэш/темп-пути других, уточните фактическое значение: `nginx -T 2>/dev/null | grep -E 'temp_path|proxy_cache_path'`.
- `NoNewPrivileges=true` не конфликтует с `user`-директивой Nginx: мастер и так root, понижение воркеров делается через `setuid()`.

### Сценарий 2. Полностью непривилегированный запуск (`User=nginx`)

Максимальная изоляция: даже мастер не root. Требует правки путей и владельцев.

```ini
[Service]
User=nginx
Group=nginx
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
RuntimeDirectory=nginx
ProtectSystem=strict
ReadWritePaths=/var/cache/nginx /var/lib/nginx /var/log/nginx
PrivateTmp=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
```

Обязательные изменения конфигурации:

```nginx
# /etc/nginx/nginx.conf — без user-директивы (уже бежит как nginx)
pid /run/nginx/nginx.pid;   # RuntimeDirectory создаёт /run/nginx
```

```bash
# Правки владельцев
sudo chown -R nginx:nginx /var/cache/nginx /var/lib/nginx /var/log/nginx
sudo systemctl daemon-reload && sudo systemctl restart nginx
```

Подводные камни:
- `logrotate` и скрипты, пишущие в `/var/log/nginx` от root, продолжат работать (ротация переименовывает и **переоткрывает** файл сигналом `USR1` — прав у пользователя достаточно).
- При `Restart=always` проверьте конфигурацию юнита без протечек secret через `EnvironmentFile`.
- Воркеры наследуют ambient-способность, поэтому порты 80/443 биндятся мастером без root.

### Сценарий 3. SELinux на RHEL-семействе (домен httpd_t)

Демон Nginx на RHEL/Rocky/Alma работает в домене `httpd_t`; его «разрешения» включаются булевыми переключателями:

```bash
# Nginx как reverse proxy ходит на апстримы (по умолчанию ЗАПРЕЩЕНО)
sudo setsebool -P httpd_can_network_connect on

# Доступ к БД (если приложение через nginx)
sudo setsebool -P httpd_can_network_connect_db on

# Переоткрытие логов сигналом USR1 (graceful reload logrotate)
sudo setsebool -P httpd_graceful_shutdown on

# Кастомный порт для listen (80/443 уже разрешены)
sudo semanage port -a -t http_port_t -p tcp 8080

# Кастомный корень сайта — контекст httpd_sys_content_t
sudo semanage fcontext -a -t httpd_sys_content_t "/srv/www(/.*)?"
sudo restorecon -Rv /srv/www
```

Разведка и диагностика:

```bash
sudo getsebool -a | grep httpd           # текущие булевы
sudo semanage fcontext -l | grep -E 'nginx|httpd_sys'   # контексты путей
sudo ls -Z /etc/nginx/nginx.conf          # контекст файла
sudo ausearch -m avc -ts recent           # события нарушений
sudo audit2why -a                          # человекопонятное объяснение
sudo sealert -a /var/log/audit/audit.log   # подробный отчёт
sudo setenforce 0                          # временная проверка «виноват ли SELinux»
```

Типичные симптомы блокировки SELinux: `403 Forbidden` при корректных правах файла, `(13) Permission denied` при `connect()` на апстрим, «нервная» работа PHP-FPM через network-сокет, пока `httpd_can_network_connect` выключен. Внимание: `setenforce 0` — недопустимо для продакшена, это только диагностика. Полная теория — в [SELinux](../../../Linux/Security/Mechanisms/SELinux.md).

### Сценарий 4. AppArmor на Debian/Ubuntu

Свежие Ubuntu/Debian запускают Nginx без ограничений:

```bash
sudo aa-status | grep -i nginx    # пусто → unconfined
sudo cat /sys/kernel/security/apparmor/profiles 2>/dev/null | wc -l
```

Если требуется профиль (типично для высоких требований безопасности):

```bash
sudo aa-genprof nginx   # интерактивная генерация из фактических обращений
sudo aa-logprof         # дополнение профиля по логам нарушений
sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.nginx   # пересборка
```

Минимальный профиль покрывает: чтение `/etc/nginx/**` и сертификатов, запись в `/var/log/nginx/**` и `/var/cache/nginx/**`, network-доступ (`network inet stream`), unix-сокеты, `capability net_bind_service` и чтение openssl/socket-библиотек. Диагностика: `dmesg | grep -i apparmor` показывает `apparmor="DENIED"`. Теория и синтаксис — в [AppArmor](../../../Linux/Security/Mechanisms/AppArmor.md).

## Операции и команды

```bash
# Оценка уровня харденинга юнита (шрифт: score)
systemd-analyze security nginx
systemctl cat nginx                        # полный применяемый юнит + drop-ins
systemctl show nginx -p ProtectSystem -p NoNewPrivileges -p RestrictAddressFamilies

# Capabilities реально удержанные процессами
grep -E 'Cap(Inh|Prm|Eff|Bnd)' /proc/$(pgrep -n nginx)/status
capsh --decode=$(grep CapInh /proc/$(pgrep -n nginx)/status | cut -f2)

# Проверка готовности после изменения юнита
sudo nginx -t && sudo systemctl restart nginx
curl -fsL https://example.com/ >/dev/null && echo OK
```

`systemd-analyze security` выводит рейтинг (`OK`/`EXPOSED`) по каждой директиве — ориентир для итераций харденинга, но «скрытые» риски (случайный drop-in, `EnvironmentFile` с режимом 0644) он не видит.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| После drop-in сервер не поднялся: `Failed to set up mount namespacing` | `ProtectSystem=strict` без `ReadWritePaths` для путей записи | добавить `ReadWritePaths=/var/log/nginx /var/cache/nginx ...`; проверить, что они существуют |
| `upstream connect: Permission denied (13)` при работающем юните | SELinux-булев `httpd_can_network_connect` выключен | `setsebool -P httpd_can_network_connect on` |
| `listen 8080` → `Permission denied` на RHEL | порт вне контекста `http_port_t` | `semanage port -a -t http_port_t -p tcp 8080` |
| fastcgi/PHP-FPM перестал отвечать | `RestrictAddressFamilies` без `AF_UNIX` | добавить `AF_UNIX` в список |
| `403 Forbidden` при правах 644 | контекст файла не `httpd_*` (SELinux) или профиль AppArmor | `restorecon -Rv` / `aa-logprof` |
| `nginx: [emerg] bind() to 0.0.0.0:80 failed` в `User=n.` режиме | не хватает ambient-капацити на порт | `AmbientCapabilities=CAP_NET_BIND_SERVICE` + рестарт |
| `(13) Permission denied` на `/run/php/*.sock` | процесс юзера не имеет доступа к сокету по путям `ProtectHome`/владельцам | согласовать `User=`/чтение сокета; проверить права `/run/php` |
| audit: `denied { name_connect }` для исходящих | SELinux блокирует исходящее соединение домена | `audit2why -a` → установить нужный булев `httpd_*` |

## Лучшие практики

1. **Изменяйте юнит через drop-in** (`/etc/systemd/system/nginx.service.d/`), не трогая файл пакета — переживёт обновления.
2. **Начинайте с `Protect*` и `NoNewPrivileges`** — они дают наибольший эффект при минимальном риске; `CapabilityBoundingSet` добавляйте только после тестов.
3. **Одна система — один MAC.** На RHEL используйте SELinux, на Debian/Ubuntu — AppArmor; не включайте оба.
4. **Никогда не отключайте SELinux/AppArmor в проде** навсегда — правильнее `setsebool -P`/`aa-logprof`; `setenforce 0` — только для диагностики.
5. **Согласуйте слои**: и `user`-директива Nginx, и `User=` юнита, и владельцы файлов должны указывать на одного пользователя.
6. **Проверяйте цепочку запроса целиком**: `curl -I`, `journalctl -u nginx`, `ausearch -m avc`/`dmesg | grep apparmor` — это три угла одного сценария.
7. Держите юнит и контексты под версионированием вместе с конфигами Nginx (см. [nginx_setup.md](../Core/nginx_setup.md#управление-конфигурацией-через-git-и-cicd)).

## Дополнительная информация

Справочная база по всем связанным механизмам лежит в разделе Linux Security; здесь — только практические настройки для Nginx.

### См. также

- [Харденинг systemd](../../../Linux/Security/Concepts/systemd_security.md) — полный справочник директив `Protect*/Restrict*/SystemCallFilter`.
- [Linux Capabilities](../../../Linux/Security/Mechanisms/Capabilities.md) — семантика bounding/ambient/inherited для не-root запуска.
- [SELinux](../../../Linux/Security/Mechanisms/SELinux.md) и [AppArmor](../../../Linux/Security/Mechanisms/AppArmor.md) — теория MAC, контексты и профили.
- [Руководство по безопасности Nginx](./nginx_security_guide.md) — прикладной слой: заголовки, TLS, лимиты, минимизация модулей.