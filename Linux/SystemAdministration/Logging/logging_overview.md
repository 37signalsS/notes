# Обзор системы логирования в Linux

## Определения

**Системные журналы (логи)** — структурированные или текстовые файлы и базы данных, в которые записываются системные сообщения, ошибки и события аудита. Анализ логов — ключевой навык для диагностики проблем, отслеживания производительности и расследования инцидентов безопасности.

**Архитектура логирования в современных Linux:**

| Компонент | Назначение | Основной документ |
| :--- | :--- | :--- |
| `systemd-journald` | **Ядро современного логирования.** Централизованный сбор логов в бинарном формате от всех компонентов системы. | [journald](./journald.md) |
| `journalctl` | Утилита командной строки для просмотра, фильтрации и анализа логов `journald`. | [journalctl](../../Diagnostics/journalctl/journalctl_overview.md) |
| `rsyslog` | Традиционный демон для фильтрации, текстовой обработки и пересылки логов по сети. | [rsyslog](./rsyslog.md) |
| `auditd` | Отдельная подсистема для строгого аудита событий безопасности на уровне ядра. | [auditd](./auditd.md) |
| `logrotate` | Автоматизация ротации, сжатия и удаления старых текстовых логов. | [logrotate](./logrotate.md) |

**Схема взаимодействия:** Ядро и службы отправляют данные в `journald`. Если установлен `rsyslog`, он забирает поток из `journald` для создания текстовых файлов в `/var/log/`. `logrotate` периодически сжимает и очищает эти текстовые файлы.

## Базовые концепции

### Иерархия логирования Linux

Система логирования в Linux представляет собой многоуровневую структуру (Observability Stack):

1.  **Центральная платформа:** Loki, Elasticsearch (ELK), ClickHouse, AWS CloudWatch.
2.  **Агрегаторы и шипперы (Telemetry Agents):** Vector (Rust), Grafana Alloy, Fluent Bit, Fluentd.
3.  **Слой Syslog:** rsyslog, syslog-ng.
4.  **Службы сбора:** systemd-journald, прямая запись в `/var/log`.
5.  **Источники:** Ядро (`/dev/kmsg`), stdout/stderr процессов, eBPF-пробы (Falco, Tetragon), приложения (`syslog()`).

### Протокол syslog (RFC 5424)

Протокол определяет **facility** (кто логирует: kern, auth, daemon, user и т.д.) и **severity** (уровень важности).

**Уровни серьёзности (Severity):**
- **emerg (0)** — система неработоспособна (panic).
- **alert (1)** — требуется немедленное действие.
- **crit (2)** — критические состояния (сбои оборудования).
- **err (3)** — ошибки выполнения.
- **warning (4)** — предупреждения.
- **notice (5)** — важные события при нормальной работе.
- **info (6)** — информационные сообщения.
- **debug (7)** — отладочные сообщения.

### Расположение логов в Linux

В системах на базе `systemd` логи находятся в двух основных хранилищах: бинарном (управляется journald) и текстовом (управляется rsyslog/приложениями).

| Расположение | Описание |
| :--- | :--- |
| `/var/log/journal/` | Постоянные (persistent) бинарные журналы `systemd-journald`. |
| `/run/log/journal/` | Временные (volatile) журналы в RAM — очищаются при перезагрузке. |
| `/var/log/syslog` | Главный системный лог (на Debian/Ubuntu). |
| `/var/log/messages` | Главный системный лог (на RHEL/CentOS). |
| `/var/log/auth.log` | События аутентификации (SSH, sudo, PAM) на Debian/Ubuntu. |
| `/var/log/secure` | События аутентификации на RHEL/CentOS. |
| `/var/log/kern.log` | Сообщения ядра (дублируются из dmesg). |
| `/var/log/audit/audit.log` | Журнал аудита безопасности (`auditd`). |
| `/var/log/nginx/` | Логи конкретных приложений (пишут самостоятельно). |
| `/var/log/wtmp` | История входов в систему (двоичный, читается через `last`). |

### Форматы журналов

| Формат | Где используется | Особенности |
| :--- | :--- | :--- |
| **Бинарный** | `systemd-journald` | Высокая скорость поиска, защита FSS, богатые метаданные. |
| **Syslog (RFC 5424)** | `rsyslog`, legacy | Текстовый стандарт, требует регулярных выражений для парсинга. |
| **JSON** | Cloud-Native, Docker | Идеален для SIEM и автоматизации, не требует сложных парсеров. |
| **Plain text** | Традиционные приложения | Читаем человеком, сложен для машинного анализа. |

> **Best Practice:** Для современных систем настраивайте вывод приложений в `stdout/stderr` в формате **JSON**. Это позволяет коллекторам (Vector, Fluent Bit) собирать логи как структурированные данные без потери контекста.

### Инструменты для просмотра логов

| Инструмент | Назначение | Документация |
| :--- | :--- | :--- |
| **`journalctl`** | Основной инструмент. Просмотр бинарных логов с мощной фильтрацией. | [journalctl](../../Diagnostics/journalctl/journalctl_overview.md) |
| **`dmesg`** | Чтение кольцевого буфера ядра. Критично для диагностики железа. | [dmesg](../../Diagnostics/Kernel/dmesg/index.md) |
| **`tail -f` / `less`** | Просмотр текстовых файлов в реальном времени. | `less`, `tail` |
| **`grep` / `zgrep`** | Поиск по паттернам, включая сжатые архивы. | [grep](../../Shell/grep.md) |
| **`ausearch`** | Фильтрация событий аудита ядра. | [auditd](./auditd.md) |

### Категории журналов безопасности

#### Анализ журналов входа (wtmp/utmp/btmp)

| Команда | Источник | Назначение | Пример вывода |
| :--- | :--- | :--- | :--- |
| `last` | `/var/log/wtmp` | История успешных входов и перезагрузок | `user pts/0 192.168.1.10 Mon Jan 01 10:00 still logged in` |
| `lastb` | `/var/log/btmp` | История **неудачных** попыток (требует root) | `user ssh:notty 192.168.1.11 Mon Jan 01 11:00 - 11:00 (00:00)` |
| `who` / `w` | `/var/run/utmp` | Кто сейчас в системе и чем занят | `user pts/0 2026-01-01 10:00 (192.168.1.10)` |
| `lastlog` | `/var/log/lastlog`| Время последнего входа каждого пользователя | `root pts/0 192.168.1.10 Mon Jan 01 10:00:00 +0000 2026` |

**Примеры анализа событий аутентификации:**
```bash
# Поиск успешных входов по SSH через journalctl
journalctl -u ssh -g "Accepted"

# Поиск неудачных попыток sudo в классических логах
grep sudo /var/log/auth.log | grep failed
```

## Практические сценарии

### Отправка тестовых сообщений: `logger`
```bash
# Базовое сообщение
logger "Тестовое сообщение"

# С указанием facility и priority
logger -t myscript -p local0.info "Скрипт выполнен успешно"

# На удаленный сервер
logger -n 192.168.1.100 -p local0.info "Удаленное сообщение"
```

### Методология диагностики (Алгоритм действий)

Диагностика в современных системах всегда начинается с инструментов `systemd`.

| Категория проблемы | Рекомендуемый порядок действий |
| :--- | :--- |
| **Служба не запускается** | 1. `systemctl status <name>`<br>2. `journalctl -u <name> -b` (за текущую сессию) |
| **Отказ в доступе (SSH/Sudo)** | 1. `journalctl -t sshd` или `journalctl -t sudo`<br>2. `grep failed /var/log/auth.log`<br>3. `ausearch -m USER_LOGIN` |
| **Сбои ядра или драйверов** | 1. `dmesg -T --level=err,warn`<br>2. `journalctl -k -b` |
| **Закончилось место на диске** | 1. `journalctl --disk-usage`<br>2. `journalctl --vacuum-size=500M`<br>3. Проверка `logrotate` |

## Дополнительная информация

### Принудительная синхронизация: `sync`
```bash
sync  # Запись буферов из RAM на диск
```
Полезна перед жестким выключением или при подозрении на Kernel Panic, чтобы гарантировать запись последних логов.

### Архитектура pipeline: Decision Tree

```
Малый масштаб (<10 хостов)
├─ journald + rsyslog → текстовые файлы + logrotate
├─ Агент: Promtail/Fluent Bit → Loki (или без агента, просто grep)
└─ Визуализация: journalctl + Grafana

Средний масштаб (10–100 хостов)
├─ Агент на каждом хосте: Vector / Fluent Bit
├─ Транспорт: TCP/TLS или Kafka (при高峰流量)
├─ Бэкенд: Loki (min RAM) или Elasticsearch (полнотекстовый поиск)
├─ Буферизация: disk buffer на агенте
└─ Визуализация: Grafana / Kibana

Большой масштаб (100+ хостов)
├─ Агент: Vector с VRL-трансформациями
├─ Брокер: Kafka (очередь, буфер, повторная отправка)
├─ Бэкенд: кластер Elasticsearch (3+ мастера) или Loki (distributed mode)
├─ Retention: Hot-Warm-Cold (SSD → HDD → S3)
├─ Security: TLS mTLS, RBAC, PII-маскирование
└─ Мониторинг pipeline: Prometheus + Grafana (метрики агента и бэкенда)
```

| Фактор | Выбор решения |
|:---|:---|
| Бюджет ограничен | Loki + Promtail (минимум RAM, open-source) |
| Нужен полнотекстовый поиск | Elasticsearch |
| Нужна корреляция с метриками | Loki (интеграция с Prometheus в Grafana) |
| K8s-кластер | Fluent Bit DaemonSet + Loki |
| Compliance (PCI DSS, GDPR) | Elasticsearch (ILM) или Loki + WORM-хранилище |
| Высокая скорость ingestion (>100K eps) | Kafka как брокер между агентами и бэкендом |

### Log Spikes и аномалии

**Log Spike** — резкий рост объема логов за короткий период. Типичные причины:

| Причина | Пример | Решение |
|:---|:---|:---|
| **Debug-логи в production** | Включили debug для отладки, забыли выключить | Алерт на рост > 2x, автоматическое отключение через таймаут |
| **Retry storm** | Сервис без backoff заваливает логами при недоступности БД | Circuit breaker, exponential backoff |
| **Баг в коде** | бесконечный цикл с логированием | Алерт на количество логов от одного сервиса > порог |
| **DDoS / сканирование** | 10K failed login attempts в минуту | rate limiting на уровне агента, алерт на аномалии |
| **Deployment** | Новый релиз генерирует x10 логов | canary deployment с мониторингом объема логов |

**Мониторинг log spikes (Prometheus):**

```yaml
groups:
  - name: log_spikes
    rules:
      - alert: LogVolumeSpike
        expr: |
          sum by (service) (rate(journald_messages_total[5m]))
          > 2 * avg_over_time(sum by (service) (rate(journald_messages_total[5m]))[7d:5m])
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Log spike на {{ $labels.service }}"

      - alert: LogVolumeCritical
        expr: |
          sum(rate(journald_messages_total[5m])) > 10000
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Критический объем логов: >10K msgs/sec"
```

**Автоматическое ограничение (Vector):**

```yaml
transforms:
  rate_limit:
    type: throttle
    inputs: [app_logs]
    threshold: 5000
    window_secs: 60
    exclude:
      - 'level == "error"'
      - 'level == "critical"'
```

### Современные тенденции (2025–2026)

- **eBPF (Falco, Tetragon):** Глубокий мониторинг безопасности без накладных расходов `auditd`.
- **Универсальные агенты (Vector, Alloy):** Единый инструмент для логов, метрик и трейсов.
- **VPC Flow Logs:** Сбор сетевой телеметрии на уровне облачной инфраструктуры.

## Лучшие практики (Best Practices)

1.  **Централизация:** Локальные логи — для разработки, центральный стек (Loki/ELK) — для Production.
2.  **Структурированное логирование (JSON):** Стандарт для упрощения поиска и корреляции.
3.  **Маскирование секретов:** PAN-номера, пароли и API-ключи должны удаляться на этапе сбора (в агенте).
4.  **Согласованные метаданные:** Обязательно наличие `hostname`, `service_name`, `env` и `trace_id`.
5.  **Разделение логов безопасности:** Логи аудита и аутентификации должны храниться отдельно и дольше.
6.  **Мониторинг объема:** Резкий всплеск логов (Log Spikes) — повод для автоматического алерта.

### См. также

- [systemd-journald: Сбор и хранение](./journald.md)
- [journalctl: Обзор и концепции](../../Diagnostics/journalctl/journalctl_overview.md)
- [rsyslog: Фильтрация и пересылка](./rsyslog.md)
- [syslog-ng: Продвинутая маршрутизация](./syslog-ng.md)
- [auditd: Аудит событий безопасности](./auditd.md)
- [logrotate: Ротация и сжатие](./logrotate.md)
- [Fluent Bit: Агент сбора логов](./fluent_bit.md)
- [Структурированное логирование](./structured_logging.md)
- [PII/Secret masking](./pii_masking.md)
- [Логирование cron-задач и скриптов](./cron_script_logging.md)
- [Debug-логи в production](./debug_logging_production.md)
- [Мониторинг dmesg](./dmesg_monitoring.md)
- [Анализ ошибок и сбоев](./error_and_crash_analysis.md)
- [Централизованное логирование](./cloud_logging.md)
- [Vector: современная альтернатива](../../../Vector/vector_overview.md)
