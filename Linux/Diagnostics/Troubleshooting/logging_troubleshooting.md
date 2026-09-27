# Диагностика и устранение неполадок логирования

## Определения

**Logging Troubleshooting** — процесс выявления и устранения сбоев на всех этапах жизненного цикла логов: генерация (приложение/ядро) → сбор (journald/files) → транспорт (Fluent Bit/Vector) → хранение и индексация (Loki/Elasticsearch).

**Backpressure (Обратное давление)** — ситуация, при которой система хранения не успевает принимать логи, что приводит к переполнению буферов на стороне агента сбора и возможной потере данных.

**High Cardinality (Высокая кардинальность)** — избыточное количество уникальных комбинаций меток (labels), которое перегружает индекс хранилища (характерно для Loki).

---

## Базовые концепции

### Архитектура конвейера логирования

Логи проходят через последовательность компонентов, и сбой на любом этапе приводит к потере данных:

```
Источник (ядро / приложение / container)
    ↓ stdout/stderr или syslog()
Сбор (systemd-journald, rsyslog, файловый драйвер)
    ↓ запись в /run/log/journal, /var/log/*, сокет
Транспорт (Fluent Bit, Vector, Promtail, journald-remote)
    ↓ сжатие, батчинг, ретраи
Хранение и индексация (Loki, Elasticsearch, файловая система)
```

Понимание точки сбоя позволяет сузить круг поиска: если логи есть в `journalctl`, но отсутствуют в Loki — проблема на этапе транспорта или хранилища.

### Типичные точки отказа

| Этап | Симптом | Инструмент проверки |
| :--- | :--- | :--- |
| **Генерация** | Приложение не пишет логи | `docker logs`, `journalctl -u <unit>`, `kubectl logs` |
| **Сбор (journald)** | Логи пропадают после reboot | `journalctl --disk-usage`, проверка `Storage=volatile` |
| **Сбор (rsyslog)** | Дублирование или потеря | `journalctl -u rsyslog`, `lsof +L1` |
| **Транспорт** | Ошибки 429/5xx, backpressure | `journalctl -u fluent-bit`, метрики агента |
| **Хранение** | Запросы возвращают 429 | `loki/api/v1/ready`, `loki/api/v1/limits` |

### Матрица прав доступа

| Ресурс | Требуемые права | Комментарий |
| :--- | :--- | :--- |
| Чтение `/var/log/journal/` | Группа `systemd-journal` или `adm` | По умолчанию доступно root и пользователям групп `systemd-journal`, `adm`, `wheel` |
| Чтение `/var/log/syslog` | Группа `adm` | На Debian/Ubuntu файлы принадлежат `syslog:adm` |
| Чтение `/var/log/secure` | Группа `adm` | На RHEL/CentOS файлы принадлежат `root:adm` |
| Управление journald | root | `journalctl --rotate`, `--vacuum-*` |
| Управление logrotate | root | Запуск через cron/systemd-timer |
| Перезапуск rsyslog | root | `systemctl restart rsyslog` |

### Ключевые конфигурационные файлы

| Файл | Компонент | Назначение |
| :--- | :--- | :--- |
| `/etc/systemd/journald.conf` | journald | Лимиты хранения, rate limiting, пересылка в syslog |
| `/etc/rsyslog.conf` | rsyslog | Глобальные правила фильтрации и пересылки |
| `/etc/rsyslog.d/*.conf` | rsyslog | Дополнительные правила (загружаются в алфавитном порядке) |
| `/etc/logrotate.conf` | logrotate | Глобальные параметры ротации |
| `/etc/logrotate.d/*` | logrotate | Правила ротации для конкретных сервисов |
| `/etc/fluent-bit/fluent-bit.conf` | Fluent Bit | Параметры ввода, парсинга и вывода |
| `/etc/loki/local-config.yaml` | Loki | Лимиты приема, хранилище, схемы |

---

## Практические сценарии

### 1. Отсутствуют логи за временной интервал

**Симптомы:** В интерфейсе Grafana/Kibana «дыры» в данных, хотя сервис работал без сбоев.

**Диагностика:**
1. **Проверка локального журнала (journald):**
   ```bash
   journalctl --verify
   # → PASS: ...
   # → FAIL: /var/log/journal/.../system.journal: Corrupted (Требуется очистка)
   ```
2. **Поиск сообщений о подавлении (Rate Limiting):**
   ```bash
   journalctl -u systemd-journald | grep "Suppressed"
   # → systemd-journald: Suppressed 1000 messages from /user.slice/...
   ```
   *Решение:* Увеличьте `RateLimitIntervalSec` и `RateLimitBurst` в `/etc/systemd/journald.conf`.
3. **Проверка синхронизации времени (NTP):**
   Если время на сервере «уплыло», логи могут записываться в прошлое или будущее.
   ```bash
   timedatectl status | grep "System clock synchronized"
   # → System clock synchronized: yes
   ```

---

### 2. Переполнение диска (/var/log)

**Симптомы:** Ошибка «No space left on device», невозможность старта сервисов.

**Диагностика:**
1. **Анализ дискового пространства:**
   ```bash
   df -h /var/log
   # → Filesystem      Size  Used Avail Use% Mounted on
   # → /dev/sda1        20G   19G     0 100% /
   ```
2. **Поиск «виновников»:**
   ```bash
   sudo du -sh /var/log/* | sort -rh | head -n 5
   # → 12G   /var/log/journal
   # → 4.5G  /var/log/nginx
   ```

**Решение:**
- **Очистка journald:** `sudo journalctl --vacuum-size=1G`.
- **Проверка logrotate:** Убедитесь, что конфигурация корректна: `sudo logrotate -d /etc/logrotate.conf` (Dry run).
- **Deleted-but-open файлы:** Если файл удален, но место не освободилось:
   ```bash
   sudo lsof +L1 | grep deleted
   # → nginx  1234  root  5w  REG  8,1  4500000  (deleted) /var/log/nginx/access.log
   ```
   *Решение:* Перезапустите процесс (например, `systemctl reload nginx`).

---

### 3. Сбои удаленной доставки (Fluent Bit → Loki)

**Симптомы:** Логи есть в `journalctl`, но не доходят до центрального хранилища.

**Диагностика:**
1. **Проверка здоровья бэкенда:**
   ```bash
   curl -I http://loki.internal:3100/ready
   # → HTTP/1.1 200 OK
   ```
2. **Анализ ошибок агента:**
   ```bash
   journalctl -u fluent-bit -n 50 --no-pager
   # → [error] [output:loki:loki.0] http_status=429 (Too Many Requests)
   # → [warn] [input:tail:0] memory limit reached, pausing...
   ```
   *Интерпретация:* 429 ошибка означает срабатывание лимитов Loki (Ingestion Rate). Пауза `memory limit` указывает на Backpressure.

3. **База позиций (Tail DB):**
   Если Fluent Bit «застрял» на одном месте, возможно повреждена SQLite база:
   ```bash
   file /var/log/fluent-bit-positions.db
   # → /var/log/fluent-bit-positions.db: SQLite 3.x database
   ```
   *Решение:* При повреждении удалите файл и перезапустите агент (он начнет чтение заново).

---

### 4. Проблемы с метаданными и High Cardinality

**Симптомы:** Поиск в Loki работает крайне медленно или выдает ошибку «Limit exceeded».

**Причина:** Использование динамических данных (UUID, Timestamp, IP) в качестве меток (Labels).

**Диагностика:**
1. Проверьте список меток:
   ```bash
   curl -s http://loki:3100/loki/api/v1/labels | jq
   ```
2. Если среди меток есть `user_id` или `request_id` — это архитектурная ошибка.
   *Решение:* Перенесите динамические данные из Labels в тело лога (Structured Metadata или просто JSON).

---

### 5. Отсутствие прав на чтение логов

**Симптомы:** `journalctl` или `cat /var/log/syslog` возвращают «Permission denied», хотя сервис работает.

**Диагностика:**
1. **Проверка членства в группах:**
   ```bash
   id -nG
   # → username adm systemd-journal wheel
   ```
2. **Проверка прав на директории:**
   ```bash
   stat -c '%a %U:%G' /var/log/journal /var/log/syslog /var/log/secure
   # → 2755 root:systemd-journal  640 root:adm  640 root:adm
   ```

**Решение:**
- Добавить пользователя в нужную группу: `sudo usermod -aG adm $USER`.
- Для `journalctl` — группа `systemd-journal` (Debian/Ubuntu) или `wheel` (RHEL).
- После изменения групп требуется перелогиниться или `newgrp adm`.

---

### 6. Дублирование логов (journald + rsyslog + файл приложения)

**Симптомы:** В `journalctl` и `/var/log/syslog` присутствуют одинаковые записи, объем логов вырастает в 2–3 раза.

**Причина:** Действует пересылка из journald в rsyslog (`ForwardToSyslog=yes`), и приложение пишет параллельно в файл и stdout.

**Диагностика:**
1. **Проверка конфигурации journald:**
   ```bash
   systemd-analyze cat-config systemd/journald.conf | grep -i ForwardToSyslog
   # → ForwardToSyslog=yes
   ```
2. **Поиск дублирующих источников:**
   ```bash
   journalctl -u nginx --since "1 minute ago" | wc -l
   cat /var/log/nginx/access.log | wc -l
   ```

**Решение:**
- Если используется rsyslog — установите `ForwardToSyslog=no` в `journald.conf` и перезапустите `systemd-journald`.
- Для контейнеров с драйвером `journald` убедитесь, что приложение не пишет в файл внутри контейнера параллельно.

---

### 7. Ошибки парсинга и некорректный формат логов

**Симптомы:** Loki/Elasticsearch не индексирует логи, в интерфейсе пустые строки или ошибки парсинга.

**Диагностика:**
1. **Проверка сырого лога:**
   ```bash
   tail -n 5 /var/log/app/app.log
   # → 2026-01-01 12:00:00 {"level":"info", "message":"..."
   ```
2. **Поиск неэкранированных символов:**
   ```bash
   grep -Pn '\x0[^0]' /var/log/app/app.log | head -n 5
   ```
   *Интерпретация:* Нулевые байты (`\0`) или невалидные UTF-8 последовательности ломают парсеры.

**Решение:**
- В конфигурации агента добавьте обработку ошибок парсинга: `skip_invalid true` (Fluent Bit) или `allow_duplicate_fields true`.
- На стороне приложения используйте библиотеки structured logging (JSON с экранированием).
- Для rsyslog используйте модуль `mmjsonparse` с отключенной строгой валидацией.

---

### 8. Журналирование ядра и потеря сообщений kmsg

**Симптомы:** В `/var/log/kern.log` и `journalctl -k` нет сообщений, хотя `dmesg` их показывает.

**Причина:** `imklog` отключен в rsyslog или rate limit journald подавил сообщения ядра.

**Диагностика:**
1. **Проверка rate limit journald:**
   ```bash
   journalctl -u systemd-journald | grep -i "suppressed"
   # → systemd-journald: Suppressed 500 messages from kernel
   ```
2. **Проверка imklog:**
   ```bash
   sudo rsyslogd -N1 | grep -i klog
   # →Warning: imklog not enabled
   ```

**Решение:**
- Для journald: увеличьте `RateLimitBurst` и `RateLimitIntervalSec` в `journald.conf`.
- Для rsyslog: добавьте в конфигурацию `module(load="imklog")` и перезапустите службу.

---

### 9. Отсутствие логов от пользовательских сервисов (User Units)

**Симптомы:** `journalctl -u myapp.service` возвращает пустой результат для сервиса, запущенного от пользователя.

**Причина:** Логи пользовательских юнитов хранятся в отдельном пространстве имен и требуют `linger` или явного указания пользователя.

**Диагностика:**
1. **Проверка статуса linger:**
   ```bash
   loginctl show-user appuser -p Linger
   # → Linger=no
   ```
2. **Чтение логов пользовательского юнита:**
   ```bash
   journalctl --user -u myapp.service
   ```

**Решение:**
- Включите linger: `sudo loginctl enable-linger appuser`.
- Или читайте логи через `journalctl --user -u myapp.service -b`.

---

### 10. Повреждение журнала после сбоя питания

**Симптомы:** `journalctl --verify` возвращает ошибки, логи обрываются на моменте сбоя.

**Диагностика:**
1. **Проверка целостности:**
   ```bash
   sudo journalctl --verify
   # → PASS: /var/log/journal/.../system.journal
   # → FAIL: /var/log/journal/.../system@abc123.journal: Corrupted
   ```
2. **Проверка размера файлов:**
   ```bash
   ls -lh /var/log/journal/*/*.journal*
   ```

**Решение:**
- Выполните ротацию перед очисткой: `sudo journalctl --rotate`.
- Удалите поврежденные архивы: `sudo journalctl --vacuum-time=1s`.
- Если проблема повторяется — проверьте файловую систему (`fsck`) и источник питания.

---

## Дополнительная информация

### Типичные проблемы и решения

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Логи пропадают после перезагрузки** | Режим `Storage=volatile` | Создать директорию `/var/log/journal` или установить `Storage=persistent`. |
| **Журнал переполняет диск** | Не настроены лимиты ротации | Настроить `SystemMaxUse` и `MaxRetentionSec` в `journald.conf`. |
| **Дублирование логов** | Активна пересылка из journald в rsyslog | Установить `ForwardToSyslog=no` в `/etc/systemd/journald.conf` |
| **Потеря логов по UDP** | Переполнение буфера ядра | Увеличить `net.core.rmem_max` через sysctl |
| **Высокая нагрузка на CPU** | Интенсивный поток логов (флуд) | Настроить `RateLimitIntervalSec`/`RateLimitBurst` или `MaxLevelStore` |
| **Ошибка "Suppressed X messages"** | Срабатывает Rate Limit | Увеличить `RateLimitBurst` и `RateLimitIntervalSec` в `journald.conf` |
| **Файлы не ротируются** | Ошибка в `logrotate` | Убедиться, что `logrotate` посылает `SIGHUP` в сервис; проверить права |
| **Повреждение файлов журнала** | Внезапное отключение питания | Проверка: `journalctl --verify`. Битые файлы следует переместить из `/var/log/journal/` |
| **Нет логов пользовательских сервисов** | `Linger=no` | `loginctl enable-linger <username>` |
| **Потеря логов при переполнении** | Backpressure от хранилища | Увеличить буфер на агенте (disk buffer), настроить ретраи, масштабировать хранилище |
| **Пустой лог после vacuum** | Активный файл не был ротирован | Выполнить `journalctl --rotate` перед `--vacuum` |
| **Логи не записываются (rsyslog)** | Ошибки прав доступа | `chown syslog:adm /var/log/*.log` (на Debian/Ubuntu) |
| **Логи не записываются (приложение)** | Приложение пишет в файл, но не в stdout | Настроить драйвер логирования на `stdout` в формате JSON |

### Чек-лист быстрой проверки
1.  **journald:** статус, лимиты, целостность (`systemctl status systemd-journald`, `journalctl --disk-usage`, `journalctl --verify`).
2.  **Время:** корректность NTP (`timedatectl status`).
3.  **Диск:** свободное место и `deleted` дескрипторы (`df -h /var/log`, `lsof +L1 | grep deleted`).
4.  **rsyslog:** статус и пересылка (`systemctl status rsyslog`, `rsyslogd -N1`).
5.  **logrotate:** последний запуск (`cat /var/lib/logrotate/status`).
6.  **Агент:** логи ошибок (429, 5xx), сетевая доступность (`journalctl -u fluent-bit`, `curl http://loki:3100/ready`).
7.  **Бэкенд:** лимиты на прием данных (`curl http://loki:3100/loki/api/v1/limits`).

### Рекомендации

1.  **Постоянное хранение journald:** На production-серверах всегда используйте `Storage=persistent`. Создайте `/var/log/journal` и настройте `SystemMaxUse=1-2G`.
2.  **Rate Limiting:** Настраивайте `RateLimitIntervalSec` и `RateLimitBurst` в `journald.conf` на значения, превышающие типичный пик нагрузки в 2–3 раза.
3.  **Структурированные логи:** Приложения должны писать в `stdout/stderr` в формате JSON. Это устраняет необходимость в сложных парсерах на стороне сбора.
4.  **Централизация:** Локальные логи — для оперативного диагностирования, центральный стек (Loki/ELK) — для долгосрочного хранения и корреляции.
5.  **Мониторинг объема:** Настройте алертинг на рост `/var/log/journal` и ошибки `429` у агентов сбора.
6.  **Ротация:** Предпочитайте встроенные механизмы ротации (`journald`, `logrotate` с `postrotate`) методу `copytruncate` из-за риска потери данных.
7.  **Безопасность:** Настройте `ForwardToSyslog=no`, если не требуется дублирование в rsyslog. Используйте FSS на критичных серверах для детекции подделки логов.
8.  **Тестирование:** Перед применением конфигурации rsyslog всегда выполняйте `sudo rsyslogd -N1`. Перед изменением правил logrotate используйте `sudo logrotate -d`.

### Очистка

После диагностики удалите временные артефакты:

1.  **Тестовые сообщения:**
    ```bash
    # Поиск тестовых сообщений
    journalctl -t test_tag --since "1 hour ago"
    # Очистка (если требуется)
    sudo journalctl --vacuum-time=1h
    ```
2.  **Временные файлы агентов:**
    ```bash
    # Проверка временных баз Fluent Bit
    ls -la /var/log/fluent-bit-positions.db*
    # Удаление при необходимости
    sudo rm -f /var/log/fluent-bit-positions.db
    ```
3.  **Архивы journald после vacuum:**
    ```bash
    # Проверка количества архивных файлов
    ls /var/log/journal/*/*.journal~ | wc -l
    ```
4.  **Восстановление стандартных лимитов journald:**
    ```bash
    sudo systemctl edit systemd-journald
    # Удалите временные overrides, если создавали
    sudo systemctl daemon-reload
    sudo systemctl restart systemd-journald
    ```
5.  **Откат изменений logrotate:**
    ```bash
    # Удалите кастомные конфиги из /etc/logrotate.d/
    sudo rm /etc/logrotate.d/test_app
    # Проверка глобальной конфигурации
    sudo logrotate -d /etc/logrotate.conf
    ```

### См. также
- [**Обзор логирования в Linux**](../../SystemAdministration/Logging/logging_overview.md)
- [**systemd-journald: Сбор и хранение**](../../SystemAdministration/Logging/journald.md)
- [**rsyslog: Фильтрация и пересылка**](../../SystemAdministration/Logging/rsyslog.md)
