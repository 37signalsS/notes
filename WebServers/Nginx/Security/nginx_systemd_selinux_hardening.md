# Харденинг Nginx на уровне системы: systemd-юнит, SELinux, AppArmor

**Актуально для:** Nginx 1.26+ (OSS/Plus) / 1.28+ – 1.30.x (Mainline), Angie 1.6+ / 1.12.x, systemd 245+ / 252+, Linux Kernel 5.15+ / 6.x (RHEL 8/9, Rocky/AlmaLinux 8/9, Debian 12, Ubuntu 22.04/24.04 LTS)

> Помимо прикладной конфигурации веб-сервера (TLS, заголовки безопасности, WAF, rate limiting — см. [Руководство по безопасности Nginx](./nginx_security_guide.md)), критически важна защита на уровне операционной системы. Изоляция окружения через директивы песочницы **systemd**, разграничение привилегий через **Linux Capabilities**, а также мандатный контроль доступа (**SELinux** в RHEL-семействе или **AppArmor** в Debian/Ubuntu) формируют рубеж эшелонированной обороны (Defense in Depth). Даже в случае успешной эксплуатации уязвимости в приложении или воркер-процессе Nginx злоумышленник не сможет получить доступ к чувствительным файлам ОС, модифицировать бинарные файлы или развить атаку по локальной сети.

## Определения

**systemd-юнит (Service Unit)** — декларативный файл конфигурации службы (`nginx.service`), управляющий жизненным циклом, деревом процессов в контрольных группах cgroups v2 и системными ограничениями окружения демона.

**Drop-in конфигурация (Drop-in file)** — файл переопределения директив сервиса (`/etc/systemd/system/nginx.service.d/*.conf`). Позволяет дополнять или изменять параметры штатного пакетного юнита (`/usr/lib/systemd/system/nginx.service`) без его прямого редактирования, сохраняя настройки при обновлениях пакета операционной системы.

**Песочница systemd (Systemd Sandboxing)** — встроенный в systemd комплекс механизмов изоляции процессов, базирующийся на пространствах имен ядра Linux (Mount, IPC, Network, UTS, User Namespaces), ограничениях файловой системы и фильтрации системных вызовов через BPF/seccomp.

**ProtectSystem / ProtectHome / PrivateTmp** — базовые директивы изоляции файловой системы в systemd. `ProtectSystem=strict` монтирует всю файловую систему в режиме Read-Only (за исключением путей, явно разрешенных через `ReadWritePaths`), `ProtectHome=true` блокирует доступ к каталогам пользователей (`/home`, `/root`), а `PrivateTmp=true` создает изолированное пространство для временных файлов.

**Linux Capabilities** — разделение монолитных привилегий суперпользователя (`root`, UID 0) на независимые дискретные права. `CapabilityBoundingSet` задает верхний предел привилегий, которые процесс может запросить; `AmbientCapabilities` передает указанные права (например, `CAP_NET_BIND_SERVICE`) при переходе на непривилегированного пользователя без использования бита SUID.

**SELinux (Security-Enhanced Linux)** — система мандатного контроля доступа (MAC) на базе модели Type Enforcement (TE). В целевой политике (targeted policy) демон Nginx функционирует в домене `httpd_t`. Доступ процесса к файлам (`httpd_sys_content_t`, `httpd_log_t`) и сетевым портам (`http_port_t`) жестко ограничен правилами политики и управляемыми булевыми флагами (`httpd_can_network_connect`).

**AppArmor** — модуль мандатного контроля доступа (MAC), использующий пути к файлам (Path-based MAC) в дистрибутивах Debian и Ubuntu. Правила доступа к бинарным файлам, конфигурациям, библиотекам и сетевым сокетам задаются в профиле `/etc/apparmor.d/usr.sbin.nginx`.

**Seccomp (Secure Computing Mode / SystemCallFilter)** — подсистема ядра Linux, использующая BPF-фильтры для перехвата и блокирования системных вызовов процесса. При попытке выполнить запрещенный вызов процесс завершается сигналом `SIGSYS` или получает ошибку `EPERM`.

**DAC (Discretionary Access Control)** — избирательный контроль доступа на основе стандартных атрибутов POSIX (пользователь, группа, маска прав `rwxrwxrwx`). Управляется владельцем файла.

**MAC (Mandatory Access Control)** — принудительный (мандатный) контроль доступа, навязываемый ядром на основе меток безопасности независимо от UID процесса и прав DAC. Даже процесс с UID 0 не может обойти ограничения MAC.

## Архитектура и принципы работы

### Архитектура процессов Nginx и модель привилегий

Веб-сервер Nginx использует многопроцессную событийно-ориентированную модель:

```text
               +--------------------------------------------------------+
               |                  Master Process (PID 1)                |
               |  (Root / unprivileged; binds 80/443; opens logs/pipes) |
               +--------------------------------------------------------+
                                         |
                       fork() + setuid() / setgid()
                                         v
               +--------------------------------------------------------+
               |                 Worker Processes (PID 2..N)             |
               |        (Runs as nginx/www-data; non-root worker)       |
               |  Event loops (epoll), SSL termination, HTTP processing |
               +--------------------------------------------------------+
                                         |
     -------------------------------------------------------------------------
     Изолирующие барьеры операционной системы:
      - systemd: Mount Namespace (RO root), PrivateTmp, Seccomp (SystemCallFilter)
      - Capabilities: CapabilityBoundingSet / AmbientCapabilities
      - MAC: SELinux (httpd_t domain) / AppArmor profile
     -------------------------------------------------------------------------
```

1. **Классическая модель (Root Master + Unprivileged Workers):**
   - **Мастер-процесс** запускается с правами `root`. Он читает конфигурационные файлы, открывает сокеты на привилегированных портах (80, 443) и открывает дескрипторы системных логов.
   - **Воркер-процессы** порождаются через вызов `fork()`, после чего вызывают `setuid()` и `setgid()`, сбрасывая свои права до непривилегированного пользователя (`nginx` в RHEL/Rocky или `www-data` в Debian/Ubuntu).
   - *Угроза:* в случае компрометации мастера злоумышленник получает полный контроль над системой.

2. **Непривилегированная модель (Non-Root Master):**
   - Мастер и воркеры изначально запускаются под непривилегированной учетной записью (`User=nginx`).
   - Для привязки к портам < 1024 мастеру выдается точечная capability ядра `CAP_NET_BIND_SERVICE` через директиву systemd `AmbientCapabilities`.
   - *Преимущество:* полное исключение суперпользователя `root` из жизненного цикла сервиса.

### Эшелонированная защита (Defense in Depth)

Харденинг на уровне системы распределяет функции безопасности по независимым изолирующим слоям:

| Слой защиты | Механизм ядра / ОС | Контролируемые ресурсы | Применяемые инструменты |
| :--- | :--- | :--- | :--- |
| **DAC** | Дискреционные права POSIX | Владельцы файлов, права `chmod` (0640/0750) | `chown`, `chmod`, `umask` |
| **systemd Sandboxing** | Namespaces (Mount, IPC, UTS) | Доступ к ФС, изоляция `/tmp`, изоляция `/dev` | `ProtectSystem=strict`, `PrivateTmp=true`, `PrivateDevices=true` |
| **systemd Capabilities** | Linux Capabilities | Потолок системных привилегий | `CapabilityBoundingSet`, `AmbientCapabilities` |
| **systemd Syscalls** | Seccomp BPF | Фильтрация системных вызовов | `SystemCallFilter`, `SystemCallArchitectures`, `MemoryDenyWriteExecute` |
| **MAC (SELinux / AppArmor)** | LSM (Linux Security Modules) | Мандатные метки файлов, портов и сетевых сокетов | SELinux: `httpd_t`, `http_port_t`, `setsebool`<br>AppArmor: `/etc/apparmor.d/usr.sbin.nginx` |
| **Прикладной L7** | Конфигурация Nginx | TLS, HTTP-заголовки, rate limits, WAF | [nginx_security_guide.md](./nginx_security_guide.md) |

### Механизм `NoNewPrivileges` и понижение прав

Директива systemd `NoNewPrivileges=true` устанавливает для процесса флаг ядра `PR_SET_NO_NEW_PRIVS`. Этот флаг гарантирует, что процесс и любые его дочерние процессы никогда не смогут повысить свои привилегии через запуск исполняемых файлов с битами SUID или SGID (например, через `sudo`, `su`, `passwd`).

> [!NOTE]
> `NoNewPrivileges=true` не препятствует понижению прав! Системные вызовы `setuid()` и `setgid()`, с помощью которых мастер-процесс Nginx передает управление воркерам под пользователем `nginx`/`www-data`, работают штатно, так как процесс уже обладает необходимыми правами и выполняет отказ от привилегий, а не их повышение.

## Практические сценарии

### Сценарий 1. Харденинг стандартного юнита Nginx через drop-in (рекомендуемый подход)

Данный сценарий изолирует окружение стандартного Nginx с root-мастером, запрещая запись в системные каталоги, блокируя доступ к устройствам, домашним каталогам и отсекая опасные системные вызовы.

#### Шаг 1. Создание каталога и drop-in файла

Не редактируйте файл `/usr/lib/systemd/system/nginx.service` напрямую. Создайте каталог переопределения:

```bash
sudo mkdir -p /etc/systemd/system/nginx.service.d
```

Создайте файл `/etc/systemd/system/nginx.service.d/hardening.conf`:

```ini
[Service]
# --- Изоляция файловой системы ---
# Монтирует всю ФС в режиме Read-Only, кроме путей, разрешенных в ReadWritePaths
ProtectSystem=strict

# Разрешенные каталоги для записи: логи, кэш, временные файлы и PID
ReadWritePaths=/var/log/nginx /var/cache/nginx /var/lib/nginx /run /var/run

# Полное сокрытие домашних каталогов (/home, /root, /run/user)
ProtectHome=true

# Индивидуальное приватное пространство /tmp и /var/tmp (отдельный mount namespace)
PrivateTmp=true

# Доступ только к базовым виртуальным устройствам (/dev/null, /dev/zero, /dev/urandom)
PrivateDevices=true

# Защита системного времени и аппаратных часов хоста
ProtectClock=true

# Запрет изменения сетевого имени хоста (hostname) и доменного имени
ProtectHostname=true

# Защита параметров ядра (/proc/sys, /sys, /proc/sysrq-trigger)
ProtectKernelTunables=true

# Запрет загрузки и выгрузки модулей ядра
ProtectKernelModules=true

# Запрет чтения журналов ядра (/dev/kmsg, /proc/kmsg)
ProtectKernelLogs=true

# Доступ к cgroups хоста только для чтения
ProtectControlGroups=true

# --- Ограничение привилегий и ядра ---
# Запрет повышения привилегий через SUID/SGID
NoNewPrivileges=true

# Запрет смены ABI исполнения процесса (защита от устаревших 32-битных интерфейсов)
LockPersonality=true

# Запрет установки realtime-приоритетов планировщика SCHED_FIFO/SCHED_RR
RestrictRealtime=true

# Запрет создания файлов с битами SUID/SGID
RestrictSUIDSGID=true

# Запрет создания пользовательских пространств имен (CLONE_NEWUSER, CLONE_NEWNET и др.)
RestrictNamespaces=true

# --- Ограничение системных вызовов (seccomp) ---
# Разрешаем стандартные системные службы и сетевой стек
SystemCallFilter=@system-service @network-io
SystemCallErrorNumber=EPERM

# Ограничение семейств сетевых протоколов:
# AF_INET (IPv4), AF_INET6 (IPv6), AF_UNIX (локальные сокеты PHP-FPM/uWSGI), AF_NETLINK (DNS resolver/glibc getifaddrs)
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK

# --- Ограничение Linux Capabilities ---
# Оставляем только привилегии, необходимые для биндинга портов <1024, смены UID/GID воркеров и поднятия rlimits
CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_SETUID CAP_SETGID CAP_SYS_RESOURCE
```

> [!WARNING]
> Директива `MemoryDenyWriteExecute=true` запрещает страницам памяти одновременно иметь права на запись и исполнение (W^X). Для стандартного Nginx и Angie она безопасна, однако **несовместима** с Nginx скомпилированным с LuaJIT (`lua-nginx-module`) или PCRE JIT, так как динамическая компиляция кода требует создания исполняемых страниц в рантайме. Если вы используете OpenResty или Lua, не включайте `MemoryDenyWriteExecute`.

> [!IMPORTANT]
> Обратите внимание на семейство `AF_NETLINK` в `RestrictAddressFamilies`. В современных дистрибутивах glibc использует сокеты Netlink для выполнения вызовов `getaddrinfo()` и `getifaddrs()`. Отсутствие `AF_NETLINK` приведет к сбоям резолвинга DNS и проверки состояния интерфейсов.

#### Шаг 2. Применение изменений и валидация

```bash
# Перечитываем конфигурацию systemd
sudo systemctl daemon-reload

# Проверяем корректность конфигурации Nginx перед рестартом
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Перезапускаем сервис
sudo systemctl restart nginx

# Проверяем статус работы сервиса
sudo systemctl status nginx --no-pager
# → Active: active (running) since ...; ...
```

Проверяем доступность веб-сервера:

```bash
curl -I http://127.0.0.1/
# → HTTP/1.1 200 OK
```

---

### Сценарий 2. Полностью непривилегированный запуск (Non-Root Master)

Запуск мастера от имени непривилегированного пользователя `nginx` обеспечивает максимальную безопасность, исключая присутствие процессов с UID 0.

#### Шаг 1. Настройка systemd drop-in для непривилегированного режима

Создайте файл `/etc/systemd/system/nginx.service.d/unprivileged.conf`:

```ini
[Service]
# Запуск мастера под пользователем и группой nginx
User=nginx
Group=nginx

# Наделение непривилегированного процесса правом биндинга портов 80 и 443
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE

# Автоматическое создание каталога /run/nginx с владельцем nginx:nginx при старте
RuntimeDirectory=nginx
RuntimeDirectoryMode=0755

# Изоляция файловой системы
ProtectSystem=strict
ReadWritePaths=/var/log/nginx /var/cache/nginx /var/lib/nginx
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
NoNewPrivileges=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK
```

#### Шаг 2. Корректировка конфигурации `nginx.conf`

Откройте `/etc/nginx/nginx.conf` и внесите следующие изменения:

```nginx
# 1. Закомментируйте или удалите директиву 'user', так как мастер уже не root:
# user nginx;

# 2. Перенесите PID-файл в каталог RuntimeDirectory (/run/nginx/):
pid /run/nginx/nginx.pid;
```

#### Шаг 3. Корректировка прав на каталоги

Убедитесь, что все рабочие каталоги принадлежат пользователю `nginx`:

```bash
sudo chown -R nginx:nginx /var/log/nginx /var/cache/nginx /var/lib/nginx
sudo systemctl daemon-reload
sudo systemctl restart nginx
```

Проверяем, от чьего имени запущены процессы мастера и воркеров:

```bash
ps -o pid,user,group,comm -C nginx
# →   PID USER     GROUP    COMMAND
# → 14201 nginx    nginx    nginx
# → 14202 nginx    nginx    nginx
```

---

### Сценарий 3. Настройка и эксплуатация SELinux на RHEL 8/9, Rocky Linux и AlmaLinux

В семействах RHEL/Rocky/AlmaLinux Nginx работает в домене безопасности `httpd_t`. Попытки взаимодействия с ресурсами, не описанными в политике, блокируются ядром с генерацией AVC denial.

#### Шаг 1. Проверка текущего статуса SELinux

```bash
sestatus
# → SELinux status:                 enabled
# → Current mode:                   enforcing
# → Mode from config file:          enforcing
# → Policy MLS status:              enabled
# → Policy deny_unknown status:     allowed
# → Memory protection checking:     actual (secure)
# → Max kernel policy version:      33
```

#### Шаг 2. Назначение контекста безопасности файлам веб-контента

Если файлы сайта размещены в нестандартном каталоге (например, `/srv/www/site` вместо `/usr/share/nginx/html`), процесс в домене `httpd_t` получит ошибку `403 Forbidden`.

Никогда не используйте команду `chcon` для постоянной настройки — при первой же проверке `restorecon` контекст сбросится. Добавляйте правило в базу данных SELinux:

```bash
# Добавляем правило сопоставления контекста для каталога и всех вложенных файлов
sudo semanage fcontext -a -t httpd_sys_content_t "/srv/www(/.*)?"

# Применяем контексты к существующим файлам
sudo restorecon -Rv /srv/www
# → Relabeled /srv/www from unlabeled_t to system_u:object_r:httpd_sys_content_t:s0
# → Relabeled /srv/www/index.html from unlabeled_t to system_u:object_r:httpd_sys_content_t:s0
```

Если сайту требуется каталог для загрузки файлов пользователями (upload) или локального кэша, назначьте тип `httpd_sys_rw_content_t`:

```bash
sudo semanage fcontext -a -t httpd_sys_rw_content_t "/srv/www/uploads(/.*)?"
sudo restorecon -Rv /srv/www/uploads
```

#### Шаг 3. Настройка булевых флагов SELinux для работы в роли Reverse Proxy

По умолчанию SELinux запрещает процессам Nginx инициировать исходящие TCP-соединения. Попытка перенаправить запрос через `proxy_pass` завершится ошибкой `502 Bad Gateway` (в `error.log`: `(13: Permission denied)`).

```bash
# Разрешаем Nginx подключаться к сетевым апстримам (Reverse Proxy)
sudo setsebool -P httpd_can_network_connect on

# Проверяем состояние флага
getsebool httpd_can_network_connect
# → httpd_can_network_connect --> on
```

Дополнительные полезные булевы флаги:

```bash
# Разрешить прямое подключение к базам данных (PostgreSQL/MySQL) через Nginx
sudo setsebool -P httpd_can_network_connect_db on

# Разрешить чтение файлов из домашних каталогов пользователей (~/public_html)
sudo setsebool -P httpd_enable_homedirs on

# Разрешить корректный перезапуск и переоткрытие логов при graceful shutdown
sudo setsebool -P httpd_graceful_shutdown on

# Разрешить Nginx изменять системные лимиты ресурсов (worker_rlimit_nofile)
sudo setsebool -P httpd_setrlimit on
```

#### Шаг 4. Добавление нестандартных сетевых портов

Если Nginx должен слушать нестандартный порт (например, 8080 или 8443), при старте возникнет ошибка `bind() to 0.0.0.0:8080 failed (13: Permission denied)`.

```bash
# Проверяем, какие порты уже назначены для HTTP-серверов
sudo semanage port -l | grep http_port_t
# → http_port_t                    tcp      80, 81, 443, 488, 8008, 8009, 8443, 9000

# Регистрируем новый порт в базе данных SELinux
sudo semanage port -a -t http_port_t -p tcp 8080

# Проверяем успешность добавления
sudo semanage port -l | grep http_port_t
# → http_port_t                    tcp      8080, 80, 81, 443, 488, 8008, 8009, 8443, 9000
```

> [!NOTE]
> Если порт уже занят другим типом SELinux, опция `-a` завершится ошибкой. В этом случае используйте модификацию существующего правила: `sudo semanage port -m -t http_port_t -p tcp 8080`.

#### Шаг 5. Диагностика AVC-отказов и компиляция целевого модуля

Если операция блокируется SELinux, проанализируйте журнал аудита:

```bash
# Поиск свежих блокировок для Nginx
sudo ausearch -m avc -ts recent -c nginx
# → type=AVC msg=audit(1713360000.123:456): avc:  denied  { name_connect } for  pid=1234 comm="nginx" dest=8080 scontext=system_u:system_r:httpd_t:s0 tcontext=system_u:object_r:unreserved_port_t:s0 tclass=tcp_socket permissive=0

# Интерпретация причины блокировки
sudo ausearch -m avc -ts recent | audit2why
# → Was caused by:
# →   Missing or disabled boolean: httpd_can_network_connect
```

Если операция легитимна, но не покрывается стандартными булевыми флагами, сгенерируйте и установите точечный модуль политики:

```bash
# Создаем и компилируем модуль на основе зафиксированных отказов
sudo ausearch -m avc -ts recent -c nginx | audit2allow -M nginx_custom_policy

# Устанавливаем скомпилированный модуль
sudo semodule -i nginx_custom_policy.pp

# Проверяем наличие установленного модуля
sudo semodule -l | grep nginx_custom_policy
# → nginx_custom_policy
```

---

### Сценарий 4. Настройка и принудительное применение AppArmor на Debian/Ubuntu

В дистрибутивах Debian и Ubuntu демон Nginx по умолчанию часто работает без профиля ограничения (`unconfined`). Создание и включение профиля AppArmor гарантирует защиту от несанкционированного чтения и записи файлов.

#### Шаг 1. Проверка текущего статуса AppArmor

```bash
sudo aa-status | grep nginx
# Если вывод пуст — Nginx работает в режиме unconfined
```

#### Шаг 2. Создание профиля AppArmor для Nginx

Создайте файл `/etc/apparmor.d/usr.sbin.nginx`:

```apparmor
#include <tunables/global>

/usr/sbin/nginx {
  #include <abstractions/base>
  #include <abstractions/nameservice>
  #include <abstractions/openssl>

  # Системные capabilities
  capability net_bind_service,
  capability setuid,
  capability setgid,
  capability dac_override,
  capability sys_resource,

  # Сетевые протоколы
  network inet stream,
  network inet6 stream,
  network unix stream,
  network netlink raw,

  # Исполняемый файл Nginx
  /usr/sbin/nginx mr,

  # Конфигурационные файлы
  /etc/nginx/** r,
  /etc/ssl/** r,
  /etc/pki/** r,

  # Логи
  /var/log/nginx/** rw,
  /var/log/nginx/ r,

  # Кэш и временные каталоги
  /var/cache/nginx/** rwk,
  /var/cache/nginx/ r,
  /var/lib/nginx/** rwk,
  /var/lib/nginx/ r,

  # PID-файлы и сокеты
  /run/nginx.pid rw,
  /run/nginx/** rw,
  /run/nginx/ r,

  # Статический веб-контент
  /var/www/** r,
  /usr/share/nginx/html/** r,

  # Системная информация
  /proc/sys/kernel/ngroups_max r,
  /proc/cpuinfo r,
  /sys/devices/system/cpu/online r,
}
```

#### Шаг 3. Перевод в режим обучения (Complain Mode) и сбор правил

Перед принудительным включением протестируйте профиль в режиме фиксации нарушений без их блокировки:

```bash
# Загружаем профиль в режиме обучения
sudo aa-complain /usr/sbin/nginx
# → Setting /usr/sbin/nginx to complain mode.

# Перезапускаем Nginx и подаем нагрузку
sudo systemctl restart nginx
curl -I http://127.0.0.1/

# Проверяем журнал блокировок и дополняем профиль при необходимости
sudo aa-logprof
```

#### Шаг 4. Включение жесткого режима (Enforce Mode)

```bash
# Переводим профиль в режим принудительного исполнения
sudo aa-enforce /usr/sbin/nginx
# → Setting /usr/sbin/nginx to enforce mode.

# Перезагружаем профиль в ядре
sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.nginx

# Проверяем статус профиля
sudo aa-status | grep nginx
# → /usr/sbin/nginx (enforce)
```

---

### Сценарий 5. Настройка ротации логов (`logrotate`) при жестком харденинге

При использовании жесткой изоляции systemd (`ProtectSystem=strict`) или непривилегированного запуска штатный механизм ротации логов может давать сбои при переоткрытии файлов.

#### Анализ взаимодействия

1. Демон `logrotate` запускается по таймеру systemd от пользователя `root`.
2. После перемещения старого файла лога Nginx должен переоткрыть дескрипторы новых файлов по сигналу `SIGUSR1`.
3. Если мастер запущен от `nginx`, сигнал должен отправляться корректно, а вновь созданные файлы должны иметь правильного владельца и права.

Настройте `/etc/logrotate.d/nginx`:

```text
/var/log/nginx/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 nginx nginx
    sharedscripts
    postrotate
        # Безопасная отправка сигнала через systemctl вместо чтения pid-файла
        /usr/bin/systemctl kill -s USR1 --kill-who=main nginx.service 2>/dev/null || true
    endscript
}
```

Протестируйте ротацию в режиме отладки:

```bash
sudo logrotate -d /etc/logrotate.d/nginx
# → reading config file /etc/logrotate.d/nginx
# → handling log "/var/log/nginx/*.log"
# → log does not need rotating (log is empty)...
```

## Операции и команды

Сводная таблица команд администрирования, аудита и диагностики системного харденинга:

```bash
# --- Аудит безопасности systemd ---
# Оценка уровня защищенности сервиса (выводит Exposure score от 0.0 до 10.0)
systemd-analyze security nginx
# →   NAME                     DESCRIPTION                                                     EXPOSURE
# → ✗ PrivateNetwork=          Service has access to the host's network                             0.5
# → ✓ PrivateTmp=              Service has no access to other software's temp files                 0.0
# → ✓ ProtectHome=             Service has no access to home directories                            0.0
# → ✓ ProtectSystem=           Service has strict read-only access to the OS file hierarchy         0.0
# → ...
# → → Overall exposure level for nginx.service: 2.1 OK

# Просмотр фактически действующих директив изоляции юнита
systemctl show nginx -p ProtectSystem -p ProtectHome -p CapabilityBoundingSet -p AmbientCapabilities -p NoNewPrivileges
# → ProtectSystem=strict
# → ProtectHome=yes
# → CapabilityBoundingSet=cap_net_bind_service cap_setuid cap_setgid cap_sys_resource
# → AmbientCapabilities=
# → NoNewPrivileges=yes

# Проверка синтаксиса drop-in файлов без перезапуска службы
systemd-analyze verify /etc/systemd/system/nginx.service.d/*.conf

# --- Проверка Linux Capabilities процессов ---
# Просмотр битовой маски capabilities рабочего процесса
grep -E 'Cap(Inh|Prm|Eff|Bnd|Amb)' /proc/$(pgrep -n nginx)/status
# → CapInh: 0000000000000000
# → CapPrm: 0000000000000000
# → CapEff: 0000000000000000
# → CapBnd: 0000000000000400
# → CapAmb: 0000000000000000

# Декодирование маски capabilities в человекочитаемый вид
capsh --decode=0000000000000400
# → 0x0000000000000400=cap_net_bind_service

# --- Проверка и управление SELinux ---
# Проверка меток безопасности файлов конфигурации и логов
ls -lZ /etc/nginx/nginx.conf /var/log/nginx
# → -rw-r--r--. 1 root root system_u:object_r:httpd_config_t:s0 /etc/nginx/nginx.conf
# → drwxr-xr-x. 2 root root system_u:object_r:httpd_log_t:s0    /var/log/nginx

# Проверка домена безопасности запущенного процесса Nginx
ps -Z -C nginx
# → LABEL                              PID TTY          TIME CMD
# → system_u:system_r:httpd_t:s0     12345 ?        00:00:00 nginx
# → system_u:system_r:httpd_t:s0     12346 ?        00:00:01 nginx

# Просмотр всех булевых переключателей, связанных с HTTP-серверами
getsebool -a | grep httpd
# → httpd_can_network_connect --> on
# → httpd_can_network_connect_db --> off
# → httpd_enable_homedirs --> off

# --- Проверка и управление AppArmor ---
# Просмотр статуса всех загруженных профилей
sudo aa-status
# → ... profiles are in enforce mode.
# →    /usr/sbin/nginx
# → ... processes are in enforce mode.
# →    /usr/sbin/nginx (12345)
```

## Устранение неполадок

| Симптом / Ошибка | Первопричина | Команда диагностики | Решение |
| :--- | :--- | :--- | :--- |
| **`Failed to set up mount namespacing: Permission denied`** или аварийный останов при старте | Директива `ProtectSystem=strict` включена, но Nginx пытается писать в каталог, не указанный в `ReadWritePaths`. | `sudo journalctl -u nginx -e --no-pager`<br># → `nginx: [emerg] open() "/run/nginx.pid" failed (30: Read-only file system)` | Добавить путь записи в `ReadWritePaths` (например, `ReadWritePaths=/run /var/log/nginx /var/cache/nginx`) или настроить `RuntimeDirectory=nginx`. |
| **`502 Bad Gateway`** при обращении к бэкенду на RHEL/Rocky | SELinux запрещает Nginx сетевые подключения к апстримам. | `sudo ausearch -m avc -ts recent -c nginx`<br># → `avc: denied { name_connect } for comm="nginx"` | Включить булевый переключатель:<br>`sudo setsebool -P httpd_can_network_connect on`. |
| **`bind() to 0.0.0.0:80 failed (13: Permission denied)`** при старте от `User=nginx` | Процесс запущен от непривилегированного пользователя без capability привязки к привилегированным портам. | `systemctl show nginx -p AmbientCapabilities`<br># → `AmbientCapabilities=` | Добавить в drop-in:<br>`AmbientCapabilities=CAP_NET_BIND_SERVICE`<br>`CapabilityBoundingSet=CAP_NET_BIND_SERVICE`. |
| **`403 Forbidden`** при чтении статических файлов при правах DAC `644`/`755` | Неверный контекст безопасности SELinux или ограничение AppArmor. | `sudo ls -Z /var/www/site/index.html`<br># → `unlabeled_t` или `admin_home_t` | Назначить корректный контекст:<br>`sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/site(/.*)?"`<br>`sudo restorecon -Rv /var/www/site`. |
| **`connect() to unix:/run/php/php-fpm.sock failed (13: Permission denied)`** | `RestrictAddressFamilies` не содержит `AF_UNIX` либо сокет заблокирован директивой `ProtectHome`. | `systemctl show nginx -p RestrictAddressFamilies`<br># → `RestrictAddressFamilies=AF_INET AF_INET6` | Добавить `AF_UNIX` в `RestrictAddressFamilies`. Убедиться, что сокет находится в `/run` или `/var/run`, а не в каталоге `/home`. |
| Аварийное завершение Nginx с кодом **`SIGSYS` (Bad system call)** | Фильтр системных вызовов seccomp (`SystemCallFilter`) заблокировал вызов ядра. | `sudo coredumpctl info nginx` или `dmesg \| grep -i seccomp`<br># → `audit: type=1326 ... comm="nginx" sig=31` | Проверить используемые сторонние модули Nginx. Расширить группы вызовов или добавить директиву `SystemCallErrorNumber=EPERM` для мягкой обработки отказа. |
| **`nginx: [warn] 1024 worker_connections exceed open file resource limit`** | Лимит дескрипторов файлов процесса ограничен на уровне systemd. | `grep 'Max open files' /proc/$(pgrep -n nginx)/status`<br># → `Max open files 1024 1024` | Задать лимит дескрипторов в секции `[Service]` drop-in файла:<br>`LimitNOFILE=65536`. |
| **`nginx: [warn] the "user" directive makes sense only if the master process runs with super-user privileges`** | В `nginx.conf` осталась директива `user`, когда юнит запущен с параметром `User=nginx`. | `sudo nginx -t`<br># → `nginx: [warn] the "user" directive makes sense only...` | Удалить или закомментировать строку `user nginx;` в файле `/etc/nginx/nginx.conf`. |
| Ошибка ротации: **`kill: (12345): Operation not permitted`** в logrotate | Скрипт ротации запускается от непривилегированного пользователя или не имеет доступа к PID. | `sudo logrotate -f /etc/logrotate.d/nginx` | Использовать вызов `/usr/bin/systemctl kill -s USR1 --kill-who=main nginx.service` в секции `postrotate`. |
| Аварийное завершение воркера с ошибкой **`SIGSEGV`** при загрузке Lua/PCRE JIT | Директива `MemoryDenyWriteExecute=true` блокирует выделение исполняемых страниц памяти. | `sudo journalctl -u nginx -e \| grep -i segfault` | Отключить директиву `MemoryDenyWriteExecute=true` в drop-in файле при использовании LuaJIT / PCRE JIT. |

## Лучшие практики

1. **Используйте исключительно drop-in файлы для модификации юнита.** Никогда не редактируйте пакетный файл `/usr/lib/systemd/system/nginx.service`. Любые оверрайды должны располагаться в каталоге `/etc/systemd/system/nginx.service.d/*.conf`, что гарантирует сохранение настроек при обновлении операционной системы.
2. **Внедряйте системный харденинг итеративно.** Начинайте с изоляции файловой системы (`ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`) и запрета повышения привилегий (`NoNewPrivileges=true`). Ограничения системных вызовов (`SystemCallFilter`) и capabilities подключайте на этапе нагрузочного тестирования во избежание сбоев сторонних модулей.
3. **Строго придерживайтесь принципа «Одна система — один MAC».** В семействах RHEL, Rocky Linux и AlmaLinux используйте SELinux. В Debian и Ubuntu используйте AppArmor. Одновременное включение двух LSM-модулей не поддерживается ядром и приводит к непредсказуемым конфликтам.
4. **Никогда не отключайте SELinux или AppArmor в производственной среде.** Использование `setenforce 0` или отключение профилей допустимо исключительно для локализации источника проблемы при отладке. В production любые проблемы доступа решаются назначением корректных контекстов (`semanage fcontext`), включением булевых флагов (`setsebool -P`) или донастройкой профилей (`aa-logprof`).
5. **Централизуйте управление лимитами в systemd.** Избегайте использования директивы `worker_rlimit_nofile` в `nginx.conf`, требующей системной capability `CAP_SYS_RESOURCE`. Задавайте лимит открытых файловых дескрипторов централизованно через директиву юнита `LimitNOFILE=65536`.
6. **Контролируйте доступность сетевых сокетов Netlink.** Всегда включайте семейство `AF_NETLINK` в директиву `RestrictAddressFamilies` наряду с `AF_INET`, `AF_INET6` и `AF_UNIX`. Это предотвращает скрытые сбои системного резолвера DNS glibc при получении топологии сетевых интерфейсов.
7. **Настройте мониторинг и алертинг событий безопасности.** Настройте отправку событий AVC denial (`/var/log/audit/audit.log`) и сообщений ядра AppArmor (`dmesg`) в централизованную систему сбора логов (Elasticsearch, Loki, Graylog). Любой всплеск отказов доступа сигнализирует либо об ошибке конфигурации, либо о попытке зондирования веб-сервера.
8. **Автоматизируйте версионирование конфигураций.** Храните drop-in файлы systemd, профили AppArmor и скрипты настройки контекстов SELinux в репозитории инфраструктурного кода (Git / Ansible) вместе с конфигурационными файлами Nginx (см. [nginx_setup.md](../Core/nginx_setup.md#управление-конфигурацией-через-git-и-cicd)).

## Дополнительная информация

Материалы по смежным механизмам изоляции ядра Linux и прикладной настройке веб-сервера:

### См. также

- [Руководство по безопасности Nginx](./nginx_security_guide.md) — прикладной уровень L7: TLS, заголовки безопасности, WAF ModSecurity/Coraza, защита от DoS и rate limiting.
- [Харденинг systemd](../../../Linux/Security/Concepts/systemd_security.md) — фундаментальный справочник по директивам песочниц, namespaces и изоляции служб в systemd.
- [Linux Capabilities](../../../Linux/Security/Mechanisms/Capabilities.md) — детальная теория дискретных привилегий ядра, управление Inheritable, Permitted, Effective и Ambient наборами.
- [SELinux](../../../Linux/Security/Mechanisms/SELinux.md) — теория мандатного контроля доступа, архитектура Flask/TE, синтаксис правил и управление политиками.
- [AppArmor](../../../Linux/Security/Mechanisms/AppArmor.md) — управление профилями, режимы enforce/complain и аудит инцидентов.
- [Диагностика и устранение неполадок Nginx](../Operations/nginx_troubleshooting.md) — общая методология траблшутинга Nginx, сетевого стека и файловых дескрипторов.
- [Базовая установка и настройка Nginx](../Core/nginx_setup.md) — управление жизненным циклом, модули и развертывание веб-сервера.
- [Архитектура и обзор Nginx](../Core/nginx_overview.md) — модель рабочих процессов, циклы обработки соединений и структура буферов.