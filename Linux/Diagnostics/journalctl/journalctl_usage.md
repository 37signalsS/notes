# Использование journalctl — Практические сценарии

## Определения

**Фильтрация по полям (Field Matching)** — метод извлечения записей на основе точного соответствия структурированным метаданным (например, `_PID=1`). Работает значительно быстрее полнотекстового поиска благодаря бинарным индексам.

**Логическая группировка (Logical Grouping)** — использование оператора `+` для построения сложных запросов, объединяющих наборы фильтров через логическое «И» (AND) и «ИЛИ» (OR).

**Курсор (Cursor)** — уникальный строковый указатель на конкретную запись. Используется в автоматизации для продолжения чтения логов с момента последней обработки, исключая дубликаты или пропуски.

**Пространство имен (Namespace)** — механизм изоляции логов (введен в systemd 245), позволяющий разделять системный журнал и журналы конкретных приложений.

**Boot ID** — уникальный 128-битный идентификатор, присваиваемый системе при каждой загрузке. Хранится в `/proc/sys/kernel/random/boot_id` и используется journald для маркировки записей, принадлежащих конкретной сессии.

**Journal File** — бинарный файл журнала. Бывает двух типов: **активный** (файл, в который в данный момент ведется запись) и **архивный** (закрытый файл только для чтения). Механизм очистки (`vacuum`) никогда не удаляет активные файлы.

**Ограничение частоты (Rate Limiting)** — механизм journald, который подавляет дублирующиеся сообщения при превышении порога `RateLimitBurst` за интервал `RateLimitIntervalSec`. Важен для предотвращения переполнения хранилища при циклических ошибках.

## Основные концепции

### Контекст выполнения и права

По умолчанию `journalctl` обращается к системному журналу.
- **Системные логи:** Требуют прав `root` или членства в группах `systemd-journal`, `adm` (Debian/Ubuntu) или `wheel` (RHEL/Fedora).
- **Пользовательские логи:** Флаг `--user` позволяет просматривать логи сервисов, запущенных в контексте текущего пользователя (доступно без sudo). Для сервисов, которые должны работать без активной пользовательской сессии, включите режим «lingering»:
  ```bash
  loginctl enable-linger <username>
  ```
- **Пути к хранилищу пользовательских логов:** Определяются переменной окружения `XDG_RUNTIME_DIR` (обычно `/run/user/<UID>`). При отсутствии lingering логи пользователя удаляются при завершении сессии.

### Управление выводом и окружение

- **Пейджер:** По умолчанию используется `less`. Для отключения (в скриптах или при перенаправлении) используйте `--no-pager`.
- **Окружение пейджера:** Переменные `SYSTEMD_PAGER` и `SYSTEMD_LESS` позволяют настроить поведение пейджера. Например, для отключения пейджера глобально:
  ```bash
  export SYSTEMD_PAGER=cat
  ```
- **Ширина строк:** По умолчанию длинные строки обрезаются. Флаг `-a` (`--all`) принудительно выводит данные полностью.
- **Интерактивность:** `-f` (`--follow`) обеспечивает мониторинг в реальном времени, аналогично `tail -f`.
- **Тихая фильтрация:** Флаг `--quiet` (или `--quiet=warning`) подавляет сообщения ниже указанного приоритета, что уменьшает объем вывода при мониторинге:
  ```bash
  journalctl -u myapp -f --quiet=warning
  ```
- **Количество строк:** Параметр `--lines` (или `-n`) управляет количеством выводимых строк. При использовании с `-f` ограничивает начальный объем:
  ```bash
  journalctl -u myapp -f --lines=50
  ```
- **Выбор полей для вывода:** Параметр `--output-fields` позволяет указать, какие поля выводить в форматах `short`, `short-precise`, `short-iso`, `verbose`:
  ```bash
  journalctl -u myapp -o short --output-fields=MESSAGE,_PID,_EXE
  ```

### Форматы вывода

Разные форматы предназначены для разных сценариев использования:

| Формат | Описание | Применение |
| :--- | :--- | :--- |
| `short` | Компактный текстовый формат (по умолчанию). | Интерактивный просмотр. |
| `short-iso` | `short` с меткой времени в формате ISO 8601. | Поиск по точному времени, парсинг. |
| `short-precise` | `short` с микросекундной точностью. | Анализ производительности, тайминг. |
| `verbose` | Полный вывод всех полей в формате `ключ=значение`. | Отладка, анализ структуры записи. |
| `json` | Одна запись на строку в формате JSON. | Парсинг через `jq`, интеграция с SIEM. |
| `json-pretty` | Многострочный отформатированный JSON. | Отладка структуры полей. |
| `cat` | Только текст сообщения. | Быстрый grep/awk, передачи в другие утилиты. |
| `export` | Специальный формат для импорта/экспорта (RFC 5424 совместимый). | Архивирование, передача между системами. |
| `with-unit` | `short` с добавлением имени юнита в начало каждой строки. | Мониторинг нескольких сервисов одновременно. |

### Сессии загрузки

Каждая перезагрузка системы помечается уникальным `_BOOT_ID`. Это позволяет `journalctl` обращаться к архивам логов прошлых сессий:

- **`--list-boots`:** Вывод списка всех доступных сессий с их ID, смещением и временем начала. Отрицательные индексы (`-1`, `-2`) позволяют обращаться к предыдущим загрузкам без знания точного ID.
- **`-b -1`:** Просмотр логов предыдущей загрузки. Аргумент может быть как числом (смещение от текущей), так и первым символом Boot ID.
- **`-b 0`:** Логи текущей сессии (значение по умолчанию).

```bash
# Список всех загрузок
journalctl --list-boots

# Логи загрузки 2 сессии назад
journalctl -b -2

# Логи конкретной загрузки по ID
journalctl -b a1b2c3d4e5f6...
```

### Метаданные журнала

Все записи в journald содержат структурированные поля. Полный список полей текущего журнала:

```bash
journalctl --fields
```

**Важные поля для повседневного использования:**

| Поле | Описание | Пример использования |
| :--- | :--- | :--- |
| `_SYSTEMD_UNIT` | Имя юнита systemd. | `journalctl -u nginx.service` |
| `_PID` | Идентификатор процесса. | `journalctl _PID=1234` |
| `_UID` | Идентификатор пользователя. | `journalctl _UID=1000` |
| `_COMM` | Короткое имя исполняемого файла. | `journalctl _COMM=sshd` |
| `_EXE` | Полный путь к исполняемому файлу. | `journalctl _EXE=/usr/sbin/sshd` |
| `SYSLOG_IDENTIFIER` | Идентификатор, используемый syslog (часто совпадает с именем сервиса). | `journalctl SYSLOG_IDENTIFIER=rsyslogd` |
| `_TRANSPORT` | Метод доставки лога (`journal`, `syslog`, `driver`, `stdout`, `kernel`). | `journalctl _TRANSPORT=journal` |
| `_HOSTNAME` | Имя хоста, отправившего лог. | `journalctl _HOSTNAME=web01` |
| `PRIORITY` | Уровень важности (0–7). | `journalctl -p err` |

> **Примечание:** Полную таблицу приоритетов и метаданных см. в [journalctl: Обзор и концепции](./journalctl_overview.md).

## Практические сценарии

### Базовая навигация

```bash
# Просмотр логов текущей загрузки (от начала)
journalctl -b

# Просмотр в обратном порядке (самые свежие сверху)
journalctl -r

# Последние 100 записей и переход в режим ожидания новых
journalctl -n 100 -f
```

### Фильтрация по времени

`journalctl` поддерживает гибкий синтаксис времени (ISO 8601 и относительные термины).

```bash
# Относительные интервалы
journalctl --since "1h ago"
journalctl --since "yesterday"
journalctl --since "2 days ago" --until "1 hour ago"

# Конкретные даты
journalctl --since "2024-05-01 12:00:00" --until "2024-05-01 13:00:00"

# Работа с UTC (игнорируя локальный часовой пояс)
journalctl --since "08:00" --utc

# Поиск событий с точностью до секунды
journalctl --since "2024-05-01 12:00:00" --until "2024-05-01 12:00:10" -u nginx
```

> **Важно:** При работе с терабайтными архивами всегда указывайте `--since`, чтобы избежать полного сканирования базы на диске.

### Фильтрация по юнитам, полям и маскам

```bash
# Конкретный сервис
journalctl -u nginx.service

# Несколько сервисов (логика ИЛИ)
journalctl -u nginx -u php-fpm

# Использование масок (Wildcards)
journalctl -u "ceph-*"

# Фильтрация по PID
journalctl _PID=1 -n 20

# Фильтрация по исполняемому файлу
journalctl _EXE=/usr/sbin/sshd

# Фильтрация по пользователю
journalctl _UID=1000 --since today

# По транспорту (только прямые записи journald, без syslog)
journalctl _TRANSPORT=journal -u myapp
```

### Сложная логика и составные запросы

При указании разных полей они объединяются через **AND**. Одно и то же поле несколько раз — через **OR**. Оператор `+` разделяет наборы фильтров.

```bash
# Ошибки конкретного процесса (AND)
journalctl _PID=1234 -p err

# Логи от двух разных исполняемых файлов (OR)
journalctl /usr/bin/sshd /usr/bin/sudo

# Сложный запрос: (юнит nginx И приоритет err) ИЛИ (юнит sshd И приоритет notice)
journalctl -u nginx.service -p err + -u sshd.service -p notice

# Ошибки двух сервисов за последний час
journalctl --since "1 hour ago" -p err -u nginx -u php-fpm
```

### Логи ядра и загрузки

```bash
# Только сообщения ядра (аналог dmesg)
journalctl -k

# Сообщения ядра за прошлую загрузку
journalctl -k -b -1

# Список всех доступных в архиве загрузок
journalctl --list-boots

# Только ошибки ядра
journalctl -k -p err --since today

# Сравнение ядра между двумя загрузками
diff <(journalctl -k -b -1 --no-pager) <(journalctl -k -b -2 --no-pager)
```

### Анализ сбоев сервисов

```bash
# Последние ошибки сервиса
journalctl -u nginx.service -p err -n 50

# Все сбои с момента последней загрузки
journalctl -u nginx.service --since today -p err

# Поиск сообщений о дампе памяти (coredump)
journalctl -u nginx.service -g "core dumped|segfault|signal"

# Анализ зависимостей и ordering cycles
journalctl -b | grep "ordering cycle"

# Тайминг старта сервиса (совместно с systemd-analyze)
systemd-analyze critical-chain nginx.service
journalctl -u nginx.service -b --no-pager | grep -E "Started|Reached|Failed|Timeout"
```

### Анализ загрузки системы

```bash
# Все ошибки и критические сообщения текущей загрузки
journalctl -b -p err --no-pager

# Логи конкретного failed-юнита
journalctl -u <failed-unit>.service -b -n 100 --no-pager

# Поиск сообщений о зависших юнитах
journalctl -b | grep "dependencies"

# Время достижения целевых состояний (targets)
journalctl -b --utc | grep "Reached target"

# Проверка успешной синхронизации времени
journalctl -u systemd-timesyncd | grep "Synchronized to"
```

### Безопасность и аудит

```bash
# Все неудачные попытки входа по SSH
journalctl -u sshd --since today | grep "Failed password"

# Успешные входы по SSH
journalctl -u sshd --since today | grep "Accepted"

# Использование sudo конкретным пользователем
journalctl _COMM=sudo _UID=1000 --since today

# События PAM (аутентификация, смена паролей)
journalctl -u sshd -g "pam_unix|pam_faillock"

# Создание/удаление пользователей
journalctl -u useradd -u userdel -n 20 --no-pager

# Анализ сессий и входов
journalctl -u systemd-logind.service -n 50 --no-pager

# SELinux denials
journalctl -u nginx | grep -i "denied"

# Блокировки fail2ban
journalctl -u fail2ban -n 30 --no-pager
```

### Диагностика производительности и давления ресурсов

```bash
# Сообщения OOM Killer
journalctl -k -g "Out of memory" --no-pager

# Детали процесса, убитого OOM
journalctl -k -g "Killed process" -n 20 --no-pager

# Предупреждения о нехватке памяти
journalctl -b -p warning -g "memory" --no-pager

# Pressure Stall Information (PSI)
journalctl -k -g "Some task" --no-pager

# Загрузка CPU и потоки
journalctl -u myapp -b --no-pager | grep -i "cpu\|thread\|threadpool"
```

### Работа с контейнерами

```bash
# Логи конкретного контейнера через journald (Docker/Podman)
journalctl CONTAINER_NAME=mycontainer -n 50 --no-pager

# Ошибки контейнера
journalctl CONTAINER_NAME=mycontainer -p err -n 20

# Логи Podman
journalctl -u podman -n 20 --no-pager

# Интеграция с systemd-юнитом для контейнера
journalctl -u myapp-container.service -f
```

### Мониторинг в реальном времени

```bash
# Мониторинг ошибок в реальном времени
journalctl -f -p err

# Мониторинг конкретного сервиса
journalctl -u sshd -f --since "1 hour ago"

# Мониторинг нескольких сервисов одновременно
journalctl -u sshd -u fail2ban -f

# Мониторинг с тихой фильтрацией (только warning и выше)
journalctl -f --quiet=warning

# Мониторинг ядра
journalctl -k -f
```

### Автоматизация, парсинг и корреляция

```bash
# Использование курсора для парсинга (гарантия отсутствия пропусков)
journalctl -u myapp -n 10 --show-cursor
# → -- cursor: <uuid>

# Продолжение чтения с последнего курсора
journalctl --after-cursor=<uuid> -u myapp -n 10

# Парсинг JSON через jq (получение только сообщений)
journalctl -u myapp -o json --since "1h ago" | jq -r '.message'

# Статистика по приоритетам
journalctl -u myapp -o json --since yesterday | jq -r '.PRIORITY' | sort | uniq -c

# Поиск последнего重启 сервиса
journalctl -u nginx.service --no-pager | grep -i "start\|stop" | tail -20

# Корреляция событий по request ID (если логируют в MESSAGE)
journalctl -u frontend -u backend --since "5 min ago" | grep "req-12345"
```

### Экспорт и форматирование

```bash
# JSON для обработки в jq или скриптах
journalctl -u nginx -o json --since "1h ago" | jq '._EXE'

# "Красивый" JSON для отладки структуры полей
journalctl -u nginx -o json-pretty -n 5

# Компактный вывод (только текст сообщения)
journalctl -u nginx -o cat -n 100

# Формат с микросекундами для точного тайминга
journalctl -u nginx -o short-precise --since "1h ago"

# Экспорт для архивации
journalctl -u nginx --since yesterday -o export > nginx_logs.journal-export
```

### Диагностика специфических проблем

```bash
# Поиск сообщений о нехватке памяти (OOM Killer)
journalctl -k -g "Out of memory" --no-pager

# Проверка попыток входа по SSH (Accepted/Failed)
journalctl -u ssh -g "Accepted|Failed" --since today

# Логи конкретного пространства имен
journalctl --namespace=app-logs -u custom-service

# Проверка подавления сообщений (Rate Limiting)
journalctl -u systemd-journald --no-pager | grep -i "suppressed"

# Анализ синхронизации времени
journalctl -u systemd-timesyncd -n 20 --no-pager
```

## Типичные ошибки и их решение

### Нет записей в журнале

**Причины:**
- `Storage=volatile` в `journald.conf` — логи хранятся только в RAM.
- Сервис еще не успел записать сообщение после старта.
- Неправильный фильтр (несуществующий unit, PID, etc.).
- Логи были удалены ротацией.

**Решение:**
```bash
# Проверить режим хранения
systemctl show systemd-journald -p Storage
# → Storage=persistent

# Проверить, что сервис работает
systemctl status myapp
journalctl -u myapp -n 5 --no-pager
```

### Permission denied

**Причина:** Текущий пользователь не состоит в группе `systemd-journal` (или `adm`, `wheel` на RHEL).

**Решение:**
```bash
# Проверить группы
groups

# Добавить в systemd-journal
sudo usermod -aG systemd-journal $USER
# Требуется перелогин
```

### Журнал поврежден

**Симптомы:** `journalctl --verify` выводит ошибки, `--vacuum` не помогает.

**Решение:**
```bash
# Ротация активных файлов
sudo journalctl --rotate

# Удаление всех архивов (включая битые)
sudo journalctl --vacuum-time=1s

# Если не помогло — ручное удаление
sudo rm -rf /var/log/journal/*/*.journal~
sudo systemctl restart systemd-journald
```

### Логи исчезают после перезагрузки

**Причина:** Используется энергозависимое хранение (`/run/log/journal`).

**Решение:**
```bash
# Создать постоянное хранилище
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo systemctl restart systemd-journald
```

### Дублирующиеся сообщения отсутствуют (Rate Limiting)

**Симптом:** В выводе нет ожидаемых записей, но сервис работает и генерирует логи.

**Диагностика:**
```bash
journalctl -u systemd-journald --no-pager | grep -i "suppressed"
# → systemd-journald: Suppressed 1000 messages from /user.slice/...
```

**Решение:** Увеличить лимиты в `/etc/systemd/journald.conf`:
```ini
[Journal]
RateLimitIntervalSec=30s
RateLimitBurst=10000
```
И перезапустить `systemd-journald`.

### Высокое потребление диска журналами

**Диагностика:**
```bash
# Общий объем
journalctl --disk-usage

# Поиск крупнейших файлов
sudo du -sh /var/log/journal/* | sort -rh
```

**Решение:**
```bash
# Немедленная очистка
sudo journalctl --rotate
sudo journalctl --vacuum-size=500M

# Настройка автоматической ротации (journald.conf)
sudo nano /etc/systemd/journald.conf
# SystemMaxUse=500M
# MaxRetentionSec=1week
```

### Логи сервиса не отображаются

**Причины:**
- Сервис не использует journald (пишет напрямую в файл).
- `StandardOutput=null` или `StandardError=null` в unit-файле.
- Сервис запущен до инициализации journald (редко).

**Решение:**
```bash
# Проверить, куда пишет сервис
systemctl show myapp -p StandardOutput -p StandardError

# Проверить, есть ли записи в обычном syslog
sudo tail -f /var/log/syslog | grep myapp
```

## Рекомендации и лучшие практики

### В скриптах и автоматизации

- **Всегда используйте `--no-pager`** при перенаправлении вывода или использовании в пайпах:
  ```bash
  journalctl --no-pager | grep "error"
  ```
- **Предпочитайте фильтры по метаданным** (`-u`, `-p`, `--since`, `_PID=`) текстовому поиску (`-g`). Фильтры по метаданным используют бинарные индексы и работают на порядки быстрее.
- **Ограничивайте временной диапазон** через `--since` и `--until` при работе с большими архивами. Это предотвращает чтение терабайт данных с диска.
- **Используйте `--quiet`** в мониторинговых скриптах, чтобы снизить объем обрабатываемых данных:
  ```bash
  journalctl -u myapp -f --quiet=warning
  ```
- **Для парсинга используйте `--output=json`** и `jq` вместо `grep` и `awk`. JSON формат не зависит от раскраски терминала и длины строк.
- **Используйте курсоры (`--show-cursor` / `--after-cursor`)** в системах сбора логов (SIEM, ELK, Loki) для гарантии отсутствия пропусков при перезапуске сборщика.

### При планировании емкости

- Периодически проверяйте объем журналов: `journalctl --disk-usage`.
- Настраивайте автоматическую ротацию через `journald.conf` (`SystemMaxUse`, `MaxRetentionSec`).
- Для production-систем рекомендуется `SystemMaxUse=1G` или меньше, в зависимости от доступного места.
- Мониторьте появление сообщений `Suppressed` от `systemd-journald` — это признак исчерпания лимитов Rate Limiting.

### Безопасность

- Включите `Seal=yes` в `journald.conf` для защиты от несанкционированного изменения записей.
- Периодически выполняйте проверку целостности: `journalctl --verify`.
- Не храните чувствительные данные (пароли, токены) в полях `MESSAGE` — они записываются в открытом виде.
- Ограничьте доступ к системным логам: только члены групп `systemd-journal`, `adm`, `wheel` должны иметь возможность читать `journalctl` без ограничений.

### Мониторинг и оповещения

- Для алертинга используйте приоритет (`-p err` или `-p warning`) вместо текстового поиска. Это снижает количество ложных срабатываний.
- Коррелируйте события по `_BOOT_ID` при анализе инцидентов, чтобы отличить текущую проблему от исторической.
- Для проверки доступности сервиса комбинируйте `systemctl is-active` с `journalctl -u <service> -p err --since "5 min ago"`.

## Ограничения и особенности работы

- **Энергозависимое хранение по умолчанию:** На свежеустановленных системах без `/var/log/journal` логи хранятся в RAM и теряются после перезагрузки. Это частая причина «исчезновения» логов на новых серверах.
- **Отсутствие `_SYSTEMD_UNIT`:** Процессы, не запущенные через systemd (например, напрямую из cron или shell), могут не иметь поля `_SYSTEMD_UNIT`. Вместо него используйте `_COMM` или `_EXE`.
- **Регистр в `--grep`:** По умолчанию `--grep` (`-g`) чувствителен к регистру. Используйте `--grep-case-sensitive=false` для нечувствительного поиска.
- **`--output-fields` работает не со всеми форматами:** Параметр поддерживается только для форматов `short`, `short-precise`, `short-iso`, `verbose`.
- **Архивные загрузки:** `journalctl -b -1` возвращает логи предыдущей загрузки только если они еще не удалены ротацией. Для очень старых загрузок используйте `--list-boots` для проверки доступности.
- **Пользовательские сервисы:** Флаг `--user` видит логи только тех сервисов, которые были запущены в текущей сессии пользователя. Для сервисов, которые должны работать без входа пользователя, включите lingering:
  ```bash
  loginctl enable-linger <username>
  ```
- **Бинарные данные в полях:** Некоторые поля (например, `_CMDLINE`) могут содержать непечатаемые символы. При парсинге JSON учитывайте, что значения могут быть base64-encoded.
- **Ограничение частоты записи (Rate Limiting):** journald по умолчанию подавляет дублирующиеся сообщения. Если важные логи отсутствуют, проверьте настройки `RateLimitIntervalSec` и `RateLimitBurst` в `journald.conf`.
- **Версия systemd:** Некоторые функции (например, `--namespace`, `--output-fields`) доступны только в systemd 245+. Проверяйте версию:
  ```bash
  journalctl --version
  ```

## Дополнительная информация

### Структурированное логирование

Для приложений, которые должны отправлять структурированные логи с пользовательскими полями (REQUEST_ID, TRACE_ID и др.), см. [Структурированное логирование приложений в journald](./journalctl_structured_logging.md).

### Производительность и оптимизация

1. **Индексы:** Всегда предпочитайте фильтры по метаданным (`-u`, `-p`, `_PID`, `_UID`, `_COMM`) текстовому поиску (`-g`).
2. **Ограничение выборки:** При работе с терабайтными архивами всегда указывайте `--since`, чтобы избежать чтения всей базы с диска.
3. **Курсоры для SIEM:** При написании парсеров используйте `--show-cursor` и `--after-cursor`, чтобы гарантировать отсутствие пропусков при перезапуске сборщика.
4. **Форматы:** Для скриптов используйте `--output=cat` (минимальные накладные расходы) или `--output=json` (надежный парсинг). Избегайте `--output=short-precise` в автоматизации — он содержит нестандартные символы.
5. **Сжатие:** По умолчанию файлы журнала сжимаются (LZ4 или XZ). Это экономит место на диске, но может немного замедлять доступ при чтении очень старых архивов.

Подробнее о производительности и масштабировании: [Производительность и масштабирование journalctl](./journalctl_performance.md).

### Интеграция с другими инструментами

```bash
# Поиск по шаблону (быстрее, чем journalctl -g, если логов много)
journalctl -b --no-pager | grep "error"

# Экспорт в файл для передачи на анализ
journalctl -b > system_logs.txt

# Комбинация с awk для статистики
journalctl --since "1h ago" -o cat | awk '{print $0}' | sort | uniq -c | sort -rn | head -20

# Интеграция с less для интерактивного просмотра с нумерацией
journalctl -u sshd -n 1000 --no-pager | less -N
```

### См. также

- [journalctl: Обзор и концепции](./journalctl_overview.md)
- [Управление хранением и ротацией](./journalctl_management.md)
- [Структурированное логирование приложений в journald](./journalctl_structured_logging.md)
- [Расследование инцидентов через journalctl](./journalctl_incident_response.md)
- [Конфигурация journald](../../SystemAdministration/Logging/journald.md)
