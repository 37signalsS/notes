# Syslog — Протокол системного журналирования

## Определения

**Syslog** — стандартный протокол для передачи системных сообщений (логов) между сетевыми устройствами и серверами. Определён в RFC 5424 (современный формат, 2009) и RFC 3164 (устаревший BSD-формат, 2001).

**Ключевая особенность:** Syslog разделяет **отправку** (source), **транспорт** (UDP/TCP/TLS) и **обработку** (receiver/relay). Это позволяет строить централизованные системы логирования (ELK, Loki, Graylog) с маршрутизацией сообщений по facility и severity.

> **См. также:** [rsyslog: настройка в Linux](../../Linux/SystemAdministration/Logging/rsyslog.md), [Docker: лог-драйвер syslog](../../Docker/Docker_logs/docker_centralized_logging.md), [SNMP: альтернатива логированию](./snmp_overview.md)

## Основные концепции

### Структура сообщения (RFC 5424)

```
 SYSLOG-MSG      = HEADER SP STRUCTURED-DATA [SP MSG]
 HEADER          = PRI VERSION SP TIMESTAMP SP HOSTNAME SP APP-NAME SP PROCID SP MSGID
```

| Поле | Описание | Пример |
|---|---|---|
| **PRI** | Приоритет (facility × 8 + severity) | `<34>` (auth + crit) |
| **VERSION** | Версия формата (1 = RFC 5424) | `1` |
| **TIMESTAMP** | ISO 8601 время с timezone | `2026-08-26T10:30:00.000Z` |
| **HOSTNAME** | Имя или IP отправителя | `web-prod-01.example.com` |
| **APP-NAME** | Имя приложения | `nginx`, `sshd`, `kernel` |
| **PROCID** | PID процесса | `1234` |
| **MSGID** | Идентификатор сообщения (RFC 3339) | `-`, `dhcp-ack` |
| **STRUCTURED-DATA** | Структурированные данные (KV) | `[exampleSDID@32473 event="auth"]` |
| **MSG** | Произвольный текст сообщения | `Failed password for root` |

### Facility — категория источника

| Facility | Код | Описание |
|---|---|---|
| `kern` | 0 | Ядро Linux |
| `user` | 1 | Пользовательские процессы |
| `mail` | 2 | Почтовый сервер |
| `daemon` | 3 | Системные демоны |
| `auth` | 4 | Аутентификация (login, sudo) |
| `syslog` | 5 | Сам syslog |
| `lpr` | 6 | Принтеры |
| `news` | 7 | Usenet news |
| `uucp` | 8 | UUCP |
| `cron` | 9 | Cron-задачи |
| `authpriv` | 10 | Приватная аутентификация (SSH ключи) |
| `ftp` | 11 | FTP-сервер |
| `ntp` | 12 | Синхронизация времени |
| `security` | 13 | Безопасность |
| `console` | 14 | Консоль |
| `local0`–`local7` | 16–23 | Пользовательские (для приложений) |

### Severity — важность сообщения

| Severity | Код | Описание |
|---|---|---|
| `emerg` | 0 | Система неизбежно падает (panic) |
| `alert` | 1 | Требуется немедленное действие |
| `crit` | 2 | Критические условия |
| `err` | 3 | Ошибки |
| `warning` | 4 | Предупреждения |
| `notice` | 5 | Нормальные, но значимые события |
| `info` | 6 | Информационные сообщения |
| `debug` | 7 | Отладочная информация |

### Расчёт PRI

```
PRI = facility × 8 + severity

Примеры:
  auth + crit    = 4 × 8 + 2 = 34
  local0 + info  = 16 × 8 + 6 = 134
  kern + warning = 0 × 8 + 4 = 4
```

### Транспорт

| Протокол | Порт | Надёжность | Шифрование | Применение |
|---|---|---|---|---|
| **UDP** | 514 | Ненадёжный | Нет | Легковесная доставка, loss-tolerant логи |
| **TCP** | 514 | Надёжный | Нет | Гарантия доставки, централизованные логи |
| **TCP+TLS** | 6514 | Надёжный | Да (TLS) | Безопасная передача (compliance, PCI DSS) |
| **RELP** | 514 | Надёжный | Опционально | Reliable Event Logging Protocol (rsyslog) |

**RELP (Reliable Event Logging Protocol, RFC 5842):**
- Расширение TCP с подтверждением доставки каждого сообщения.
- Решает проблему потери TCP-соединения: после реконнекта ретранслирует неподтверждённые сообщения.
- Используется в rsyslog как `imrelp` / `omrelp`.

### Маршрутизация и фильтрация

Syslog-сообщения маршрутизируются по ** facility и severity**:

```
# Синтаксис rsyslog:
facility.severity    action

# Примеры:
auth,authpriv.*      /var/log/auth.log
*.*;auth,authpriv.none  /var/log/syslog
local0.*             @syslog-server:514       # UDP
local0.*             @@syslog-server:514      # TCP
local0.*             @@(o)syslog-server:6514  # TCP+TLS
```

### Централизованная архитектура логирования

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│   Web Server │   │  App Server  │   │    Database  │
│  (rsyslog)   │   │  (rsyslog)   │   │  (rsyslog)   │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                  │
       └──────────┬───────┴──────────┬───────┘
                  │                  │
           ┌──────▼──────┐   ┌──────▼──────┐
           │   Relay 1   │   │   Relay 2   │
           │  (rsyslog)  │   │  (rsyslog)  │
           └──────┬──────┘   └──────┬──────┘
                  │                  │
                  └──────────┬───────┘
                             │
                      ┌──────▼──────┐
                      │  Central    │
                      │  (Loki/     │
                      │  Elasticsearch│
                      └─────────────┘
```

**Компоненты:**
- **Source:** Приложение/сервис, генерирующий логи
- **Relay:** Промежуточный сервер для маршрутизации и агрегации
- **Collector:** Центральное хранилище (Loki, Elasticsearch, Graylog)
- **Forwarder:** Агент на хосте (rsyslog, syslog-ng, Fluentd)

## Практический блок

### Настройка rsyslog как sender (TCP+TLS)

```conf
# /etc/rsyslog.d/50-forward.conf

# Доверие сертификату
DefaultNetstreamDriverCAFile /etc/ssl/certs/ca-certificates.crt

# Отправка через TCP+TLS
action(type="omfwd"
       target="syslog.example.com"
       port="6514"
       protocol="tcp"
       stream.driver="gtls"
       stream.driver.caFile="/etc/ssl/certs/ca-certificates.crt"
       template="RSYSLOG_SyslogProtocol23Format"
       queue.type="linkedList"
       queue.size="10000"
       queue.filename="fwd_queue"
       action.resumeRetryCount="-1")
```

### Настройка rsyslog как receiver (TCP+TLS)

```conf
# /etc/rsyslog.d/01接收.conf

module(load="imtcp"
       StreamDriver.Name="gtls"
       StreamDriver.Mode="1"
       StreamDriver.Authmode="x509/name"
       PermitRemoteOpen="on")

input(type="imtcp" port="6514")

# Маршрутизация по facility
template(name="PerHost" type="string"
         string="/var/log/remote/%HOSTNAME%/%PROGRAMNAME%.log")

if $inputname == "imtcp" then {
    action(type="omfile" dynaFile="PerHost")
    stop
}
```

### Docker: лог-драйвер syslog

```bash
# Запуск контейнера с отправкой логов в syslog
docker run -d \
  --log-driver=syslog \
  --log-opt syslog-address=tcp://syslog-server:514 \
  --log-opt syslog-facility=daemon \
  --log-opt tag="docker/{{.Name}}" \
  my-app
```

```yaml
# Docker Compose
services:
  app:
    image: my-app
    logging:
      driver: syslog
      options:
        syslog-address: "tcp://syslog-server:514"
        syslog-facility: "daemon"
        tag: "docker/{{.Name}}"
```

### Сравнение rsyslog vs syslog-ng vs journald

| Характеристика | rsyslog | syslog-ng | journald |
|---|---|---|---|
| **Формат** | RFC 5424, BSD | RFC 5424, BSD, CSV, JSON | Бинарный (structured) |
| **Транспорт** | UDP, TCP, TLS, RELP | UDP, TCP, TLS, RELP, MQTT | Unix socket |
| **Маршрутизация** | Фильтры, properties, templates | Паттерны, parsers, rewrite | journalctl фильтры |
| **Производительность** | Высокая (linkedList queues) | Высокая (correlate, junction) | Средняя |
| **Персистентность** | Queue на диск (queue.filename) | Disk buffer, Journal | /var/log/journal |
| **Интеграция** | Prometheus, Elasticsearch, Kafka | Prometheus, Elasticsearch, Kafka | syslog, rsyslog |
| **Использование** | RHEL, Debian, Ubuntu | S systemd-based, hardened | systemd (по умолчанию) |

### Типичные проблемы

| Проблема | Причина | Решение |
|---|---|---|
| Логи дублируются в `/var/log/syslog` | `ForwardToSyslog=yes` в journald.conf | Отключить: `ForwardToSyslog=no` |
| Потеря логов при переполнении диска | Disk queue заполнен | Настроить `queue.maxdiskspace`, `queue.size` |
| TCP-соединение разрывается | Firewall, таймаут | Проверить `ss -tnp | grep 514`, настроить keepalive |
| Неверный формат TIMESTAMP | RFC 3164 vs RFC 5424 | Использовать `RSYSLOG_SyslogProtocol23Format` |
| TLS handshake failed | Неверный сертификат | Проверить `openssl s_client -connect host:6514` |

## Дополнительная информация

- **RFC 5424** — The Syslog Protocol (основной стандарт)
- **RFC 3164** — The BSD syslog Protocol (устаревший)
- **RFC 5842** — RELP (Reliable Event Logging Protocol)
- **RFC 5425** — Syslog over TLS
- **RFC 5426** — Syslog over UDP
- **RFC 8460** — SMTP TLS Reporting (связь с syslog)
- **[rsyslog: настройка в Linux](../../Linux/SystemAdministration/Logging/rsyslog.md)** — практическая конфигурация
- **[Docker: лог-драйверы](../../Docker/Docker_logs/docker_centralized_logging.md)** — интеграция с Docker
- **[Vector:替代 syslog](../../Vector/vector_overview.md)** — современная замена rsyslog
