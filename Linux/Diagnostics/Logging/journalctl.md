# `journalctl`: Просмотр и анализ логов Systemd

## Определения

* **`journalctl`** — утилита командной строки для просмотра, фильтрации и анализа логов, собранных службой `systemd-journald`. Является основным инструментом для работы с журналом systemd.
* **`systemd-journald`** — системная служба, централизованно собирающая логи от всех компонентов ОС (ядро, службы, приложения, stdout/stderr) в структурированном бинарном формате. Конфигурация демона описана в [journald.md](../../SystemAdministration/Logging/journald.md).

Информация о демоне `systemd-journald` находится в [journald.md](../../SystemAdministration/Logging/journald.md).

## Основные концепции

### Централизованное и структурированное логирование

Служба `systemd-journald` собирает логи со всего окружения `systemd` (ядро, системные сервисы, приложения, stdout/stderr) в **структурированном бинарном формате**. В отличие от традиционных текстовых логов (например, `rsyslog`), это обеспечивает:

* **Централизацию:** Все системные сообщения хранятся в одном месте.
* **Обогащение метаданными:** Каждое сообщение автоматически получает метаданные (имя сервиса, PID процесса, UID пользователя, уровень приоритета и т.д.).
* **Мощную и быструю фильтрацию:** Возможность фильтровать логи по любым метаданным без парсинга текстовых строк.

### Хранение логов

Логи `systemd-journald` могут храниться двумя способами:

1. **Энергозависимое (Volatile):** По умолчанию логи хранятся в `/run/log/journal`. Эта директория монтируется как `tmpfs` и очищается при каждой перезагрузке системы.
2. **Постоянное (Persistent):** Если существует директория `/var/log/journal`, `systemd-journald` автоматически начнет использовать её для постоянного хранения логов. В этом случае логи сохраняются между перезагрузками.

### Уровни приоритета логов

`journalctl` позволяет фильтровать сообщения по их уровню приоритета (от 0 до 7, от самого критического до отладочного):

* `0: emerg` (System is unusable)
* `1: alert` (Action must be taken immediately)
* `2: crit` (Critical conditions)
* `3: err` (Error conditions)
* `4: warning` (Warning conditions)
* `5: notice` (Normal but significant condition)
* `6: info` (Informational messages)
* `7: debug` (Debug-level messages)

## Практические сценарии (`journalctl`)

### 1. Просмотр логов

* **Все логи (в обратном хронологическом порядке):**

    ```bash
    journalctl
    ```

* **Логи в реальном времени (поток событий):**

    ```bash
    journalctl -f
    ```

* **Логи ядра (аналог `dmesg`):**

    ```bash
    journalctl -k
    # Или для просмотра в реальном времени:
    journalctl -kf
    ```

* **Логи с последней загрузки:**

    ```bash
    journalctl -b
    # Для предыдущей загрузки (например, -1, -2 и т.д.):
    journalctl -b -1
    ```

* **Список всех зарегистрированных загрузок (для выбора конкретной):**

    ```bash
    journalctl --list-boots
    ```

* **Логи от новых к старым (обратный порядок):**

    ```bash
    journalctl -r
    ```

### 2. Фильтрация логов

* **По службе (unit):**

    ```bash
    # Логи сервиса Nginx
    journalctl -u nginx.service
    # И с отслеживанием в реальном времени:
    journalctl -u nginx.service -f
    ```

* **По нескольким службам:**

    ```bash
    journalctl -u sshd.service -u httpd.service
    ```

* **По идентификатору процесса (PID):**

    ```bash
    journalctl _PID=1234
    ```

* **По идентификатору пользователя (UID):**

    ```bash
    journalctl _UID=1000
    ```

* **По времени:**

    ```bash
    # За последний час
    journalctl --since "1 hour ago"
    # С определенной даты и времени
    journalctl --since "2023-10-26 18:00:00"
    # Между двумя датами
    journalctl --since "2023-10-26 18:00:00" --until "2023-10-26 18:10:00"
    ```

* **По уровню приоритета:**

    ```bash
    # Только ошибки и более критичные сообщения
    journalctl -p err
    # Только предупреждения и ошибки
    journalctl -p warning..err
    ```

* **По пути к исполняемому файлу:**

    ```bash
    journalctl /usr/lib/systemd/systemd
    ```

### 3. Настройка и управление хранением логов

**Важно:** Настройка хранения логов (persistent/volatile, лимиты размера) выполняется на уровне демона `systemd-journald`. Подробное описание конфигурации находится в [journald.md](../../SystemAdministration/Logging/journald.md#настройка-постоянного-хранения).

Ниже приведены команды `journalctl` для мониторинга использования дискового пространства:

* **Проверить текущий размер журнала:**

    ```bash
    journalctl --disk-usage
    ```

* **Очистка журнала (освобождение места):**

    ```bash
    # Оставить только последние 500 МБ логов
    sudo journalctl --vacuum-size=500M

    # Оставить логи только за последние 2 дня
    sudo journalctl --vacuum-time=2d

    # Оставить только N последних записей (файлов журнала)
    sudo journalctl --vacuum-files=5
    ```

### 4. Экспорт и форматирование вывода

`journalctl` поддерживает различные форматы вывода, что полезно для интеграции с системами мониторинга или дальнейшей обработки скриптами:

* **JSON-формат (машиночитаемый вывод):**

    ```bash
    # Вывод в JSON (одна строка на запись)
    journalctl -u nginx.service --output=json

    # Вывод в JSON (красивый, многострочный)
    journalctl -u nginx.service --output=json-pretty

    # Вывод в JSON с экранированием (для парсинга)
    journalctl -u nginx.service --output=json-sse
    ```

* **Другие форматы:**

    ```bash
    # Короткий вывод (только сообщение)
    journalctl -u nginx.service --output=cat

    # Вывод в формате syslog (традиционный формат)
    journalctl -u nginx.service --output=syslog

    # Вывод с дополнительными метаданными (journal format)
    journalctl -u nginx.service --output=short-journal
    ```

### 5. Расширенные сценарии использования

* **Поиск по содержимому логов (аналог grep):**

    ```bash
    # Поиск по тексту в логах (регистронезависимый)
    journalctl -u nginx.service | grep -i "error"

    # Встроенный поиск journalctl (быстрее, т.к. использует индексы)
    journalctl -u nginx.service -g "error"
    ```

* **Подсчет событий:**

    ```bash
    # Подсчитать количество ошибок сервиса
    journalctl -u nginx.service -p err --no-pager | wc -l

    # Статистика по уровням логирования
    journalctl -u nginx.service --no-pager | awk '{print $5}' | sort | uniq -c
    ```

* **Сравнение логов между загрузками:**

    ```bash
    # Логи сервиса за текущую и предыдущую загрузку
    journalctl -u nginx.service -b 0
    journalctl -u nginx.service -b -1
    ```

* **Мониторинг конкретных полей (метаданных):**

    ```bash
    # Показать только PID процессов
    journalctl -u nginx.service -o verbose | grep _PID

    # Показать только сообщения от определенного исполняемого файла
    journalctl EXE=/usr/sbin/nginx
    ```

## Дополнительная информация

### Маскировка чувствительных данных

`journalctl` поддерживает маскировку конфиденциальных полей (например, паролей, токенов):

```bash
# Автоматически скрывать значения полей PASSWORD, SECRET и т.д.
journalctl --mask
```

По умолчанию маскируются поля: `PASSWORD`, `PASSPHRASE`, `SECRET`, `_PASSWORD`, `_PASSPHRASE`.

### Отладка и диагностика проблем с journald

* **Проверить статус службы journald:**

    ```bash
    systemctl status systemd-journald
    ```

* **Проверить, какие поля доступны в журнале:**

    ```bash
    journalctl --fields
    ```

* **Включить отладочное логирование самого journald:**

    ```bash
    # Временно увеличить уровень логирования
    sudo systemctl kill -s SIGUSR1 systemd-journald
    ```

### Производительность и ограничения

* **Индексация:** `journalctl` использует индексы для быстрого поиска по времени, PID, UID и другим полям. Поиск по тексту (`-g`) также ускорен.
* **Бинарный формат:** Хранение в бинарном формате обеспечивает высокую скорость записи и чтения, но требует специальных утилит (`journalctl`) для просмотра.
* **Ограничения размера:** При достижении лимитов (`SystemMaxUse`) старые логи автоматически удаляются (FIFO).
* **Не подходит для долгосрочного хранения:** Для архивации логов на месяцы/годы используйте пересылку в [rsyslog](../../SystemAdministration/Logging/rsyslog.md) или специализированные системы (ELK, Loki, Splunk).

### Типичные проблемы и решения

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `journalctl` показывает только логи текущей загрузки | Не настроено persistent storage | Создать `/var/log/journal` и перезапустить `systemd-journald` (см. [journald.md](../../SystemAdministration/Logging/journald.md)) |
| Логи занимают слишком много места | Не настроены лимиты | Настроить `SystemMaxUse` в `/etc/systemd/journald.conf` |
| Нет логов от конкретного сервиса | Сервис пишет в свой файл, а не в journald | Проверить конфигурацию сервиса или настроить интеграцию (см. [rsyslog.md](../../SystemAdministration/Logging/rsyslog.md)) |
| `journalctl -g` не находит текст | Поиск регистрозависимый или текст в экранированном поле | Использовать `grep` после `journalctl` или `-g "pattern"` с правильным паттерном |

### Интеграция с другими системами логирования

* **rsyslog:** `rsyslog` может забирать сообщения из `journald` через модуль `imjournal` для дальнейшей обработки и пересылки. Настройка описана в [rsyslog.md](../../SystemAdministration/Logging/rsyslog.md).
* **dmesg:** Для просмотра только логов ядра можно использовать [`dmesg`](../../Diagnostics/Kernel/dmesg.md) — SSoT для работы с кольцевым буфером ядра, низкоуровневой диагностики оборудования и OOM Killer. `journalctl -k` предоставляет больше возможностей фильтрации и долгосрочного хранения.
* **auditd:** Для аудита событий безопасности (системные вызовы, доступ к файлам) используется [`auditd`](../../SystemAdministration/Logging/auditd.md). Это отдельная подсистема, не связанная с `journald`.

### Ссылки по теме

* **Демон systemd-journald:** [journald.md](../../SystemAdministration/Logging/journald.md) — конфигурация демона, хранение логов.
* **Обзор системы логирования:** [logging_overview.md](../../SystemAdministration/Logging/logging_overview.md) — общая архитектура, `logrotate`, `logger`.
* **Логи ядра:** [dmesg.md](../../Diagnostics/Kernel/dmesg.md) — диагностика проблем ядра.
* **Устранение проблем с загрузкой:** [reboot_troubleshooting.md](../../Diagnostics/Troubleshooting/reboot_troubleshooting.md) — анализ проблем загрузки через `journalctl`.
* **Systemd:** [overview.md](../../Core/systemd/overview.md) — общие концепции systemd.
* **Анализ сбоев:** [error_and_crash_analysis.md](../../SystemAdministration/Logging/error_and_crash_analysis.md) — `coredumpctl`, `kdump`.
