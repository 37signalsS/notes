# Мониторинг событий файловой системы — inotify

## Определения

- **inotify (inode notify):** Подсистема ядра Linux, предоставляющая программный интерфейс (API) для отслеживания событий файловой системы в реальном времени на уровне отдельных inode. Позволяет приложениям подписываться на уведомления об изменениях в конкретных файлах или директориях.
- **fanotify:** Более современный и масштабируемый интерфейс мониторинга. Предназначен для системных сервисов (антивирусы, индексаторы). Поддерживает рекурсивное отслеживание всей точки монтирования, перехват событий с возможностью блокировки (Allow/Deny) и идентификацию процесса (PID), совершившего действие.
- **Событие (Event):** Дискретное действие над объектом ФС (открытие, чтение, запись, удаление, перемещение).
- **Watch Descriptor (WD):** Целочисленный идентификатор, возвращаемый ядром при добавлении наблюдения за объектом. Аналог файлового дескриптора, но для inotify.
- **Watch Instance:** Экземпляр inotify, созданный через `inotify_init1()`. Каждый экземпляр имеет собственную очередь событий и набор watch descriptors.

## Основные концепции

### Механизм работы

inotify функционирует на уровне **VFS (Virtual File System)**. Приложение создает экземпляр inotify (через системный вызов `inotify_init1`) и добавляет в него «дескрипторы наблюдения» (**watch descriptors**) для интересующих объектов.

**Критическое ограничение:** inotify **не является рекурсивным**. Для отслеживания дерева директорий приложение должно явно добавить каждый подкаталог в список наблюдения. Это создает «состояние гонки» (race condition) при создании новых папок: файлы внутри новой папки могут быть созданы до того, как приложение успеет добавить на неё watch descriptor.

### Флаги инициализации (`inotify_init1`)

| Флаг | Назначение |
| :--- | :--- |
| **`IN_CLOEXEC`** | Автоматически закрыть FD при успешном `execve()`. Стандарт для демонов. |
| **`IN_NONBLOCK`** | Вернуть `-EAGAIN` вместо блокировки при чтении из пустой очереди. Требуется для event-loop (epoll/select). |

### Типы событий (Event Masks)

| Константа | Описание |
| :--- | :--- |
| **`IN_ACCESS`** | Файл был прочитан (доступ). |
| **`IN_MODIFY`** | Файл был изменен (запись). |
| **`IN_ATTRIB`** | Изменены метаданные (права, атрибуты, время, расширенные атрибуты). |
| **`IN_CLOSE_WRITE`** | Файл, открытый на запись, был закрыт (момент фиксации изменений). |
| **`IN_CLOSE_NOWRITE`** | Файл, открытый без записи, был закрыт. |
| **`IN_OPEN`** | Файл был открыт. |
| **`IN_MOVED_FROM`** | Файл/директория перемещены *из* наблюдаемой папки. |
| **`IN_MOVED_TO`** | Файл/директория перемещены *в* наблюдаемую папку. |
| **`IN_CREATE`** | Создан файл или директория в наблюдаемой папке. |
| **`IN_DELETE`** | Файл или директория удалены из наблюдаемой папки. |
| **`IN_DELETE_SELF`** | Сам наблюдаемый объект был удален. |
| **`IN_MOVE_SELF`** | Сам наблюдаемый объект был перемещен. |

**Дополнительные флаги:**
| Константа | Описание |
| :--- | :--- |
| **`IN_DONT_FOLLOW`** | Не разрешать символические ссылки. Важно для безопасности. |
| **`IN_ONESHOT`** | Отслеживать только первое событие, после чего автоматически удалить watch. |
| **`IN_ALL_EVENTS`** | Маска всех вышеперечисленных событий. |

**Механизм Cookie:** При перемещении (`rename`) генерируются два события: `IN_MOVED_FROM` и `IN_MOVED_TO`. Они содержат уникальный 32-битный **cookie**. Если приложение видит два события с одинаковым cookie, оно может сопоставить их как единую операцию перемещения.

### Системные лимиты (sysctl)

Для предотвращения исчерпания ресурсов ядра (каждый watch занимает память) установлены лимиты:

| Параметр | Описание | Значение (типичное) |
| :--- | :--- | :--- |
| **`fs.inotify.max_user_watches`** | Макс. кол-во объектов (папок/файлов) на пользователя. | 8192–65536 |
| **`fs.inotify.max_user_instances`** | Макс. кол-во очередей (экземпляров) на пользователя. | 128 |
| **`fs.inotify.max_queued_events`** | Макс. кол-во событий в одной очереди. | 16384 |

**Просмотр и изменение:**
```bash
# Текущие значения
sysctl fs.inotify

# Временное увеличение (для тяжелых IDE, например, VS Code или IntelliJ)
sudo sysctl -w fs.inotify.max_user_watches=524288

# Постоянное применение в /etc/sysctl.d/99-inotify.conf
# fs.inotify.max_user_watches=524288
```

### Внутренняя архитектура

#### Потребление памяти

Каждый watch descriptor занимает в ядре около **1 КБ** памяти (структура `inotify_watch` + кэш имени). Для мониторинга дерева из 100 000 файлов требуется ~100 МБ памяти ядра.

#### Очередь событий

События помещаются в очередь экземпляра inotify. Если приложение не читает события быстрее, чем они генерируются, очередь заполняется и генерируется событие `IN_Q_OVERFLOW`. При этом **часть событий теряется безвозвратно**. Увеличение `max_queued_events` дает лишь буфер, но не решает проблему медленного потребителя.

#### Рекурсивный мониторинг

Поскольку inotify не рекурсивен, типичный паттерн — обход директории и добавление watch на каждый подкаталог. При создании новой директории внутри наблюдаемой нужно:
1. Обработать событие `IN_CREATE | IN_ISDIR`
2. Добавить watch на новую директорию
3. Рекурсивно обойти её содержимое

### inotify в контейнерах

**Важно:** inotify работает в рамках namespace контейнера. Watch descriptors, созданные внутри контейнера, видны только процессам в этом namespace. Это означает:

- Лимиты `fs.inotify.*` применяются **к каждому контейнеру отдельно** (если не共用 user namespace).
- Если приложение в контейнере отслеживает большой volume, лимиты внутри контейнера могут быть исчерпаны независимо от хоста.
- Docker Compose Watch Mode потребляет watches на **хосте** для отслеживания путей.

**Рекомендация:** Для контейнеров с тяжелым мониторингом ФС явно увеличивайте лимиты через `sysctl` в runtime или в DaemonSet (Kubernetes).

### Сравнение: inotify vs fanotify (2026+)

| Критерий | inotify | fanotify (Modern) |
| :--- | :--- | :--- |
| **Область действия** | Конкретные файлы/папки. | Точки монтирования / Вся ФС. |
| **Рекурсия** | Требует ручного добавления всех подпапок. | **Нативная** для всей иерархии. |
| **Контроль доступа** | Только уведомление (постфактум). | **Блокировка** (Allow/Deny до совершения). |
| **Сложность** | Простой, доступен без root. | Требует `CAP_SYS_ADMIN`. |
| **Производительность** | Накладные расходы растут с числом watches. | Постоянная (масштабируется по объему событий). |

## Инструментарий

Пакет **inotify-tools** предоставляет CLI-интерфейс к API:
- **`inotifywait`:** Ожидает наступления событий. Идеально для автоматизации.
- **`inotifywatch`:** Собирает статистику обращений за период времени.

**Программные binding:**
- **Python:** `watchdog` (кросс-платформенный, использует inotify на Linux), `pyinotify` (чистый inotify).
- **Go:** `github.com/hanwen/go-fuse/v2` включает inotify-совместимые utilities, `github.com/fsnotify/fsnotify` — кроссплатформенный.
- **Rust:** `notify` crate.

## Практические сценарии

### 1. Автоматическая перезагрузка Nginx при изменении конфига

```bash
#!/bin/bash
TARGET="/etc/nginx/nginx.conf"

while true; do
    # -e close_write: гарантирует, что файл уже сохранен на диск
    inotifywait -e close_write "$TARGET"
    nginx -t && systemctl reload nginx
done
```

### 2. Рекурсивный мониторинг директории с логами

Для обработки событий в конвейере используйте флаг `--monitor` (`-m`).
```bash
# Отслеживание новых файлов в /var/log/app рекурсивно
inotifywait -m -r -e create --format '%w%f' /var/log/app | while read NEW_FILE
do
    echo "Обнаружен новый лог-файл: $NEW_FILE"
done
```

### 3. Форматированный аудит активности

```bash
# Вывод: [Время] [Событие] [Путь]
inotifywait -m -r --timefmt '%H:%M:%S' --format '[%T] %e %w%f' /home/user/data
```

### 4. Мониторинг логов fail2ban (Debouncing)

Fail2ban использует `pyinotify` для отслеживания логов в реальном времени. Для custom-реализации с подавлением шума:

```bash
# Ожидаем закрытия файла после записи, с debounce 1 секунда
inotifywait -m -e close_write --format '%w%f' /var/log/fail2ban.log | \
while read -r file; do
    sleep 1  # debounce: ждем завершения записи
    tail -n 20 "$file" | grep -i "ban\|unban" && \
    notify-send "fail2ban" "New ban event detected"
done
```

**См. также:** [fail2ban](../Security/Tools/fail2ban.md) — backend `pyinotify` для мониторинга логов.

### 5. systemd Path Units — декларативный триггер сервисов

Альтернатива скриптам с `inotifywait` — нативные `.path` юниты systemd. Подходит для production, обеспечивает авто-перезапуск и логирование через journald.

```ini
# /etc/systemd/system/config-watcher.path
[Unit]
Description=Watch /etc/myapp/config.yaml

[Path]
PathModified=/etc/myapp/config.yaml

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/config-reloader.service
[Unit]
Description=Reload myapp configuration

[Service]
Type=oneshot
ExecStart=/usr/bin/kill -HUP $(cat /run/myapp.pid)
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now config-watcher.path
```

**См. также:** [Обзор юнитов systemd](../Core/systemd/systemd_units_overview.md) — типы юнитов и их взаимодействие.

### 6. Hot Reload в Kubernetes (ConfigMap + inotify)

Kubernetes обновляет тома ConfigMap через атомарные симлинки (`..data` → `..<timestamp>`). Приложения с поддержкой inotify (Nginx, Prometheus, Envoy) автоматически подхватывают изменения.

**Критическое ограничение:** Kubelet кэширует inotify-события на 60–90 секунд. Для приложений, требующих мгновенного обновления, используйте sidecar-reloader (Stakater Reloader) или HTTP `/-/reload` эндпоинт.

**Диагностика:**
```bash
# Проверить, что kubelet видит изменения
kubectl get events --field-selector reason=SuccessfulMount --watch

# Проверить симлинки в томе
kubectl exec -it <pod> -- ls -la /etc/config
# → ..data -> ..20240101120000
# → ..20240101120000 -> ... (актуальные данные)
```

**См. также:**
- [ConfigMap: Обновление и Rollout](../../Kubernetes/Base/ConfigMap/update_and_rollout.md) — механизмы Hot Reload.
- [ConfigMap: Best Practices](../../Kubernetes/Base/ConfigMap/best_practices.md) — ограничения и паттерны.

### 7. Docker Compose Watch Mode

Docker Compose v2 использует inotify на хосте для отслеживания изменений файлов в режиме `watch`. Каждый отслеживаемый путь потребляет FD и память.

```yaml
# compose.yml
services:
  app:
    build: .
    develop:
      watch:
        - path: ./src
          action: sync
        - path: ./Dockerfile
          action: rebuild
```

**См. также:** [Docker Compose Watch Mode](../../Docker/Docker_compose/docker_compose_watch_mode.md) — ресурсные ограничения и настройка.

### 8. Триггер бэкапа по изменению файлов

```bash
WATCH_DIR="/srv/important-data"
BACKUP_CMD="/usr/local/bin/incremental-backup.sh"

inotifywait -m -r -e close_write --format '%w%f' "$WATCH_DIR" | \
while read -r file; do
    # Исключаем временные файлы
    [[ "$file" == *.tmp ]] && continue
    # Debounce: запускаем бэкап не чаще 1 раза в 5 секунд
    $BACKUP_CMD "$file"
done
```

### 9. CI/CD: деплой артефактов по появлению файла

```bash
ARTIFACT_DIR="/opt/ci-artifacts"
DEPLOY_SCRIPT="/usr/local/bin/deploy.sh"

inotifywait -m -e create --format '%w%f' "$ARTIFACT_DIR" | \
while read -r artifact; do
    [[ "$artifact" != *.tar.gz ]] && continue
    echo "$(date -Iseconds) Deploying $artifact"
    $DEPLOY_SCRIPT "$artifact" || \
    echo "$(date -Iseconds) ERROR: deploy failed" | \
    mail -s "Deploy failed" ops@example.com
done
```

### 10. Python: пользовательский watchdog с `watchdog`

```python
# pip install watchdog
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time

class ReloadHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.yaml'):
            print(f"Config changed: {event.src_path}")
            # reload_config()

observer = Observer()
observer.schedule(ReloadHandler(), path='/etc/myapp', recursive=False)
observer.start()
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    observer.stop()
observer.join()
```

## Диагностика и устранение неполадок

### Утечка inotify-дескрипторов

Приложение создает watcher'ы, но не закрывает их. Типичные виновники: IDE, файловые менеджеры, мониторинговые агенты.

```bash
# Проверка количества inotify FD процесса
ls /proc/<PID>/fd | grep inotify | wc -l

# Глобальный лимит inotify
cat /proc/sys/fs/inotify/max_user_watches
cat /proc/sys/fs/inotify/max_user_instances

# Поиск процессов с наибольшим количеством inotify FD
sudo lsof | grep inotify | awk '{print $1}' | sort | uniq -c | sort -rn | head
```

**См. также:** [Диагностика утечек FD](../Diagnostics/Troubleshooting/troubleshooting_file_descriptor_leaks.md) — классификация дескрипторов и дифференциальная диагностика.

### IN_Q_OVERFLOW — переполнение очереди

```bash
# Мониторинг переполнений в реальном времени
sudo perf trace -e sys_inotify_* -a --duration=60 2>/dev/null | \
grep IN_Q_OVERFLOW

# Или через auditd (если настроен)
ausearch -m SYSCALL -sc inotify | grep overflow
```

**Решение:**
1. Оптимизировать потребителя: обрабатывать события пакетами, а не по одному.
2. Увеличить `max_queued_events` (временное облегчение).
3. Добавить debounce/deduplication на стороне приложения.

### Сетевые ФС (NFS/SMB)

inotify **не работает** надежно на сетевых ресурсах. Требуется классический опрос (polling).

### Событие `IN_IGNORED`

Возникает, когда объект удален или ФС размонтирована. inotify автоматически удаляет этот watch.

### Ошибка `No space left on device`

Чаще всего означает исчерпание лимита `max_user_watches`. Проверьте `sysctl`.

## Мониторинг и алертинг

### Метрики для Prometheus (node_exporter)

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `node_filefd_allocated` | Общее количество открытых FD | > 80% от `fs.file-max` |
| `node_processes` | Количество процессов | Рост без причины |
| `node_systemd_units` | Количество юнитов | Резкий рост |

Для inotify-специфичных метрик используйте **custom exporter** или blackbox-проверки:

```bash
# Проверка текущего использования watches
sudo lsof | grep inotify | wc -l

# Сравнение с лимитом
echo "scale=2; $(sudo lsof | grep inotify | wc -l) / $(cat /proc/sys/fs/inotify/max_user_watches) * 100" | bc
# → процент использования
```

### Логи ядра

```bash
# Все события FUSE/ввода-вывода за последний час
journalctl --since "1 hour ago" | grep -E "inotify|IN_Q_OVERFLOW"

# Потенциальные проблемы с лимитами
dmesg | grep -i "inotify"
```

## Безопасность

### Принципы безопасного использования

1. **Принцип наименьших привилегий:** Монтируйте ФС от имени отдельного сервисного пользователя. Используйте `inotifywait` из scripts, а не ручной запуск от root.
2. **Ограничение `IN_DONT_FOLLOW`:** Используйте этот флаг при работе с символьными ссылками во внешних директориях, чтобы избежать следования за ссылками за пределы наблюдаемой области.
3. **Права на точку монтирования:** Устанавливайте `chmod 700` на каталог мониторинга, если данные используются одним пользователем.
4. **SELinux / AppArmor:** Применяйте политики Mandatory Access Control к скриптам, выполняющим `inotifywait` в критичных директориях.

### Векторы атак

- **Утечка информации через inotify:** Злоумышленник с доступом к пользовательскому процессу может использовать inotify для наблюдения за файлами, к которым у него нет прямого доступа (например, `/etc/shadow` через временный файл). Ограничьте доступ к sensitive директориям.
- **DoS через исчерпание watches:** Если злоумышленник может создавать файлы в наблюдаемой директории, он может исчерпить лимит `max_user_watches`. Используйте квоты ФС и ограничьте права на запись.
- **Race condition:** Новые подкаталоги не наблюдаются автоматически. Приложение, не добавляющее watch на новые директории, пропускает события — это может быть использовано для обхода аудита.

## Дополнительная информация

### Связанные темы
- [Параметры ядра (sysctl)](../Core/kernel/sysctl.md) — управление глобальными лимитами.
- [Аудит системы (auditd)](../SystemAdministration/Logging/auditd.md) — для безопасности (кто именно изменил файл).
- [Обзор юнитов systemd](../Core/systemd/systemd_units_overview.md) — `.path` юниты как альтернатива.
- [Диагностика утечек FD (inotify)](../Diagnostics/Troubleshooting/troubleshooting_file_descriptor_leaks.md) — инструменты анализа.
- [Тюнинг ядра для Kubernetes (inotify)](../../Kubernetes/Troubleshooting/Common_Errors/NodeUnavailability/kernel_tuning.md) — сценарий переполнения watches.
- [ConfigMap: Hot Reload](../../Kubernetes/Base/ConfigMap/update_and_rollout.md) — использование inotify в K8s.
- [Docker Compose Watch Mode](../../Docker/Docker_compose/docker_compose_watch_mode.md) — inotify на хосте для разработки.
- [Диагностика открытых файлов (lsof)](../Diagnostics/Processes/lsof.md) — поиск процессов, удерживающих inotify FD.

### Источники и стандарты

- **Официальная документация:** https://github.com/libfuse/libfuse
- **Ядерный модуль:** `Documentation/filesystems/inotify.rst` в исходниках ядра Linux.
