# Структурированное логирование приложений в journald

## Определения

**Структурированное логирование (Structured Logging)** — метод записи логов в машиночитаемом формате, где каждое поле имеет имя и тип. В контексте journald это означает, что сообщение состоит из набора пар `ключ=значение`, а не из неструктурированного текста. Структурированные логи позволяют выполнять эффективный поиск по полям без регулярных выражений.

**Пользовательские поля (User-defined Fields)** — дополнительные метаданные, добавляемые приложением к сообщению через API journald (например, `REQUEST_ID`, `TRACE_ID`, `USER_ID`). Пользовательские поля индексируются и доступны для фильтрации через `journalctl`.

**Транспорт доставки (Transport)** — механизм, с помощью которого приложение отправляет логи в journald: нативный протокол journald (Unix-сокет), syslog-сокет (`/dev/log`), или stdout/stderr с перехватом systemd.

**Фасилитиет syslog (Syslog Facility)** — числовой идентификатор (0–23), определяющий категорию источника лога (auth, daemon, local0–local7). Используется для маршрутизации и фильтрации сообщений в rsyslog и journald.

## Основные концепции

### Механизмы доставки логов в journald

Приложение может отправлять логи в journald тремя способами, каждый из которых имеет компромиссы:

| Механизм | Метод | Структурированные поля | Метаданные | Зависимости |
| :--- | :--- | :--- | :--- | :--- |
| **Нативный API (sd_journal_send)** | Unix-сокет `@/org/systemd/journal/stdout` | Полная поддержка пользовательских полей | Автоматические (PID, UID,_COMM) | `libsystemd` |
| **Syslog-сокет** | `/dev/log` или `/run/systemd/journal/stdout` | Ограничено (только MESSAGE + SYSLOG_*) | Базовые (SYSLOG_IDENTIFIER, SYSLOG_FACILITY) | Нет |
| **stdout/stderr** | Перехват systemd из unit-файла | Только MESSAGE | Минимальные (_PID, _COMM) | systemd (Type=simple/notify) |

**Рекомендация для продакшена:** Используйте нативный API (`sd_journal_send`) для приложений, требующих rich-метаданные (microservices, API). Для простых скриптов и cron-задач — syslog-сокет через `logger`. Для контейнеров — stdout/stderr (перехватывается автоматически).

### Нативный API: sd_journal_send

Библиотека `libsystemd` предоставляет функцию `sd_journal_send()` для отправки структурированных сообщений:

**На C:**
```c
#include <systemd/sd-journal.h>

sd_journal_send(
    "MESSAGE=Request processed successfully",
    "REQUEST_ID=req-abc-123",
    "USER_ID=1000",
    "ENDPOINT=/api/v1/users",
    "STATUS_CODE=200",
    "RESPONSE_TIME_MS=42",
    "PRIORITY=%d", LOG_INFO,
    NULL
);
```

**На Python (через python-systemd):**
```python
import systemd.journal

logger = systemd.journal.JournaldLogHandler()
logger.set_identifier("myapp")

# Структурированное сообщение с пользовательскими полями
logger.info(
    "Request processed",
    extra={
        "REQUEST_ID": "req-abc-123",
        "USER_ID": 1000,
        "ENDPOINT": "/api/v1/users",
        "STATUS_CODE": 200,
        "RESPONSE_TIME_MS": 42,
    }
)
```

**На Go (через go-systemd):**
```go
import "github.com/coreos/go-systemd/journal"

journal.Send(
    "Request processed",
    journal.PriInfo,
    map[string]string{
        "REQUEST_ID":      "req-abc-123",
        "USER_ID":         "1000",
        "ENDPOINT":        "/api/v1/users",
        "STATUS_CODE":     "200",
        "RESPONSE_TIME_MS": "42",
    },
)
```

**Фильтрация пользовательских полей:**
```bash
# Поиск по пользовательскому полю REQUEST_ID
journalctl REQUEST_ID=req-abc-123

# Все логи конкретного ENDPOINT
journalctl ENDPOINT=/api/v1/users --since "1 hour ago"

# Комбинированный запрос: конкретный сервис + пользовательское поле
journalctl -u myapp STATUS_CODE=500 --since today
```

### Структурированное логирование через stdout (JSON)

Для приложений, запускаемых через systemd (Type=simple, Type=notify), stdout/stderr автоматически перехватываются journald. Рекомендуемый формат — JSON:

```ini
# /etc/systemd/system/myapp.service
[Service]
Type=notify
ExecStart=/usr/bin/myapp
# Стандартный вывод перехватывается journald
StandardOutput=journal
StandardError=journal
```

**Пример JSON-вывода приложения:**
```json
{"timestamp":"2024-05-01T12:00:00Z","level":"info","message":"Request processed","request_id":"req-abc-123","user_id":1000,"endpoint":"/api/v1/users","status_code":200,"response_time_ms":42}
```

**Важно:** journald парсит JSON-строки и индексирует их как единое поле `MESSAGE`. Для извлечения отдельных полей из JSON используйте `jq`:
```bash
# Извлечение поля request_id из JSON-сообщений
journalctl -u myapp -o json --since "1h ago" | jq -r '.MESSAGE | fromjson | .request_id'

# Подсчёт количества ошибок по status_code
journalctl -u myapp -o json --since today | \
  jq -r '.MESSAGE | fromjson | select(.status_code >= 500) | .status_code' | \
  sort | uniq -c | sort -rn
```

### Маппинг syslog facility на journald

При использовании syslog-сокета или `logger` facility определяет категорию лога:

| Facility | Код | SYSLOG_FACILITY | Типичное использование |
| :--- | :--- | :--- | :--- |
| `kern` | 0 | `kern` | Ядро |
| `user` | 1 | `user` | Пользовательские процессы |
| `mail` | 2 | `mail` | Почтовый сервер |
| `daemon` | 3 | `daemon` | Системные демоны |
| `auth` | 4 | `auth` | Аутентификация |
| `syslog` | 5 | `syslog` | Сам syslog |
| `lpr` | 6 | `lpr` | Принтер |
| `news` | 7 | `news` | NNTP |
| `uucp` | 8 | `uucp` | UUCP |
| `cron` | 9 | `cron` | Cron |
| `authpriv` | 10 | `authpriv` | Приватная аутентификация |
| `ftp` | 11 | `ftp` | FTP |
| `local0`–`local7` | 16–23 | `local0`–`local7` | Пользовательские (рекомендуется для приложений) |

**Пример с logger:**
```bash
# Отправка в journald через syslog-сокет с указанием facility
logger -p local0.info -t myapp "Request processed successfully"

# Фильтрация по facility в journalctl
journalctl -t myapp
journalctl SYSLOG_FACILITY=16  # local0
```

### Пользовательские поля: соглашения именования

Для единообразия в масштабируемых системах рекомендуется использовать стандартизированные имена пользовательских полей:

| Поле | Описание | Пример |
| :--- | :--- | :--- |
| `REQUEST_ID` | Уникальный идентификатор запроса | `req-abc-123` |
| `TRACE_ID` | Идентификатор трассировки (OpenTelemetry) | `trace-xyz-789` |
| `SPAN_ID` | Идентификатор спана | `span-456` |
| `USER_ID` | Идентификатор пользователя | `1000` |
| `SESSION_ID` | Идентификатор сессии | `sess-001` |
| `ENDPOINT` | API endpoint | `/api/v1/users` |
| `STATUS_CODE` | HTTP status code | `200`, `500` |
| `RESPONSE_TIME_MS` | Время ответа в миллисекундах | `42` |
| `ERROR_CODE` | Код ошибки приложения | `E001` |
| `COMPONENT` | Компонент системы | `auth-service` |

**Важно:** Имена полей в journald чувствительны к регистру и не должны начинаться с подчёркивания (это зарезервировано для системных полей). Используйте верхний регистр: `REQUEST_ID`, а не `_request_id`.

### Интерпретация пользовательских полей в journalctl

Пользовательские поля доступны для фильтрации и вывода:

```bash
# Фильтрация по пользовательскому полю
journalctl REQUEST_ID=req-abc-123

# Вывод только определённых полей (verbose формат)
journalctl -u myapp -o verbose --since "1h ago" | grep -E "REQUEST_ID|STATUS_CODE|MESSAGE"

# JSON-вывод с пользовательскими полями
journalctl -u myapp -o json --since "1h ago" -n 1 | jq .
# → {
#   "REQUEST_ID": "req-abc-123",
#   "STATUS_CODE": "200",
#   "MESSAGE": "Request processed",
#   "_PID": "1234",
#   "_SYSTEMD_UNIT": "myapp.service",
#   ...
# }

# Список всех доступных полей текущего журнала
journalctl --fields

# Поиск по нескольким пользовательским полям
journalctl -u myapp REQUEST_ID=req-abc-123 STATUS_CODE=500
```

### Интеграция с корреляцией (Correlation IDs)

В микросервисной архитектуре `REQUEST_ID` или `TRACE_ID` передаётся через все компоненты системы. В journald это выглядит так:

```bash
# Получение всех логов, связанных с одним запросом, across services
journalctl --since "5 min ago" | grep "req-abc-123"

# Или с использованием пользовательских полей (если все сервисы пишут REQUEST_ID)
journalctl REQUEST_ID=req-abc-123

# Корреляция через JSON
journalctl -o json --since "5 min ago" | \
  jq -r 'select(.REQUEST_ID == "req-abc-123") | "\(.SYSLOG_IDENTIFIER): \(.MESSAGE)"'
```

**Паттерн для приложений:**
1. API-шлюз генерирует `REQUEST_ID` и передаёт его в заголовке `X-Request-ID`
2. Каждый сервис извлекает `REQUEST_ID` из заголовка и включает его в логи
3. При анализе инцидента: `journalctl REQUEST_ID=<id>` — и все логи из всех сервисов

### Сравнение подходов к структурированному логированию

| Критерий | sd_journal_send | logger (syslog) | stdout JSON |
| :--- | :--- | :--- | :--- |
| **Структурированные поля** | Полная поддержка | Ограничено (SYSLOG_*) | Через jq |
| **Производительность** | Высокая (Unix-сокет) | Средняя (syslog-сокет) | Высокая (перехват) |
| **Автоматические метаданные** | Полные (PID, UID, COMM, EXE) | Базовые (SYSLOG_IDENTIFIER) | Минимальные |
| **Зависимости** | `libsystemd` | Нет | systemd |
| **Для контейнеров** | Не рекомендуется | Возможно | Рекомендуется |
| **Для скриптов/cron** | Сложно | Рекомендуется | Невозможно |
| **JSON-native** | Да (через пользовательские поля) | Нет | Да |

## Практические сценарии

### Настройка приложения на нативный API

**Шаг 1: Установка зависимостей**
```bash
# Debian/Ubuntu
sudo apt install libsystemd-dev

# RHEL/CentOS
sudo dnf install systemd-devel
```

**Шаг 2: Компиляция**
```bash
gcc -o myapp myapp.c -lsystemd
```

**Шаг 3: Systemd unit-файл**
```ini
# /etc/systemd/system/myapp.service
[Unit]
Description=My Application
After=network.target

[Service]
Type=notify
ExecStart=/usr/bin/myapp
# Логи автоматически идут в journald через sd_journal_send
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Шаг 4: Валидация**
```bash
sudo systemctl start myapp
journalctl -u myapp -o verbose -n 5 --no-pager
# → MESSAGE=Request processed
#    REQUEST_ID=req-abc-123
#    _PID=1234
#    _SYSTEMD_UNIT=myapp.service
#    _COMM=myapp
```

### Настройка Python-приложения

**Установка:**
```bash
pip install systemd-python
```

**Конфигурация логирования:**
```python
import logging
import systemd.journal

# Создание handler для journald
journald_handler = systemd.journal.JournaldLogHandler()
journald_handler.set_identifier("myapp")
journald_handler.setFormatter(logging.Formatter('%(message)s'))

# Настройка логгера
logger = logging.getLogger("myapp")
logger.addHandler(journald_handler)
logger.setLevel(logging.INFO)

# Использование с пользовательскими полями
logger.info(
    "User authenticated",
    extra={
        "USER_ID": user_id,
        "SESSION_ID": session_id,
        "AUTH_METHOD": "ssh_key",
    }
)
```

**Валидация:**
```bash
journalctl -t myapp -o verbose -n 1 --no-pager
# → USER_ID=1000
#    SESSION_ID=sess-001
#    AUTH_METHOD=ssh_key
#    MESSAGE=User authenticated
```

### Настройка Go-приложения

**go.mod:**
```
require github.com/coreos/go-systemd/v22 v22.5.0
```

**Код:**
```go
package main

import (
    "github.com/coreos/go-systemd/v22/journal"
)

func logRequest(requestID string, userID int, statusCode int) {
    journal.Send(
        "Request processed",
        journal.PriInfo,
        map[string]string{
            "REQUEST_ID":  requestID,
            "USER_ID":     fmt.Sprintf("%d", userID),
            "STATUS_CODE": fmt.Sprintf("%d", statusCode),
        },
    )
}
```

### Централизованный сбор структурированных логов

Для доставки структурированных логов из journald в Loki/Promtail:

```yaml
# /etc/promtail/config.yml
scrape_configs:
  - job_name: journald
    journal:
      max_age: 1h
      labels:
        job: myapp
    relabel_configs:
      # Маппинг пользовательских полей на labels Loki
      - source_labels: [__journal__REQUEST_ID]
        target_label: request_id
      - source_labels: [__journal__STATUS_CODE]
        target_label: status_code
      - source_labels: [__journal__SYSTEMD_UNIT]
        target_label: systemd_unit
```

**Важно:** Не создавайте labels из высококардинальных полей (REQUEST_ID, SESSION_ID) — это перегрузит индекс Loki. Используйте их как фильтры в LogQL, а не как labels.

### Шаблон systemd-юнита для структурированного логирования

```ini
# /etc/systemd/system/myapp.service
[Unit]
Description=My Structured Logging App
After=network.target

[Service]
Type=notify
ExecStart=/usr/bin/myapp

# Контроль формата логов
StandardOutput=journal
StandardError=journal

# Идентификатор для фильтрации через journalctl -t
SyslogIdentifier=myapp

# Ограничение уровня логирования на уровне systemd
LogLevelMax=info

# Имя пространства имён (systemd 245+)
# LogNamespace=app-logs

Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Дополнительная информация

### Производительность

- **Нативный API** — самый быстрый вариант: отправка через Unix-сокет `@/org/systemd/journal/stdout` с минимальными накладными расходами.
- **logger** — медиатор: отправка через syslog-сокет с дополнительным парсингом.
- **stdout JSON** — высокая производительность, но требует `jq` для парсинга при анализе.
- **Индексы:** Пользовательские поля индексируются journald, что обеспечивает быструю фильтрацию. Однако избыточное количество уникальных значений в пользовательских полях (например, `REQUEST_ID`) может увеличить размер журнала.

### Безопасность

- **Чувствительные данные:** Не записывайте пароли, токены или персональные данные в пользовательские поля — они хранятся в открытом виде в бинарном формате и доступны всем членам групп `systemd-journal`, `adm`, `wheel`.
- **Маскирование:** Для маскирования чувствительных полей используйте фильтрацию на этапе сбора (rsyslog `property replacer`, Promtail `relabel_configs`).
- **FSS (Forward Secure Sealing):** Включите `Seal=yes` в `journald.conf` для защиты от подделки пользовательских полей.

### Ограничения

- **Максимальная длина значения поля:** Определяется параметром `LineMax` в `journald.conf` (по умолчанию 48K). Длинные JSON-строки могут быть обрезаны.
- **Специальные символы:** Значения полей с непечатаемыми символами могут быть повреждены. Используйте base64-кодирование для бинарных данных.
- **Версия systemd:** Нативный API требует `libsystemd` (доступен во всех современных дистрибутивах). Пользовательские поля доступны начиная с systemd 214+.
- **Корреляция через REQUEST_ID:** Требует согласованного именования во всех сервисах. Разнобой в именах полей делает корреляцию невозможной.

### См. также

- [journalctl: Обзор и концепции](./journalctl_overview.md)
- [Практическое использование journalctl](./journalctl_usage.md)
- [Конфигурация journald](../../SystemAdministration/Logging/journald.md)
- [Глубокое погружение в логирование](../../../Concepts/Observability_and_Monitoring/logs_deep_dive.md)
