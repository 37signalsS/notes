# Обзор системы логирования в Linux

## Определения

**Системные журналы (логи)** — файлы, в которые записываются системные сообщения и события. Анализ логов — ключевой навык для диагностики проблем, отслеживания производительности и расследования инцидентов безопасности.

**Архитектура логирования в современных Linux:**

| Компонент | Назначение | SSoT |
| :--- | :--- | :--- |
| `systemd-journald` | Централизованный сбор логов в бинарном формате | [journald.md](./journald.md) |
| `journalctl` | Просмотр и анализ логов journald | [journalctl.md](../../Diagnostics/Logging/journalctl.md) |
| `rsyslog` | Фильтрация, обработка и пересылка логов | [rsyslog.md](./rsyslog.md) |
| `auditd` | Аудит событий безопасности на уровне ядра | [auditd.md](./auditd.md) |
| `logrotate` | Ротация и архивация текстовых логов | См. ниже |

Часто эти системы работают вместе: `journald` собирает сообщения, `rsyslog` забирает их для фильтрации и пересылки, `logrotate` управляет размером файлов.

## Базовые концепции

### Стандартные файлы и директории логов

Несмотря на то, что `journald` хранит логи в бинарном формате, многие службы по-прежнему пишут текстовые логи в директорию `/var/log/`. Это поведение часто настраивается через `rsyslog`.

- `/var/log/syslog` (Debian/Ubuntu) или `/var/log/messages` (CentOS/RHEL): Главный системный лог, куда попадает большинство событий от ядра и служб.
- `/var/log/auth.log` (Debian/Ubuntu) или `/var/log/secure` (CentOS/RHEL): События аутентификации (входы по SSH, `sudo`, неудачные попытки). **Ключевой файл для анализа безопасности.** Для более детального аудита событий безопасности см. [auditd: Аудит событий безопасности](./auditd.md).
- `/var/log/dmesg`: Сообщения ядра при загрузке. Подробнее см. [dmesg: Просмотр сообщений ядра](../../Diagnostics/Kernel/dmesg.md).
- `/var/log/boot.log`: Лог процесса загрузки.
- `/var/log/apt/` (Debian/Ubuntu) или `/var/log/yum.log` (CentOS/RHEL): Логи менеджера пакетов.
- **Логи приложений:** Многие приложения (например, `nginx`, `apache2`, `postgresql`) создают свои собственные поддиректории в `/var/log/`.

### Централизованное логирование

Хранение логов локально на каждом хосте имеет ряд существенных недостатков:

- Потребление дискового пространства и I/O.
- Угроза безопасности: Локальные логи проще удалить или подделать злоумышленником.
- Сложность анализа: В больших инфраструктурах анализ логов на каждом хосте вручную неэффективен.
- Отсутствие агрегации: Сложно коррелировать события между разными хостами.

Для решения этих проблем применяется **централизованное логирование**, когда логи со всех хостов собираются на выделенных серверах. Традиционно это достигается с помощью `rsyslog`, но в современных распределенных системах используются специализированные агенты (Fluentd, Vector) и брокеры сообщений (Kafka). Подробнее о подходах к централизованному логированию в контексте наблюдаемости см. [Мониторинг и Observability (Наблюдаемость / O11y)](../../../Concepts/Observability_and_Monitoring/observability_overview.md), а о проектировании высоконагруженной доставки логов — [Проектирование высоконагруженного мониторинга в распределенных системах](../../../Concepts/Observability_and_Monitoring/designing_high-load_monitoring_in_distributed_systems.md).

### Ротация логов (`logrotate`)

Чтобы текстовые лог-файлы не занимали все место на диске, утилита `logrotate` периодически их архивирует, сжимает и удаляет.

- **Основной конфиг:** `/etc/logrotate.conf`
- **Конфиги для отдельных служб:** `/etc/logrotate.d/`

## Практические сценарии

### Отправка тестовых сообщений: `logger`

Утилита `logger` позволяет отправлять сообщения в syslog вручную. Это полезно для тестирования конфигурации rsyslog, проверки централизованного сбора логов или отладки скриптов.

```bash
# Отправить сообщение с уровнем info в facility user (по умолчанию)
logger "Тестовое сообщение"

# Отправить сообщение с указанием facility и priority
logger -t myscript -p local0.info "Скрипт выполнен успешно"

# Отправить сообщение на удаленный syslog-сервер (если настроено)
logger -n 192.168.1.100 -p local0.info "Удаленное сообщение"
```

- `-t tag`: Добавить тег к сообщению (обычно имя скрипта или процесса)
- `-p facility.priority`: Указать facility (источник) и priority (уровень важности)
- `-n server`: Отправить на удаленный хост

### Анализ логов с помощью командной строки

- **`tail`**: Просмотр конца файла в реальном времени (`tail -f /var/log/syslog`).
- **`less`**: Мощный просмотрщик с поиском (`/`, `?`) и фильтрацией (`&`).
- **`grep`**: Поиск текста по шаблону (`grep "error" /var/log/syslog`).
- **`zcat` / `zgrep`**: Утилиты для работы со сжатыми логами (`.gz`), созданными `logrotate`.

### Пример конфигурации `logrotate`

Конфигурация в `/etc/logrotate.d/nginx` для ротации логов веб-сервера:

```
/var/log/nginx/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 nginx adm
    sharedscripts
    postrotate
        [ -f /var/run/nginx.pid ] && kill -USR1 `cat /var/run/nginx.pid`
    endscript
}
```

- `daily`: Ротировать ежедневно.
- `rotate 14`: Хранить 14 старых логов.
- `compress`: Сжимать старые логи.
- `postrotate...endscript`: Команды, которые выполняются после ротации (здесь — сигнал Nginx переоткрыть лог-файлы).

**Проверка конфигурации:**

```bash
# Выполнить "сухой запуск" для отладки
sudo logrotate -d /etc/logrotate.conf
```

### Принудительная синхронизация буферов: `sync`

Команда `sync` принудительно записывает все данные из буферов памяти на диск. Это полезно перед выключением системы или для гарантии записи критических логов:

```bash
# Синхронизировать все отложенные записи на диск
sync
```

Применяется не только к логам, но и к любым файловым операциям.

### Методология диагностики проблем логирования

| Проблема | Порядок диагностики |
| :--- | :--- |
| Сервис не запускается | 1. `journalctl -u <сервис> -b`<br>2. `systemctl status <сервис>`<br>3. Проверить логи приложения в `/var/log/<app>/` |
| Ошибки аутентификации | 1. `journalctl -p err -b`<br>2. `/var/log/auth.log` или `/var/log/secure`<br>3. `ausearch -m USER_LOGIN` (если настроен `auditd`) |
| Проблемы ядра/драйверов | 1. `journalctl -k -b`<br>2. [`dmesg -T`](../../Diagnostics/Kernel/dmesg.md)<br>3. `dmesg --level=err,warn` |
| Дисковое пространство | 1. `journalctl --disk-usage`<br>2. `du -sh /var/log/*`<br>3. Проверить конфигурацию `logrotate` |
| Проблемы загрузки | 1. `journalctl --list-boots`<br>2. `journalctl -b -1` (предыдущая загрузка)<br>3. [`reboot_troubleshooting.md`](../../Diagnostics/Troubleshooting/reboot_troubleshooting.md) |
| Инцидент безопасности | 1. `ausearch -m SYSCALL`<br>2. `/var/log/audit/audit.log`<br>3. `journalctl _UID=0` (действия root) |

## Ссылки по теме

### Основные компоненты

* **systemd-journald:** [journald.md](./journald.md) — демон, конфигурация, хранение.
* **journalctl:** [journalctl.md](../../Diagnostics/Logging/journalctl.md) — утилита просмотра логов.
* **rsyslog:** [rsyslog.md](./rsyslog.md) — фильтрация и пересылка.
* **auditd:** [auditd.md](./auditd.md) — аудит безопасности.

### Диагностика

* **dmesg:** [dmesg.md](../../Diagnostics/Kernel/dmesg.md) — логи ядра.
* **Анализ сбоев:** [error_and_crash_analysis.md](./error_and_crash_analysis.md) — coredump, kdump.
* **Troubleshooting:** [general_troubleshooting_methodology.md](../../Diagnostics/Troubleshooting/general_troubleshooting_methodology.md).

### Observability

* **Централизованное логирование:** [Observability and Monitoring](../../../Concepts/Observability_and_Monitoring/observability_overview.md).
* **Высоконагруженный мониторинг:** [designing_high-load_monitoring_in_distributed_systems.md](../../../Concepts/Observability_and_Monitoring/designing_high-load_monitoring_in_distributed_systems.md).
