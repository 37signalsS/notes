# Traefik на bare-metal/VM: установка, systemd, эксплуатация

**Актуально для:** Traefik v3.x / Linux systemd

## Определения

**Bare-metal/VM-развертывание** — запуск Traefik в виде нативного скомпилированного бинарного файла Go непосредственно в операционной системе Linux (без контейнеризации Docker/Podman или оркестрации Kubernetes) под управлением системного менеджера `systemd`.

**Ambient Capabilities** — механизм ядра Linux (`prctl(PR_CAP_AMBIENT)`), позволяющий непривилегированному процессу наследовать системные привилегии (capabilities) без повышения прав до суперпользователя (`root`). Для Traefik критична `CAP_NET_BIND_SERVICE`, дающая право занимать порты `< 1024` (80, 443).

**systemd Sandboxing** — комплекс декларативных параметров безопасности unit-файла (`ProtectSystem`, `ProtectHome`, `NoNewPrivileges`, `PrivateTmp`), изолирующий файловую систему и системные вызовы процесса от остальной ОС.

**File Provider Dynamic Watch** — механизм Traefik, отслеживающий события файловой системы (`inotify`) в заданной директории и автоматически перечитывающий динамическую конфигурацию (маршруты, сервисы, middleware) в рантайме без перезапуска процесса.

**Graceful Shutdown (мягкое завершение)** — процедура контролируемой остановки сервиса при получении сигнала `SIGTERM`: Traefik перестает принимать новые TCP-соединения, завершает обработку текущих in-flight запросов в рамках лимитов `transport.lifeCycle`, фиксирует состояние ACME и завершается с кодом `0`.

**In-place Binary Upgrade** — регламент атомарной замены исполняемого файла `/usr/local/bin/traefik` новой версией с валидацией синтаксиса до перезапуска службы и возможностью немедленного отката (rollback).

**logrotate (`copytruncate`)** — метод ротации журналов, при котором активный лог-файл копируется в архивный, а исходный файл обрезается до нулевого размера (`truncate`) на месте. Необходим для приложений, которые не реализуют сигналы переоткрытия дескрипторов (`SIGHUP`/`SIGUSR1`).

**Kernel Accept Queue (`somaxconn`)** — системная очередь ядра Linux для полностью установленных TCP-соединений (`ESTABLISHED`), ожидающих выборки вызовом `accept()`.

## Базовые концепции

### Архитектура процесса Traefik на bare-metal

В отличие от Docker-окружения, где жизненным циклом и сетевыми интерфейсами управляет контейнерный демон, на bare-metal Traefik функционирует как единый многопоточный системный процесс. Внутренний планировщик Go распределяет горутины по всем доступным процессорным ядрам хоста (`GOMAXPROCS`).

```
Входящий трафик (Порты 80, 443, 8080)
            │
            ▼
┌────────────────────────────────────────────────────────┐
│ Traefik Process (PID: traefik, UID: 998, GID: 998)    │
│ AmbientCapabilities: CAP_NET_BIND_SERVICE             │
│                                                        │
│ ┌──────────────────────┐    ┌────────────────────────┐ │
│ │ Статическая часть     │    │ Динамическая часть     │ │
│ │ /etc/traefik/        │    │ /etc/traefik/dynamic/  │ │
│ │ traefik.yml          │    │ *.yml (inotify watch)  │ │
│ └──────────┬───────────┘    └───────────┬────────────┘ │
│            │ (Старт)                    │ (Рантайм)    │
│            ▼                            ▼              │
│    EntryPoints (TCP/UDP) ──► Routers ──► Middlewares   │
│                                              │         │
│                                              ▼         │
│                                           Services     │
└──────────────────────────────────────────────┬─────────┘
                                               │
                                               ▼
                              Бэкенд-сервисы хоста / LAN
                              (127.0.0.1:3000, 10.0.0.5:8080)
```

Преимущества развертывания на bare-metal:
- Отсутствие накладных расходов на виртуализацию сети (`veth`-пары, `bridge`, `docker-proxy`, conntrack трансляции портов).
- Полная прозрачность сетевых соединений и прямое использование аппаратных очередей сетевой карты.
- Централизованный аудит безопасности, лимитов ресурсов (`cgroups v2`) и журнала через `systemd`.

Ограничения:
- Отсутствие автоматического Service Discovery по метаданным контейнеров: управление маршрутизацией осуществляется через `File provider` (с GitOps/Ansible) или внешние KV-хранилища (Consul, Etcd).
- Обновление бинарного файла и сертификатов требует системных процедур сопровождения.

### Сетевые привилегии: non-root и Capabilities

Для прослушивания стандартных портов HTTP (80) и HTTPS (443) процессам традиционно требуются привилегии `root`. Запуск обратного прокси под учетной записью суперпользователя нарушает базовый принцип безопасности наименьших привилегий (Least Privilege).

Для безопасного запуска Traefik от выделенного пользователя `traefik` используются три подхода:

| Метод | Механизм | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **systemd AmbientCapabilities** *(Рекомендуется)* | Директивы `AmbientCapabilities=CAP_NET_BIND_SERVICE` и `CapabilityBoundingSet=CAP_NET_BIND_SERVICE` в unit-файле | Привилегии выдаются только службе, бинарник на диске остается чистым | Работает только при запуске через `systemd` |
| **Файловые Capabilities (`setcap`)** | `setcap 'cap_net_bind_service=+ep' /usr/local/bin/traefik` | Работает при ручном запуске из терминала | Сбрасывается при каждой перезаписи/обновлении бинарника |
| **Ядерный параметр `sysctl`** | `sysctl -w net.ipv4.ip_unprivileged_port_start=80` | Не требует capabilities | Глобально открывает порты 80+ для всех непривилегированных процессов ОС |

Подробнее о механизмах привилегий: [Linux Capabilities](../../Linux/Security/Mechanisms/Capabilities.md).

### Статическая и динамическая конфигурация без Docker

Конфигурация Traefik разделена на две изолированные части:
1. **Статическая конфигурация (`/etc/traefik/traefik.yml`):** задает базовые параметры процесса — точки входа (`entryPoints`), провайдеры конфигурации (`providers`), хранилище сертификатов (`certificatesResolvers`), системные логи и метрики. Применяется **исключительно** в момент старта процесса.
2. **Динамическая конфигурация (`/etc/traefik/dynamic/`):** определяет правила маршрутизации — роутеры (`routers`), цепочки промежуточных обработчиков (`middlewares`) и целевые сервисы (`services`).

Для bare-metal основным источником динамических правил выступает `File Provider` с опцией `watch: true`:

```yaml
# /etc/traefik/traefik.yml
providers:
  file:
    directory: /etc/traefik/dynamic
    watch: true
```

Traefik инициализирует механизм `inotify` на каталог `/etc/traefik/dynamic`. При добавлении, изменении или удалении любого YAML-файла изменения вступают в силу немедленно без сброса активных соединений и без рестарта демона.

### Сигналы ядра и жизненный цикл процесса

| Сигнал | Назначение | Реакция Traefik v3 |
| :--- | :--- | :--- |
| `SIGTERM` / `SIGINT` | Стандартная остановка | Запуск graceful shutdown: закрытие слушающих сокетов, добор in-flight запросов в рамках `requestAcceptGraceTimeout`, ожидание активных запросов до `graceTimeout`, сброс `acme.json` на диск и выход с кодом `0`. |
| `SIGHUP` | Перечитывание конфигурации | **Игнорируется или приводит к ошибке.** В Traefik не существует перезагрузки статической конфигурации по `SIGHUP`. Для перечитывания динамики рестарт не нужен (работает `watch`), а для изменения статики необходим `systemctl restart`. |
| `SIGKILL` | Принудительное уничтожение | Аварийный обрыв соединений ядром. Приводит к потере данных клиентов и риску повреждения файла `acme.json`, если в этот момент выполнялась запись сертификата. |

### Сетевой стек ядра Linux для обратного прокси

В условиях высокой нагрузки (high load) bare-metal сервер с Traefik упирается в системные лимиты ядра по умолчанию:
- Малый размер очереди `somaxconn` (128 или 4096) приводит к отбрасыванию SYN-пакетов при всплесках трафика.
- Узкий диапазон временных портов (`ip_local_port_range`) и медленная очистка сокетов `TIME_WAIT` вызывают дефицит портов при проксировании на локальные upstream-сервисы (`Cannot assign requested address`).
- Дефолтный лимит файловых дескрипторов (1024) блокирует параллельные TCP-соединения (`Too many open files`).

Подробнее о дескрипторах: [Файловые дескрипторы](../../Linux/FileSystems/file_descriptors.md).

## Практические сценарии

### Сценарий 1: Установка бинарника с проверкой контрольных сумм

Установка официального релиза Traefik v3 для архитектуры x86_64 (amd64) с валидацией целостности SHA-256.

```bash
# 1. Фиксация целевой стабильной версии
TRAEFIK_VERSION="v3.3.4"
ARCH="linux_amd64"

# 2. Загрузка архива релиза и файла контрольных сумм
curl -sSLO "https://github.com/traefik/traefik/releases/download/${TRAEFIK_VERSION}/traefik_${TRAEFIK_VERSION}_${ARCH}.tar.gz"
curl -sSLO "https://github.com/traefik/traefik/releases/download/${TRAEFIK_VERSION}/traefik_${TRAEFIK_VERSION}_checksums.txt"

# 3. Верификация контрольной суммы конкретного скачанного архива
grep "traefik_${TRAEFIK_VERSION}_${ARCH}.tar.gz" "traefik_${TRAEFIK_VERSION}_checksums.txt" | sha256sum -c -
# → traefik_v3.3.4_linux_amd64.tar.gz: OK

# 4. Распаковка и размещение в системном каталоге
tar -xzf "traefik_${TRAEFIK_VERSION}_${ARCH}.tar.gz" traefik
sudo install -m 0755 -o root -g root traefik /usr/local/bin/traefik
rm -f "traefik_${TRAEFIK_VERSION}_${ARCH}.tar.gz" "traefik_${TRAEFIK_VERSION}_checksums.txt" traefik

# 5. Проверка установленной версии
/usr/local/bin/traefik version
# → Version:      v3.3.4
# → Codename:     ...
# → Go version:   go1.23...
```

### Сценарий 2: Создание пользователя и структуры каталогов

Traefik должен запускаться от выделенного непривилегированного пользователя без оболочки входа и с минимально достаточными правами на файловую систему.

```bash
# Создание системной группы и пользователя traefik
sudo groupadd --system traefik
sudo useradd --system \
    --gid traefik \
    --home-dir /var/lib/traefik \
    --no-create-home \
    --shell /usr/sbin/nologin \
    --comment "Traefik Edge Router" \
    traefik

# Создание каталогов конфигурации, данных и логов
sudo mkdir -p /etc/traefik/dynamic
sudo mkdir -p /var/lib/traefik
sudo mkdir -p /var/log/traefik

# Создание и защита хранилища сертификатов Let's Encrypt
sudo touch /var/lib/traefik/acme.json
sudo chmod 0600 /var/lib/traefik/acme.json

# Назначение владельцев
sudo chown -R root:traefik /etc/traefik
sudo chmod 0755 /etc/traefik
sudo chmod 0750 /etc/traefik/dynamic

sudo chown -R traefik:traefik /var/lib/traefik
sudo chmod 0750 /var/lib/traefik

sudo chown -R traefik:traefik /var/log/traefik
sudo chmod 0750 /var/log/traefik
```

### Сценарий 3: Производственная конфигурация (Статика и Динамика)

#### 1. Статическая конфигурация: `/etc/traefik/traefik.yml`

```yaml
# Точки входа
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
          permanent: true

  websecure:
    address: ":443"
    transport:
      lifeCycle:
        requestAcceptGraceTimeout: 5s
        graceTimeout: 30s
      respondingTimeouts:
        readTimeout: 60s
        writeTimeout: 60s
        idleTimeout: 180s

  traefik:
    address: "127.0.0.1:8080"

# Провайдеры конфигурации
providers:
  file:
    directory: /etc/traefik/dynamic
    watch: true

# Встроенный health check
ping:
  entryPoint: traefik

# Метрики Prometheus
metrics:
  prometheus:
    entryPoint: traefik
    addEntryPointsLabels: true
    addRoutersLabels: true
    addServicesLabels: true

# Системный лог
log:
  level: INFO
  format: json

# Журнал доступа (access log)
accessLog:
  filePath: "/var/log/traefik/access.log"
  format: json
  bufferingSize: 100
  filters:
    retryAttempts: true
    minDuration: "10ms"

# Автоматический выпуск TLS-сертификатов Let's Encrypt
certificatesResolvers:
  letsencrypt:
    acme:
      email: admin@example.com
      storage: /var/lib/traefik/acme.json
      httpChallenge:
        entryPoint: web
```

#### 2. Пример динамического маршрута: `/etc/traefik/dynamic/app.yml`

```yaml
http:
  routers:
    backend-app:
      rule: "Host(`app.example.com`)"
      entryPoints:
        - websecure
      service: backend-service
      middlewares:
        - secure-headers
        - gzip-compress
      tls:
        certResolver: letsencrypt

  services:
    backend-service:
      loadBalancer:
        passHostHeader: true
        healthCheck:
          path: /healthz
          interval: 10s
          timeout: 3s
        servers:
          - url: "http://127.0.0.1:3000"
          - url: "http://127.0.0.1:3001"

  middlewares:
    secure-headers:
      headers:
        stsSeconds: 31536000
        stsIncludeSubdomains: true
        stsPreload: true
        contentTypeNosniff: true
        browserXssFilter: true
        frameDeny: true

    gzip-compress:
      compress: {}
```

### Сценарий 4: Production unit-файл systemd с изоляцией

Создайте файл `/etc/systemd/system/traefik.service`:

```ini
[Unit]
Description=Traefik Edge Router & Reverse Proxy
Documentation=https://doc.traefik.io/traefik/
After=network-online.target
Wants=network-online.target
RequiresMountsFor=/var/lib/traefik /var/log/traefik

[Service]
Type=simple
User=traefik
Group=traefik

# Валидация конфигурации перед каждым запуском
ExecStartPre=/usr/local/bin/traefik config validate --configfile=/etc/traefik/traefik.yml
ExecStart=/usr/local/bin/traefik --configfile=/etc/traefik/traefik.yml

# Проверка синтаксиса при вызове systemctl reload
ExecReload=/usr/local/bin/traefik config validate --configfile=/etc/traefik/traefik.yml

# Политика перезапуска
Restart=on-failure
RestartSec=3s

# Сетевые права для non-root пользователя (биндинг портов 80 и 443)
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE

# Изоляция и песочница (systemd Sandboxing)
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true

# Разрешенные пути для записи (строгий ProtectSystem=strict)
ReadWritePaths=/var/lib/traefik /var/log/traefik

# Лимиты системных ресурсов процесса
LimitNOFILE=1048576
LimitNPROC=512

# Управление остановкой процесса (Graceful Shutdown)
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=45s

[Install]
WantedBy=multi-user.target
```

Применение и запуск:

```bash
# Перечитывание конфигурации systemd
sudo systemctl daemon-reload

# Включение автозапуска и немедленный старт
sudo systemctl enable --now traefik

# Проверка статуса службы
sudo systemctl status traefik --no-pager
# → Active: active (running) since ...
# → Main PID: 12345 (traefik)
```

> **Важно по плагинам:** Если используются сторонние плагины Traefik (интерпретатор Yaegi), им требуется запись в каталог плагинов (`/var/lib/traefik/plugins-storage`). Убедитесь, что каталог плагинов включен в `ReadWritePaths`, а директива `MemoryDenyWriteExecute=true` отключена (Yaegi выполняет динамическую генерацию кода в памяти).

Подробнее о директивах: [Структура юнит-файла systemd](../../Linux/Core/systemd/systemd_unit_file_structure.md).

### Сценарий 5: Тюнинг ядра Linux под высокие нагрузки (sysctl)

Создайте файл `/etc/sysctl.d/99-traefik.conf` для оптимизации сетевого стека ядра под интенсивный входящий и исходящий TCP-трафик:

```ini
# Размер очереди полностью установленных TCP-соединений (Accept Queue)
net.core.somaxconn = 65535

# Размер очереди неполных соединений (SYN Queue)
net.ipv4.tcp_max_syn_backlog = 65535

# Максимальное число открытых файлов в масштабе всей системы
fs.file-max = 2097152

# Расширение диапазона исходящих портов для проксирования на бэкенды
net.ipv4.ip_local_port_range = 10240 65535

# Безопасное переиспользование сокетов в состоянии TIME_WAIT для исходящих TCP-соединений
net.ipv4.tcp_tw_reuse = 1

# Максимальное количество сокетов, удерживаемых в состоянии TIME_WAIT
net.ipv4.tcp_max_tw_buckets = 1440000

# Таймаут удержания сокета в состоянии FIN-WAIT-2
net.ipv4.tcp_fin_timeout = 15

# Максимальные размеры сетевых буферов приема и передачи
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
```

Применение параметров без перезагрузки сервера:

```bash
sudo sysctl --system
# → * Applying /etc/sysctl.d/99-traefik.conf ...
# → net.core.somaxconn = 65535
# → net.ipv4.tcp_max_syn_backlog = 65535
# → ...
```

### Сценарий 6: Graceful Shutdown и безопасный рестарт службы

Для предотвращения обрыва активных клиентских сессий Traefik и systemd должны работать согласованно:

1. В `traefik.yml` настроен `transport.lifeCycle`:
   - `requestAcceptGraceTimeout: 5s` — продолжает принимать новые рукопожатия 5 секунд после сигнала остановки, компенсируя задержку системного планировщика.
   - `graceTimeout: 30s` — ожидает завершения выполнения активных запросов бэкендами. Суммарное время дренажа: `5s + 30s = 35s`.
2. В `traefik.service` задан `TimeoutStopSec=45s` — с запасом превышает 35 секунд, гарантируя, что systemd не отправит аварийный `SIGKILL` раньше времени.

Тестирование мягкой остановки и рестарта под нагрузкой:

```bash
# 1. Проверка синтаксиса перед любым рестартом
/usr/local/bin/traefik config validate --configfile=/etc/traefik/traefik.yml
# → Configuration OK

# 2. Перезапуск службы
sudo systemctl restart traefik

# 3. Контроль логов завершения процесса
journalctl -u traefik -n 20 --no-pager
# → "Shutting down"
# → "Stopping server gracefully"
# → "Server stopped"
# → "Traefik closed"
```

Подробнее об алгоритмах мягкого завершения: [Graceful Shutdown и Zero-Downtime Deploy в Traefik](./traefik-graceful-shutdown.md).

### Сценарий 7: Ротация логов через logrotate (`copytruncate`)

**Техническая специфика Traefik:** Процесс Traefik держит открытый файловый дескриптор на файл `access.log` и **не поддерживает** переоткрытие дескрипторов по сигналу (в отличие от Nginx с `USR1`). Если использовать стандартное переименование файла (`mv`), Traefik продолжит писать в старый `inode` (в `access.log.1`), а новый файл останется пустым.

Решение: использование директивы `copytruncate` в `/etc/logrotate.d/traefik`:

```conf
/var/log/traefik/*.log {
    daily
    rotate 14
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
    create 0640 traefik traefik
}
```

Проверка конфигурации ротации в режиме отладки:

```bash
sudo logrotate -d /etc/logrotate.d/traefik
# → reading config file /etc/logrotate.d/traefik
# → rotating pattern: /var/log/traefik/*.log after 1 days (14 rotations)
# → copying /var/log/traefik/access.log to /var/log/traefik/access.log.1
# → truncating /var/log/traefik/access.log

# Принудительный тестовый прогон
sudo logrotate -f /etc/logrotate.d/traefik
ls -la /var/log/traefik/
# → access.log
# → access.log.1
```

**Альтернатива для SRE (Вывод в `journald`):** Если на сервере развернут агент сбора логов (Vector, Promtail), отключите `filePath` в `accessLog` и `log` в `traefik.yml` (логи пойдут в `stdout`). В этом случае ротацию и сжатие полностью берет на себя `systemd-journald`.

Подробнее о параметрах ротации: [logrotate: Ротация и сжатие логов](../../Linux/SystemAdministration/Logging/logrotate.md).

### Сценарий 8: Бесшовное обновление бинарника и процедура отката (Rollback)

Регламент безопасного обновления Traefik на production bare-metal хосте.

```bash
# 1. Загрузка новой версии во временный файл
NEW_VERSION="v3.3.5"
ARCH="linux_amd64"
curl -sSL "https://github.com/traefik/traefik/releases/download/${NEW_VERSION}/traefik_${NEW_VERSION}_${ARCH}.tar.gz" -o "/tmp/traefik_${NEW_VERSION}.tar.gz"
tar -xzf "/tmp/traefik_${NEW_VERSION}.tar.gz" -C /tmp traefik
mv /tmp/traefik /tmp/traefik.new
chmod 0755 /tmp/traefik.new

# 2. Проверка валидности текущей рабочей конфигурации НОВЫМ бинарником
/tmp/traefik.new config validate --configfile=/etc/traefik/traefik.yml
# → Configuration OK

# 3. Создание резервной копии текущего работающего бинарника
sudo cp -p /usr/local/bin/traefik /usr/local/bin/traefik.bak

# 4. Атомарная замена исполняемого файла на диске
sudo install -m 0755 -o root -g root /tmp/traefik.new /usr/local/bin/traefik
rm -f "/tmp/traefik_${NEW_VERSION}.tar.gz" /tmp/traefik.new

# 5. Мягкий перезапуск службы
sudo systemctl restart traefik

# 6. Проверка здоровья (Smoke test)
sleep 2
curl -sf http://127.0.0.1:8080/ping
# → OK
/usr/local/bin/traefik version
# → Version: v3.3.5

# 7. ПРОЦЕДУРА ОТКАТА (выполняется только при обнаружении сбоев):
# sudo mv /usr/local/bin/traefik.bak /usr/local/bin/traefik
# sudo systemctl restart traefik
```

### Сценарий 9: Резервное копирование и восстановление `acme.json` и конфигурации

```bash
# 1. Создание каталога резервной копии
BACKUP_DIR="/var/backups/traefik/$(date +%F_%H%M%S)"
sudo mkdir -p "$BACKUP_DIR"

# 2. Создание снимка конфигурации и сертификатов
sudo cp -a /etc/traefik/traefik.yml "$BACKUP_DIR/"
sudo cp -a /etc/traefik/dynamic "$BACKUP_DIR/"
sudo cp -a /var/lib/traefik/acme.json "$BACKUP_DIR/"
sudo cp -a /etc/systemd/system/traefik.service "$BACKUP_DIR/"

# 3. Фиксация прав на бэкап сертификатов
sudo chmod 0600 "$BACKUP_DIR/acme.json"
echo "Backup saved to: $BACKUP_DIR"
```

Восстановление после сбоя или переноса на чистый сервер:

```bash
# Остановка службы перед заменой файлов
sudo systemctl stop traefik

# Восстановление файлов
sudo cp -a "$BACKUP_DIR/traefik.yml" /etc/traefik/
sudo cp -a "$BACKUP_DIR/dynamic" /etc/traefik/
sudo cp -a "$BACKUP_DIR/acme.json" /var/lib/traefik/
sudo cp -a "$BACKUP_DIR/traefik.service" /etc/systemd/system/

# Обязательное восстановление корректных прав (иначе Let's Encrypt откажет в старте)
sudo chown -R root:traefik /etc/traefik
sudo chown -R traefik:traefik /var/lib/traefik
sudo chmod 0600 /var/lib/traefik/acme.json

# Валидация и старт
/usr/local/bin/traefik config validate --configfile=/etc/traefik/traefik.yml
sudo systemctl daemon-reload
sudo systemctl start traefik
```

Подробнее о стратегиях восстановления: [Disaster Recovery и Backup Traefik](./traefik-disaster-recovery.md).

## Операции и команды

Сводная таблица команд сопровождения Traefik на bare-metal хосте:

| Категория | Команда | Назначение / Ожидаемый результат |
| :--- | :--- | :--- |
| **Синтаксис** | `/usr/local/bin/traefik config validate --configfile=/etc/traefik/traefik.yml` | Проверка синтаксиса статической конфигурации (`Configuration OK`) |
| **Журнал** | `journalctl -u traefik -f -o cat` | Непрерывный мониторинг системного журнала сервиса |
| **Сокеты** | `ss -tulpn '( sport = :80 or sport = :443 or sport = :8080 )'` | Проверка открытых слушающих портов и PID процесса |
| **Очереди** | `ss -lnt '( sport = :80 or sport = :443 )'` | Инспекция `Send-Q` (лимит очереди) и `Recv-Q` (число ожидающих `accept()`) |
| **Ресурсы** | `systemctl status traefik` | Проверка статуса, времени аптайма, использования памяти и задач Cgroup |
| **Лимиты** | `cat /proc/$(pgrep -u traefik traefik)/limits \| grep 'open files'` | Проверка фактического лимита `Max open files` (должен быть >= 1048576) |
| **Healthcheck** | `curl -i http://127.0.0.1:8080/ping` | Проверка внутреннего статуса готовности (`HTTP/1.1 200 OK`, тело: `OK`) |
| **Метрики** | `curl -s http://127.0.0.1:8080/metrics \| grep traefik_entrypoint_requests_total` | Сбор метрик Prometheus для локальной проверки |

## Устранение неисправностей

| Проблема | Диагностический признак | Первопричина | Решение |
| :--- | :--- | :--- | :--- |
| **Сбой привязки портов 80/443** | `bind: permission denied` в логах при старте | Процесс запущен от пользователя `traefik`, но в unit-файле отсутствуют capabilities | Добавить `AmbientCapabilities=CAP_NET_BIND_SERVICE` и `CapabilityBoundingSet=CAP_NET_BIND_SERVICE` в `traefik.service` |
| **Сбой запуска из-за прав на сертификаты** | `permissions are too open for /var/lib/traefik/acme.json` | Права на файл `acme.json` отличны от `0600` | Выполнить `sudo chmod 0600 /var/lib/traefik/acme.json` и `sudo chown traefik:traefik ...` |
| **Отказ записи ProtectSystem** | `read-only file system` при ротации или обновлении ACME | Включен `ProtectSystem=strict`, а путь записи не объявлен | Добавить целевой каталог в директиву `ReadWritePaths=` unit-файла |
| **Пустой access.log после ротации** | Размер лога 0 байт, данные пишутся в `access.log.1` | В logrotate использовано обычное переименование вместо `copytruncate` | Добавить директиву `copytruncate` в `/etc/logrotate.d/traefik` |
| **Ошибки `Too many open files`** | Ошибки сокетов `accept: too many open files` под нагрузкой | Превышен лимит дескрипторов процесса | Указать `LimitNOFILE=1048576` в `traefik.service` и перезапустить сервис |
| **Обрывы соединений при рестарте** | Клиенты получают `Connection reset by peer` во время деплоя | `graceTimeout` отсутствует или `TimeoutStopSec` меньше времени дренажа | Настроить `transport.lifeCycle.graceTimeout: 30s` и выставить `TimeoutStopSec=45s` |
| **Ошибки синтаксиса роутеров** | В логах: `cannot create service: field not found` | Ошибка в YAML-файле dynamic provider | Выполнить валидацию YAML линтером, проверить журнал `journalctl -u traefik` |

## Рекомендации

- **Принцип наименьших привилегий:** Никогда не запускайте бинарный файл Traefik от пользователя `root`. Назначайте привилегию прослушивания системных портов исключительно через `AmbientCapabilities=CAP_NET_BIND_SERVICE`.
- **Предварительная валидация (ExecStartPre):** Всегда держите вызов `traefik config validate` в директиве `ExecStartPre` unit-файла. Это исключит падение production-сервиса при опечатках в статическом файле `traefik.yml`.
- **Защита acme.json:** Файл `acme.json` содержит приватные ключи сертификатов. Права доступа строго `0600`, владелец `traefik:traefik`. Храните регулярный бэкап этого файла в изолированном защищенном хранилище.
- **Отказоустойчивость на bare-metal:** Для организации высокой доступности без облачных балансировщиков используйте пару серверов Traefik под управлением **Keepalived** с общим виртуальным IP (VIP) и проверкой доступности через `/ping`. Подробнее: [Keepalived — обзор и настройка высокой доступности](../../Networking/ServicesAndTools/keepalived_overview.md).
- **Динамическая конфигурация в GitOps:** Храните файлы каталога `/etc/traefik/dynamic/` в Git-репозитории и доставляйте их на хост средствами Ansible или скриптов CI/CD. Горячее применение через `watch: true` гарантирует нулевой простой без перезапуска службы.

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — общая архитектура, статические и динамические параметры, entryPoints.
- [High Availability Traefik](./traefik-high-availability.md) — кластеризация на bare-metal, Keepalived VIP, active-passive и active-active схемы.
- [Graceful Shutdown и Zero-Downtime Deploy в Traefik](./traefik-graceful-shutdown.md) — детальный разбор жизненного цикла соединений и таймаутов дренажа.
- [Disaster Recovery и Backup Traefik](./traefik-disaster-recovery.md) — регламенты резервного копирования и восстановления после аварий.
- [Наблюдаемость Traefik](./traefik-observability.md) — экспорт метрик в Prometheus и структурированное логирование.
- [Структура юнит-файла systemd](../../Linux/Core/systemd/systemd_unit_file_structure.md) — параметры безопасности и управления службами systemd.
- [Linux Capabilities](../../Linux/Security/Mechanisms/Capabilities.md) — теория и практика применения капацити ядра Linux.
- [logrotate: Ротация и сжатие логов](../../Linux/SystemAdministration/Logging/logrotate.md) — детальный справочник параметров утилиты logrotate.
- [Keepalived — обзор и настройка высокой доступности (HA)](../../Networking/ServicesAndTools/keepalived_overview.md) — настройка VRRP и виртуальных IP для bare-metal инфраструктуры.