# Traefik на bare-metal/VM: установка, systemd, эксплуатация

## Определения

**Bare-metal/VM-развертывание** — запуск Traefik как обычного системного процесса (бинарный файл) без контейнеров: пакетирование под systemd, работа с сигналами, ротация логов.

**Gracious shutdown (мягкое завершение)** — процесс корректной остановки: Traefik перестает принимать новые соединения, дожидается обработки активных и завершает работу с кодом `0`.

**Static config reload** — перезагрузка статической части конфигурации (entrypoints, providers, certResolvers). В Traefik **не бывает** перезагрузки статики по `SIGHUP`: статические опции применяются только при старте процесса. Динамическая часть (роутеры, сервисы, middleware) перечитывается провайдерами в рантайме без перезапуска.

**logrotate** — стандартный механизм ротации файловых логов: резка по размеру/времени, сжатие, удаление старых файлов; в контексте Traefik применяется к `access.log` (см. [Наблюдаемость Traefik](./traefik-observability.md)).

## Базовые концепции

### Запуск Traefik без Docker: чем отличается

Плюсы bare-metal: нет зависимости от демона Docker, ниже накладные расходы, проще интеграция в классические конфигурации с Nginx/Apache на тех же хостах, полноценное управление через systemd (автозапуск, restart, лимиты).

Минусы: нет встроенного сервис-дискавери по меткам контейнеров — придется использовать File-провайдер, KV-хранилища или Consul Catalog/Nomad (см. [Провайдеры конфигурации](./traefik-providers-advanced.md)); автообновления сертификатов и маршрутов завязаны на `providers.file.watch`; обновление версии — ручной процесс (в отличие от смены тега образа).

### Каким провайдером пользоваться без Docker

Для статического окружения (VM, bare-metal) основной способ динамической конфигурации — **File provider** с директорией и `watch: true`:

```yaml
providers:
  file:
    directory: /etc/traefik/dynamic
    watch: true
```

При изменении любого файла в директории Traefik пересчитывает маршруты без перезапуска процесса. Статические опции (сам `providers`, entrypoints, ACME) — только в `/etc/traefik/traefik.yml`, требуют рестарта.

### Сигналы и жизненный цикл процесса

| Сигнал | Поведение Traefik |
| :--- | :--- |
| `SIGTERM` / `SIGINT` | Мягкое завершение: перестает принимать новые соединения, ждет завершения активных (до лимитов `transport.lifeCycle`), выходит с кодом `0`. |
| `SIGHUP` | **Нет** перезагрузки конфигурации. Используется только для запуска `ExecReload`-команды в unit-файле (обычно для проверки конфига). |
| `SIGKILL` | Принудительное завершение (только при `TimeoutStopSec` или аварии): возможна потеря сессий и порча `acme.json`. |

Параметры мягкого завершения задаются на entrypoint (см. [Обзор Traefik](./traefik_overview.md)):

```yaml
entryPoints:
  websecure:
    address: ":443"
    transport:
      lifeCycle:
        requestAcceptGraceTimeout: 5s   # добор входящих соединений при shutdown
        graceTimeout: 15s               # ожидание активных соединений перед выходом
```

## Практические сценарии

### Сценарий 1: Установка бинарника (Debian/Ubuntu, amd64)

```bash
# Последний стабильный релиз (проверяйте актуальные версии на GitHub releases)
TRAEFIK_VERSION=v3.7

# Загрузка архива и контрольной суммы
curl -LO "https://github.com/traefik/traefik/releases/download/${TRAEFIK_VERSION}/traefik_${TRAEFIK_VERSION#v}_linux_amd64.tar.gz"
curl -LO "https://github.com/traefik/traefik/releases/download/${TRAEFIK_VERSION}/traefik_${TRAEFIK_VERSION#v}_checksums.txt"

# Проверка контрольной суммы
grep "traefik_" "$(ls traefik_${TRAEFIK_VERSION#v}_checksums.txt)" | sha256sum -c -
# → traefik_v3.7_linux_amd64.tar.gz: OK

# Распаковка и установка
tar -xzf "traefik_${TRAEFIK_VERSION#v}_linux_amd64.tar.gz"
sudo mv traefik /usr/local/bin/
traefik version
# → Traefik v3.7.0
```

### Сценарий 2: Создание пользователя и структуры каталогов

```bash
sudo useradd -r -s /usr/sbin/nologin -d /var/lib/traefik traefik
sudo mkdir -p /etc/traefik/dynamic \
             /var/lib/traefik \
             /var/log/traefik
sudo touch /var/lib/traefik/acme.json
sudo chmod 600 /var/lib/traefik/acme.json
sudo chown -R traefik:traefik /etc/traefik /var/lib/traefik /var/log/traefik
```

### Сценарий 3: Unit-файл systemd

`/etc/systemd/system/traefik.service`:

```ini
[Unit]
Description=Traefik reverse proxy
Documentation=https://doc.traefik.io/traefik/
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=traefik
Group=traefik
ExecStart=/usr/local/bin/traefik --configfile=/etc/traefik/traefik.yml
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5

# Ограничения безопасности
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/traefik /var/log/traefik
LimitNOFILE=100000
LimitNPROC=10000

# Ожидание мягкого завершения до SIGKILL
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

Применение:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now traefik
sudo systemctl status traefik
# → Active: active (running)
```

> Примечание: `ProtectSystem=strict` делает корневую ФС read-only. Traefik должен писать только в `acme.json` и логи — пути указаны в `ReadWritePaths`. Плагинам (Yaegi) нужна запись в каталог кеша плагинов — при использовании плагинов добавьте его в `ReadWritePaths`.

### Сценарий 4: Graceful shutdown и рестарт без потерь

Проверка, что процесс корректно обрабатывает сигнал:

```bash
# Отправить SIGTERM вручную и наблюдать за логами
sudo kill -TERM $(pgrep -f 'traefik --configfile')
# → журнал: "Starting TCP Server" ... "Stopping" -> процесс выходит с кодом 0

# Рестарт через systemd (мягкое завершение затем старт)
sudo systemctl restart traefik
# Проверка отсутствия обрывов во время рестарта (извне)
while true; do curl -so /dev/null -w '%{http_code}\n' https://app.example.com/; sleep 0.2; done
# → 200 на протяжении всего рестарта
```

При нулевом даунтайме рестарт с одним инстансом гарантировать нельзя (см. [High Availability](./traefik-high-availability.md)).

### Сценарий 5: Ротация access-логов через logrotate

Если `accessLog` пишет в файл, обязательна ротация. `/etc/logrotate.d/traefik`:

```conf
/var/log/traefik/access.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    sharedscripts
    postrotate
        # access log открывается на запись; переоткрытие после ротации не нужно,
        # но следующий запрос создаст новый файл автоматически
    endscript
}
```

Замечания:

- Traefik при ротации продолжает писать в старый `inode`, пока не получит «переоткрыть файл». Для принудительного переоткрытия используют `TimeStampFormat`/перезапуск или запись логов в stdout + сборку агентом (Vector/Fluent Bit). Самый простой устойчивый вариант — писать access-логи в stdout (`filePath: ""`/`/dev/stdout`) и забирать их агентом сбора логов (см. [Наблюдаемость Traefik](./traefik-observability.md)).
- Если лог пишется в файл и ротация обязательна — выставляйте `create 0644 traefik traefik` в конфиге logrotate или используйте `su traefik traefik` для корректных прав.

### Сценарий 6: Резервное копирование и восстановление acme.json

```bash
# Резервная копия (процесс при этом не останавливаем)
sudo cp -a /var/lib/traefik/acme.json "/backups/acme.json.$(date +%F).bak"
# Восстановление: остановить Traefik, подменить файл, запустить
sudo systemctl stop traefik
sudo cp acme.json /var/lib/traefik/acme.json
sudo chown traefik:traefik /var/lib/traefik/acme.json && sudo chmod 600 /var/lib/traefik/acme.json
sudo systemctl start traefik
```

Ограничения: `acme.json` нельзя восстанавливать параллельно с работающим процессом другого инстанса (конфликт записи). Подробнее про ACME и права — [Обзор Traefik](./traefik_overview.md).

### Сценарий 7: Полное резервное копирование и восстановление конфигурации

```bash
# Структура для бэкапа
TRAEFIK_BACKUP_DIR="/backups/traefik/$(date +%F)"

# 1. Статическая конфигурация
sudo cp -a /etc/traefik/traefik.yml "$TRAEFIK_BACKUP_DIR/"

# 2. Динамическая конфигурация
sudo cp -a /etc/traefik/dynamic "$TRAEFIK_BACKUP_DIR/"

# 3. Сертификаты
sudo cp -a /var/lib/traefik/acme.json "$TRAEFIK_BACKUP_DIR/"

# 4. Права и владелец
sudo chown -R traefik:traefik "$TRAEFIK_BACKUP_DIR"
sudo chmod 600 "$TRAEFIK_BACKUP_DIR/acme.json"

# 5. Проверка бэкапа
ls -la "$TRAEFIK_BACKUP_DIR"
```

Восстановление после полной потери ноды:

```bash
# 1. Установка Traefik (бинарник)
sudo cp traefik /usr/local/bin/

# 2. Восстановление пользователя и каталогов
sudo useradd -r -s /usr/sbin/nologin -d /var/lib/traefik traefik
sudo mkdir -p /etc/traefik/dynamic /var/lib/traefik /var/log/traefik

# 3. Восстановление файлов из бэкапа
sudo cp -a /backups/traefik/2026-09-24/traefik.yml /etc/traefik/
sudo cp -a /backups/traefik/2026-09-24/dynamic /etc/traefik/
sudo cp -a /backups/traefik/2026-09-24/acme.json /var/lib/traefik/

# 4. Права
sudo chown -R traefik:traefik /etc/traefik /var/lib/traefik /var/log/traefik
sudo chmod 600 /var/lib/traefik/acme.json

# 5. Валидация конфигурации
traefik config validate --configfile=/etc/traefik/traefik.yml

# 6. Запуск
sudo systemctl enable --now traefik
```

Ротация бэкапов:

```bash
# Хранить 7 дней
find /backups/traefik -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \;
```

## Операции и команды

```bash
# Проверка конфигурации синтаксиса ДО старта
traefik config validate --configfile=/etc/traefik/traefik.yml
# → Configuration OK

# Логи процесса
journalctl -u traefik -f

# Топ открытых соединений
ss -tlnp | grep traefik

# Потребление памяти/ресурсов
systemctl status traefik

# Текущие используемые версии Go/Traefik
traefik version
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Не стартует: permission denied на acme.json** | Права не `600` или владелец не `traefik` | `chown traefik:traefik` + `chmod 600` |
| **`ProtectSystem` блокирует запись** | Плагины/кэш пишут вне `ReadWritePaths` | Добавьте каталог кеша плагинов в `ReadWritePaths` |
| **Ротация обрывает лог/Access log пуст** | logrotate не переоткрывает дескриптор | Писать в stdout + агент сбора, либо настроить `su`/`create` в logrotate |
| **Сертификаты не продлеваются на новом хосте** | `acme.json` не перенесен или без прав 600 | Восстановить файл бэкапа по Сценарию 6 |
| **SIGHUP не перезагружает конфигурацию** | Ожидание `reload` из мира Nginx | Статика — только рестарт; динамика перечитывается провайдером (`watch: true`) |
| **SIGTERM не завершает процесс в лимит** | Долгие запросы бэкендов | Увеличьте `graceTimeout`, `TimeoutStopSec` или настройте таймауты upstream |

## Рекомендации

- Для bare-metal всегда закрепляйте версию (`v3.x`) и проверяйте контрольную сумму (Сценарий 1).
- Обязательны: выделенный пользователь, `ProtectSystem=strict`, `NoNewPrivileges`, `LimitNOFILE`.
- Статику меняйте через GitOps (config в пакетном виде), динамику — через `watch`-каталог.
- Acess-логи большого объема пишите в stdout и собирайте агентом, а не в `filePath` (проще мониторинг и ротация).
- Перед каждым рестартом прогоняйте `traefik config validate` — включая в CI.
- Полный набор приемов нулевого даунтайма при рестартах — в [High Availability](./traefik-high-availability.md).

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — статическая конфигурация, entrypoints, `transport.lifeCycle`.
- [High Availability Traefik](./traefik-high-availability.md) — несколько инстансов, rolling-обновление, ACME в HA.
- [Linux: systemd (юнит-файлы)](../../Linux/Core/systemd/systemd_unit_file_structure.md) — полный справочник директив юнит-файлов.
- [Logrotate](../../Linux/SystemAdministration/Logging/logrotate.md) — справочник по ротации логов в Linux.