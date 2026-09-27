# systemd-journald: Централизованный сбор логов

## Определения

* **`systemd-journald`** — системная служба, централизованно собирающая логи от всех компонентов ОС (Операционная Система): ядро, службы, приложения, stdout/stderr (стандартный вывод / стандартный вывод ошибок) в структурированном бинарном формате.
* **`journalctl`** — утилита командной строки для просмотра и анализа логов, собранных `systemd-journald`. **Подробное описание утилиты `journalctl` находится в [journalctl_overview.md](../../Diagnostics/journalctl/journalctl_overview.md).**

## Базовые концепции

### Архитектура и принцип работы

`systemd-journald` работает как демон, управляемый системой инициализации systemd. Он является первым пользовательским процессом, запускаемым ядром (PID 1 или ранний пользовательский space), и начинает собирать логи с самых ранних этапов загрузки.

**Источники логов:**

1. **Ядро (`/dev/kmsg`):** journald перехватывает кольцевой буфер ядра (`printk`), обеспечивая сбор сообщений `dmesg` в единый поток.
2. **Службы systemd:** Приложения, управляемые systemd, отправляют логи через Unix-сокеты. journald получает не только текст сообщения, но и метаданные: PID, UID, GID, имя исполняемого файла, cgroup.
3. **stdout/stderr:** Любой сервис, у которого в unit-файле не указано `StandardOutput=null` / `StandardError=null`, автоматически направляет свой вывод в journald.
4. **Сокет `/dev/log`:** Для совместимости с традиционными syslog-приложениями, которые используют `syslog()` или пишут в `/dev/log`.
5. **Подсистема аудита:** journald может получать события от Linux Audit (`auditd`) через netlink.

**Структурированное хранение:**

Каждое сообщение — набор пар `ключ=значение`. Это отличается от текстовых логов (например, `/var/log/syslog`), где каждая строка — неструктурированный текст.

- **Автоматические метаданные:** Ядро и systemd заполняют системные поля (`_PID`, `_UID`, `_COMM`, `_EXE`, `_SYSTEMD_UNIT`, `_BOOT_ID`, `_MACHINE_ID`, `_TRANSPORT`). Это предотвращает подмену отправителя, так как эти данные поступают из доверенных источников.
- **Индексация:** Все поля индексируются, что обеспечивает мгновенный поиск по времени, идентификаторам и любым метаданным без полного сканирования файлов.
- **Structured logging:** Приложения могут отправлять поля `MESSAGE_ID` (128-битный UUID типа сообщения) и пользовательские поля, что облегчает корреляцию и автоматический парсинг.

**Бинарный формат и жизненный цикл записи:**

journald использует структурированный двоичный формат с расширением `.journal`. Файлы хранятся в:

- `/run/log/journal/<machine-id>/` — энергозависимое хранилище (tmpfs, RAM)
- `/var/log/journal/<machine-id>/` — постоянное хранилище (диск)

**Жизненный цикл журнала:**
1. **Сбор (Collection):** Сообщение поступает через один из каналов.
2. **Индексация:** Добавляются системные поля, создаются индексы.
3. **Запись:** Данные записываются в текущий активный файл через `mmap()`.
4. **Ротация:** При достижении лимитов (`SystemMaxUse`, `MaxFileSec`) активный файл закрывается, становится архивным (получает суффикс `@<hash>.journal`), создается новый активный файл.
5. **Очистка (Vacuum):** Архивные файлы удаляются по критериям размера, времени или количества.

**Защита от подделки:** Бинарные файлы сложнее модифицировать незаметно, чем текстовые. Поддерживается криптографическое подписание (Forward Secure Sealing, FSS), которое позволяет обнаружить любые изменения после подписи.

### Пространства имён (Journal Namespaces)

В современных версиях (systemd 245+) поддерживаются пространства имён журнала. Это позволяет запускать независимые экземпляры `systemd-journald@<namespace>.service` для изоляции логов конкретных приложений или контейнеров от системного журнала.

* Изолированный демон имеет собственные настройки в `/etc/systemd/journald@<namespace>.conf`.
* Логи хранятся в `/var/log/journal/<machine-id>.<namespace>/`.
* Привязка сервиса к пространству имён выполняется через директиву `LogNamespace=` в его юнит-файле.

**Практическое применение:**
- Изоляция логов контейнеров (Podman, Docker) от системного журнала.
- Отдельные журналы для критичных приложений (базы данных, платежные системы).
- Многопользовательские окружения с требованием разделения логов.

### Поля журнала

Каждое сообщение в журнале содержит стандартные метаданные:

| Поле | Описание |
| :--- | :--- |
| `MESSAGE` | Текст сообщения |
| `PRIORITY` | Уровень приоритета (0–7, см. уровни приоритета syslog) |
| `_PID` | PID (Process ID) отправителя |
| `_UID` | UID (User ID) пользователя, от имени которого запущен процесс |
| `_COMM` | Имя исполняемого файла (короткое) |
| `_EXE` | Полный путь к исполняемому файлу |
| `_SYSTEMD_UNIT` | Имя systemd-юнита (сервиса) |
| `_HOSTNAME` | Имя хоста |
| `_MACHINE_ID` | UUID машины |
| `_BOOT_ID` | UUID текущей загрузки |
| `_TRANSPORT` | Метод доставки лога (`driver`, `syslog`, `journal`, `stdout`, `kernel`) |
| `CODE_FILE`, `CODE_LINE` | Позиция в исходном коде (если доступно) |
| `MESSAGE_ID` | Уникальный идентификатор типа сообщения (128-битный UUID) |

Полный список доступных полей: `journalctl --fields`.

### Уровни приоритета (RFC 5424)

| Код | Уровень | Описание |
| :--- | :--- | :--- |
| 0 | `emerg` | Система неработоспособна (panic) |
| 1 | `alert` | Требуется немедленное действие |
| 2 | `crit` | Критические условия |
| 3 | `err` | Ошибки |
| 4 | `warning` | Предупреждения |
| 5 | `notice` | Нормальные, но значимые события |
| 6 | `info` | Информационные сообщения |
| 7 | `debug` | Отладочные сообщения |

### SplitMode

Параметр `SplitMode` в `journald.conf` определяет стратегию распределения логов между файлами:

- **`SplitMode=uid`** (по умолчанию в большинстве дистрибутивов): создает отдельные файлы для каждого пользователя (`user-<UID>.journal`). Это обеспечивает изоляцию, но может привести к большому количеству мелких файлов.
- **`SplitMode=machine`**: все логи пишутся в единый системный файл `system.journal`. Подходит для систем с большим количеством пользователей, где важна простота управления.
- **`SplitMode=none`**: аналогично `machine`, но без разделения на системный и пользовательские файлы.

**Влияние на хранение:**
- При `SplitMode=uid` команда `journalctl --disk-usage` показывает суммарный размер по всем файлам, включая пользовательские.
- Ротация и вакуум затрагивают все файлы независимо от режима.
- Для production-серверов с множеством сервисов рекомендуется `SplitMode=machine` для упрощения мониторинга.

### Rate Limiting

journald имеет встроенный механизм защиты от флуда (дублирующихся сообщений), который активируется при превышении порога `RateLimitBurst` за интервал `RateLimitIntervalSec`.

**Как работает:**
- При превышении лимита journald подавляет дублирующиеся сообщения и записывает в лог статистику: `Suppressed X messages from /...`.
- Это предотвращает переполнение хранилища при циклических ошибках или атаках типа DoS.

**Конфигурация в `journald.conf`:**
```ini
[Journal]
# Окно для подсчета burst (по умолчанию 5s)
RateLimitIntervalSec=5s
# Максимальное количество сообщений в окне (по умолчанию 10000)
RateLimitBurst=10000
```

**Когда увеличивать лимиты:**
- На production-серверах с высоким трафиком (веб-серверы, API) установите `RateLimitBurst=50000` и `RateLimitIntervalSec=10s`.
- Для отладочных сред можно временно отключить rate limiting: `RateLimitIntervalSec=0`.

**Диагностика подавленных сообщений:**
```bash
# Проверить, есть ли подавленные сообщения
journalctl -u systemd-journald | grep -i "suppressed"
# → systemd-journald: Suppressed 1000 messages from /user.slice/...
```

### Хранение логов

1. **Энергозависимое (Volatile):** По умолчанию логи хранятся в `/run/log/journal`. Директория монтируется как `tmpfs` (временная файловая система в оперативной памяти) и очищается при перезагрузке.
2. **Постоянное (Persistent):** При наличии директории `/var/log/journal`, демон автоматически переходит в режим постоянного хранения.

**Организация файлов на диске:**
- Файлы размещаются в подкаталогах по `Machine ID`: `/var/log/journal/<machine-id>/`.
- Имена файлов: `system.journal` (системные логи), `user-<UID>.journal` (пользовательские), `system@<hash>.journal` (архивные сессии).
- journald автоматически определяет режим хранения при загрузке: если существует `/var/log/journal`, используется постоянное хранилище.

**Проверка режима хранения:**

```bash
# Проверить текущий режим
ls -la /var/log/journal/ 2>/dev/null && echo "Persistent" || echo "Volatile"
# → Persistent

# Проверить размер журнала
journalctl --disk-usage
# → Archived and active journals take up 512.0M in the file system.
```

## Практические сценарии

### Настройка постоянного хранения

Для сохранения логов после перезагрузки:

```bash
# 1. Создание директории для постоянного хранения
sudo mkdir -p /var/log/journal

# 2. Установка прав (группа systemd-journal)
sudo chown root:systemd-journal /var/log/journal
sudo chmod 2755 /var/log/journal

# 3. Перезапуск службы
sudo systemctl restart systemd-journald
```

> **Диагностическая ценность:** По умолчанию журнал может храниться в оперативной памяти и очищаться при перезагрузке. Перевод его в режим `persistent` превращает логи в "спасательный круг": после краха системы вы сможете спокойно изучить журнал именно той сессии, на которой произошел сбой.

### Production-ready конфигурация journald.conf

Полная конфигурация для production-сервера:

```ini
[Journal]
# Хранение
Storage=persistent
Compress=yes
Seal=yes
SplitMode=uid

# Лимиты размера
SystemMaxUse=1G
SystemKeepFree=2G
SystemMaxFileSize=200M
RuntimeMaxUse=200M

# Лимиты времени
MaxRetentionSec=30day
MaxFileSec=1day

# Rate limiting
RateLimitIntervalSec=5s
RateLimitBurst=10000

# Интеграция
ForwardToSyslog=no
ForwardToWall=no
ForwardToConsole=no

# Производительность
SyncIntervalSec=5m
LineMax=48K
```

**Применение настроек:**
```bash
sudo systemctl restart systemd-journald
journalctl --disk-usage
# → Archived and active journals take up 1.2G on disk.
```

### Ограничение размера и времени хранения (Ротация)

Настройка производится в `/etc/systemd/journald.conf` (секция `[Journal]`). `journald` имеет встроенные механизмы ротации и очистки, предпочтительные перед внешними утилитами вроде `logrotate`.

```ini
[Journal]
# Режим хранения: auto, persistent, volatile, none
Storage=persistent

# Максимальный общий размер журнала на диске
SystemMaxUse=2G

# Минимальный объем свободного места на диске (резерв для ОС)
SystemKeepFree=15%

# Максимальный размер одного файла журнала до ротации
SystemMaxFileSize=200M

# Максимальное время хранения файлов журнала (удаление старых)
MaxRetentionSec=1month

# Максимальное время записи в один файл до его принудительной ротации
MaxFileSec=1week

# Ограничение скорости записи (Rate Limiting) для защиты от флуда
RateLimitIntervalSec=5s
RateLimitBurst=10000

# Сжатие данных (по умолчанию включено для файлов > 512 байт)
Compress=yes
```

**Основные параметры лимитов:**

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `SystemMaxUse` | Лимит суммарного объема логов на диске (`/var/log/journal`) | `500M`, `4G` |
| `RuntimeMaxUse` | Лимит для volatile-хранилища (`/run/log/journal`) | `200M` |
| `SystemKeepFree` | Гарантированный запас свободного места на ФС | `15%`, `10G` |
| `MaxRetentionSec` | Удаление логов старше указанного времени | `1month`, `14days` |
| `MaxFileSec` | Ротация активного файла журнала по времени | `1week` |

### Глубина логирования (MaxLevel)

Параметры `MaxLevel*` позволяют фильтровать события на этапе их записи в журнал или пересылки, что критично для экономии места на нагруженных серверах:

* **`MaxLevelStore`**: Определяет максимальный уровень логов, сохраняемых в журнале (например, `info` отсечет `debug`).
* **`MaxLevelSyslog`**: Глубина логов, пересылаемых в syslog.
* **`MaxLevelWall`**: Глубина логов, отправляемых всем залогиненным пользователям (`wall`).

**Практическое применение:**
```ini
# /etc/systemd/journald.conf
[Journal]
# Сохранять только info и выше (отсечь debug)
MaxLevelStore=info

# Пересылать в syslog только warning и выше
MaxLevelSyslog=warning

# Отправлять wall только для emerg/alert
MaxLevelWall=alert
```

### Ручная очистка журнала (Vacuuming)

Если требуется немедленно освободить место, не дожидаясь срабатывания лимитов:

```bash
# Удалить логи старше 7 дней
sudo journalctl --vacuum-time=7d

# Оставить логи только до указанного размера (например, 500 МБ)
sudo journalctl --vacuum-size=500M

# Оставить только указанное количество файлов (ротаций)
sudo journalctl --vacuum-files=5
```
Подробные инструкции по управлению хранением описаны в:
**[Управление хранением и очистка journalctl](../../Diagnostics/journalctl/journalctl_management.md)**

### Удаленное логирование (Remote Logging)

Для построения централизованных систем сбора логов в экосистеме systemd используются:

1.  **`systemd-journal-upload`**: Отправляет локальные логи на удаленный сервер по HTTP(S). Конфигурация: `/etc/systemd/journal-upload.conf`.
2.  **`systemd-journal-remote`**: Принимает логи и сохраняет их в бинарном формате journald. Конфигурация: `/etc/systemd/journal-remote.conf`.
3.  **`systemd-journal-gatewayd`**: Предоставляет HTTP API для доступа к логам.

**Конфигурация journal-upload (клиент):**
```ini
# /etc/systemd/journal-upload.conf
[Upload]
URL=https://log-server:19532
ServerKeyFile=/etc/ssl/journal-upload/server.key
ServerCertificateFile=/etc/ssl/journal-upload/server.crt
TrustedCertificateFile=/etc/ssl/journal-upload/ca.crt
```

**Конфигурация journal-remote (сервер):**
```ini
# /etc/systemd/journal-remote.conf
[Remote]
ServerKeyFile=/etc/ssl/journal-server/server.key
ServerCertificateFile=/etc/ssl/journal-server/server.crt
TrustedCertificateFile=/etc/ssl/journal-server/ca.crt
Input=stdin
```

**Запуск сервисов:**
```bash
# На клиенте
sudo systemctl enable --now systemd-journal-upload

# На сервере
sudo systemctl enable --now systemd-journal-remote
```

### Централизованный сбор логов через rsyslog

В большинстве production-сред journald используется как локальный сборщик, а rsyslog отвечает за пересылку на центральный сервер:

```ini
# /etc/systemd/journald.conf
[Journal]
ForwardToSyslog=no
ForwardToWall=no
```

```bash
# /etc/rsyslog.d/50-forward.conf
# Пересылка всего на центральный сервер
*.* @log-server.example.com:514

# Или с TLS
*.* @@log-server.example.com:6514
```

**Преимущества такого подхода:**
- journald собирает логи с ранних этапов загрузки и из systemd-юнитов.
- rsyslog выполняет сложную фильтрацию, буферизацию и пересылку.
- Центральный сервер получает единый поток логов от всех хостов.

### Мониторинг логов пользовательских служб (user services)

Для сервисов, запущенных в контексте пользователя (`--user`):

```bash
# Просмотр логов пользовательских сервисов
journalctl --user -u myapp -f

# Включение lingering для сервисов, работающих без сессии
sudo loginctl enable-linger <username>

# Проверка размера журналов пользователя
journalctl --user --disk-usage

# Очистка старых записей пользователя
journalctl --user --vacuum-time=30d
```

**Важно:** Без `lingering` пользовательские логи удаляются при завершении сессии. Для серверных приложений (агенты, боты) всегда включайте `lingering`.

### Анализ загрузки системы через journald

journald является первым демоном, запускаемым systemd, поэтому он содержит логи с самых ранних этапов загрузки:

```bash
# Все события текущей загрузки
journalctl -b

# Логи предыдущей загрузки (если доступны)
journalctl -b -1

# Список всех доступных загрузок
journalctl --list-boots

# Только ошибки ядра текущей загрузки
journalctl -k -b -p err

# Время достижения целевых состояний
journalctl -b | grep "Reached target"
```

### Мониторинг journald в реальном времени

```bash
# Все ошибки и критические сообщения в реальном времени
journalctl -f -p err

# Мониторинг конкретного сервиса
journalctl -u nginx -f --since "1 hour ago"

# Мониторинг нескольких сервисов одновременно
journalctl -u sshd -u fail2ban -f

# Мониторинг с тихой фильтрацией (только warning и выше)
journalctl -f --quiet=warning

# Мониторинг ядра
journalctl -k -f
```

### Интеграция с мониторингом и SIEM

#### Prometheus (node_exporter textfile collector)

Генерация метрик для Prometheus:

```bash
#!/bin/bash
# /usr/local/bin/journal-metrics.sh
# Генерация метрик journald для node_exporter

METRICS_FILE="/var/lib/prometheus/node-exporter/journal-metrics.prom"
mkdir -p $(dirname $METRICS_FILE)

# Размер журнала
SIZE=$(du -sb /var/log/journal 2>/dev/null | cut -f1)
FILES=$(ls /var/log/journal/*/*.journal 2>/dev/null | wc -l)
STATUS=$(systemctl is-active systemd-journald)

cat > $METRICS_FILE <<EOF
# HELP journal_size_bytes Journal size in bytes
# TYPE journal_size_bytes gauge
journal_size_bytes $SIZE
# HELP journal_files_count Number of journal files
# TYPE journal_files_count gauge
journal_files_count $FILES
# HELP journal_service_up Journal service status (1=up, 0=down)
# TYPE journal_service_up gauge
journal_service_up $([ "$STATUS" = "active" ] && echo 1 || echo 0)
EOF
```

```ini
# /etc/systemd/system/journal-metrics.service
[Unit]
Description=Generate journald metrics for Prometheus
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/journal-metrics.sh
```

```ini
# /etc/systemd/system/journal-metrics.timer
[Unit]
Description=Run journal metrics generator every 5 minutes

[Timer]
OnCalendar=*:00/5
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now journal-metrics.timer
```

#### Loki / Promtail

Для доставки логов в Loki используйте Promtail или Grafana Alloy:

```yaml
# /etc/promtail/config.yml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: journald
    journal:
      max_age: 1h
      labels:
        job: journald
        host: web01
    relabel_configs:
      - source_labels: [__journal__systemd_unit]
        target_label: systemd_unit
```

### Интеграция с syslog

Для поддержки legacy-инфраструктуры (например, `rsyslog`), `journald` может пересылать сообщения в сокет syslog (`/run/systemd/journal/syslog`).

```ini
# В /etc/systemd/journald.conf
[Journal]
ForwardToSyslog=yes
```

### Настройка защиты от подделки (Forward Secure Sealing - FSS)

FSS использует криптографические алгоритмы для добавления специальных меток в журнал. Это позволяет обнаружить модификацию, усечение или подмену прошлых записей (например, если сервер был скомпрометирован).

1. **Генерация ключей:**
   ```bash
   sudo journalctl --setup-keys
   ```
   Утилита сгенерирует пару ключей. Секретный ключ (Sealing Key) остается на сервере (в `/var/log/journal/`), а ключ верификации (Verification Key) будет выведен на экран — **его необходимо сохранить в безопасном месте вне сервера**.

2. **Настройка интервала печати (опционально):**
   В `/etc/systemd/journald.conf`:
   ```ini
   [Journal]
   Seal=yes
   # Как часто добавлять криптографическая печать (по умолчанию 15m)
   SealIntervalSec=10m
   ```

3. **Верификация логов (после инцидента):**
   ```bash
   # Потребуется ввести Verification Key, сохраненный ранее
   journalctl --verify --verify-key=<сохраненный-ключ>
   # → PASS: /var/log/journal/.../system.journal
   ```

### Аудит безопасности через journald

journald автоматически собирает события безопасности, связанные с системными сервисами:

```bash
# Все неудачные попытки входа по SSH
journalctl -u sshd --since today | grep "Failed password"

# Успешные входы по SSH
journalctl -u sshd --since today | grep "Accepted"

# Использование sudo конкретным пользователем
journalctl _COMM=sudo _UID=1000 --since today

# События systemd-logind (создание/удаление сессий)
journalctl -u systemd-logind.service -n 50 --no-pager

# SELinux denials
journalctl -u nginx | grep -i "denied"
```

### Корреляция событий по Boot ID

```bash
# Найти Boot ID проблемной загрузки
journalctl --list-boots

# Просмотреть события конкретного Boot ID
journalctl -b -1 _SYSTEMD_UNIT=network.target

# Сравнить поведение сервиса между загрузками
journalctl -b -1 -u app.service
journalctl -b -2 -u app.service
```

### Резервное копирование и восстановление

```bash
# 1. Синхронизация и ротация перед бэкапом
sudo journalctl --sync --rotate

# 2. Копирование директории (только после ротации!)
sudo cp -a /var/log/journal /backup/journal-$(date +%F)

# 3. Если используется FSS, скопировать также ключи
sudo cp -a /var/log/journal/privatekey /backup/

# Восстановление:
sudo systemctl stop systemd-journald
sudo rm -rf /var/log/journal/*
sudo cp -a /backup/journal-YYYY-MM-DD/* /var/log/journal/
sudo systemctl start systemd-journald
```

### Управление через системные сигналы

В автоматизированных скриптах или при отсутствии доступа к бинарнику `journalctl` можно использовать сигналы:

| Сигнал | Действие | Эквивалент |
| :--- | :--- | :--- |
| `SIGUSR1` | Перенос логов из RAM на диск | `journalctl --flush` |
| `SIGRTMIN+1` | Принудительная ротация | `journalctl --rotate` |

```bash
# Пример: принудительная ротация через kill
sudo systemctl kill -s SIGRTMIN+1 systemd-journald
```

### Оперативное изменение параметров без редактирования файла

```bash
# Временное изменение через systemd override
sudo systemctl edit systemd-journald

# Добавить в [Service] секцию:
# [Service]
# Environment=SYSTEMD_JOURNALD_OVERRIDE="SystemMaxUse=1G MaxRetentionSec=14d"

# Или через drop-in файл
sudo mkdir -p /etc/systemd/system/systemd-journald.service.d
cat <<'EOF' | sudo tee /etc/systemd/system/systemd-journald.service.d/override.conf
[Service]
Environment=SYSTEMD_JOURNALD_OVERRIDE="SystemMaxUse=1G MaxRetentionSec=14d"
EOF

sudo systemctl daemon-reload
sudo systemctl restart systemd-journald
```

### Сценарий: Инцидент "Диск заполнен логами"

```bash
# 1. Немедленная диагностика
df -h /var/log
journalctl --disk-usage
du -sh /var/log/journal/* | sort -rh | head -10

# 2. Экстренная очистка (оставить минимум)
sudo journalctl --sync --rotate
sudo journalctl --vacuum-size=100M
sudo journalctl --vacuum-time=1d

# 3. Если не помогло — ручная очистка архивов
sudo find /var/log/journal -name "*.journal~" -delete
sudo find /var/log/journal -name "*.journal" -size +1G -delete

# 4. Проверка, что сервис работает
sudo systemctl status systemd-journald

# 5. Постоянное решение — настройка лимитов в journald.conf
sudo nano /etc/systemd/journald.conf
# Установить: SystemMaxUse=1G, MaxRetentionSec=7d
sudo systemctl restart systemd-journald
```

## Дополнительная информация

### Безопасность и целостность

* **Защита от подделки:** Структурированный бинарный формат затрудняет ручное редактирование логов злоумышленником. Включите `Seal=yes` в `journald.conf` для криптографической защиты.
* **ACL (Access Control List):** Доступ ограничен пользователями в группах `systemd-journal`, `adm` (Debian/Ubuntu) или `wheel` (RHEL/Fedora). Проверяйте права:
  ```bash
  sudo stat -c '%a %U:%G' /var/log/journal
  # → 2755 root:systemd-journal
  ```
* **SplitMode**: Определяет, как распределяются записи. `SplitMode=uid` (по умолчанию) создает отдельные файлы для каждого пользователя, `SplitMode=none` пишет всё в один системный журнал.
* **Права на директорию:** Для постоянного хранения используйте `chmod 2755` (setgid для группы systemd-journal).
* **ForwardToSyslog:** Отключайте `ForwardToSyslog=yes`, если используется rsyslog, чтобы избежать дублирования логов в `/var/log/syslog`.

### Производительность

* **Асинхронная запись:** `journald` использует асинхронную запись по умолчанию для минимизации блокировок ввода-вывода.
* **`SyncIntervalSec`**: Интервал принудительного сброса данных на диск (по умолчанию 5 мин). Уменьшение значения увеличивает нагрузку на диск, но снижает риск потери логов при сбое.
* **`LineMax`**: Максимальная длина строки лога (по умолчанию 48k). Длинные строки будут обрезаны. Увеличивайте только при необходимости логировать большие объемы данных (например, JSON-строки).
* **Сжатие:** Архивные файлы сжимаются (LZ4 или XZ). Это экономит место на диске, но может немного замедлять доступ при чтении очень старых архивов.
* **mmap():** journald использует отображение файлов в память для быстрого доступа. Однако это означает, что активный файл нельзя удалить — сначала выполните ротацию.

### Best Practices

1. **Всегда используйте `Storage=persistent`** на production-серверах. Энергозависимое хранение (`volatile`) приводит к потере логов после перезагрузки.
2. **Настраивайте лимиты заранее:** Установите `SystemMaxUse` и `MaxRetentionSec` до того, как диск заполнится. Рекомендуемые значения: `SystemMaxUse=1G`, `MaxRetentionSec=30day`.
3. **Используйте `SplitMode=uid`** для многопользовательских систем, `SplitMode=machine` для серверов с большим количеством сервисов.
4. **Включайте `Seal=yes`** на критичных серверах для защиты от подделки логов.
5. **Отключайте `ForwardToSyslog`**, если используется rsyslog для пересылки, чтобы избежать дублирования.
6. **Мониторьте размер журнала:** Добавьте проверку свободного места в `/var/log` в ваши скрипты мониторинга.
7. **Используйте `journalctl --vacuum`** вместо ручного удаления файлов — это безопаснее и корректно обрабатывает активные файлы.
8. **Для сервисов без systemd** (cron, shell-скрипты) используйте `logger` или перенаправляйте stdout/stderr в journald через `systemd-cat`.

### Соответствие требованиям (Compliance)

* **PCI DSS v4.0.1:** Требует хранения логов аудита не менее 12 месяцев. Настройте `MaxRetentionSec=1year` и обеспечьте централизованный сбор.
* **CIS Benchmarks:** Рекомендуют `Storage=persistent`, `Seal=yes`, `ForwardToSyslog=no` и ограничение доступа к `/var/log/journal`.
* **ФЗ-152 (Россия):** Требует защиты персональных данных. Используйте `Seal=yes` для гарантии целостности логов.

### Известные ограничения

1. **Энергозависимое хранение по умолчанию:** На свежеустановленных системах без `/var/log/journal` логи хранятся в RAM и теряются после перезагрузки.
2. **Отсутствие `_SYSTEMD_UNIT`:** Процессы, не запущенные через systemd (например, напрямую из cron или shell), могут не иметь поля `_SYSTEMD_UNIT`. Вместо него используйте `_COMM` или `_EXE`.
3. **Регистр в `--grep`:** По умолчанию `--grep` (`-g`) чувствителен к регистру. Используйте `--grep-case-sensitive=false` для нечувствительного поиска.
4. **Бинарные данные в полях:** Некоторые поля (например, `_CMDLINE`) могут содержать непечатаемые символы. При парсинге JSON учитывайте, что значения могут быть base64-encoded.
5. **Ограничение частоты записи (Rate Limiting):** journald по умолчанию подавляет дублирующиеся сообщения. Если важные логи отсутствуют, проверьте настройки `RateLimitIntervalSec` и `RateLimitBurst` в `journald.conf`.
6. **Версия systemd:** Некоторые функции (например, `--namespace`, `--output-fields`) доступны только в systemd 245+. Проверяйте версию:
   ```bash
   journalctl --version
   ```

### Типичные проблемы и решения

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Логи пропадают после перезагрузки** | Режим `Storage=volatile` | Создать директорию `/var/log/journal` или установить `Storage=persistent`. |
| **Журнал переполняет диск** | Не настроены лимиты ротации | Настроить `SystemMaxUse` и `MaxRetentionSec` в `journald.conf`. |
| **Высокая нагрузка на CPU** | Интенсивный поток логов (флуд) | Настроить `RateLimit` или использовать `LogLevelMax=` в юнит-файле сервиса. |
| **Ошибка "Suppressed X messages"** | Срабатывает Rate Limit | Увеличить `RateLimitBurst` и `RateLimitIntervalSec` в `journald.conf`. |
| **Повреждение файлов журнала** | Внезапное отключение питания | Проверка: `journalctl --verify`. Битые файлы следует переместить из `/var/log/journal/`. |
| **Дублирование логов в `/var/log/syslog`** | `ForwardToSyslog=yes` в journald.conf | Отключить: `ForwardToSyslog=no`. |
| **Нет логов пользовательских сервисов** | Не включен lingering | `loginctl enable-linger <username>` |
| **Логи не сохраняются после ребута** | Режим `Storage=volatile` или нет папки | Проверьте `journald.conf` и наличие `/var/log/journal`. |
| **Ошибка доступа к `/var/log/journal`** | Неверные права доступа | Проверьте права: `chown root:systemd-journal /var/log/journal`. |

### См. также

* **rsyslog:** Обработка и пересылка логов. Подробнее: [rsyslog](./rsyslog.md).
* **auditd:** Аудит безопасности на уровне ядра. Подробнее: [auditd](./auditd.md).
* **journalctl:** Утилита просмотра логов. Полное описание: [journalctl](../../Diagnostics/journalctl/journalctl_overview.md).
* **Управление хранением и очистка:** Подробные инструкции по vacuum и ротации: [journalctl_management](../../Diagnostics/journalctl/journalctl_management.md).
* **Управление логами в Docker:** Использование драйвера journald: [docker_centralized_logging](../../../Docker/Docker_logs/docker_centralized_logging.md).
* **Обзор логирования:** [logging_overview](./logging_overview.md).
