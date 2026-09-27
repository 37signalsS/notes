# Управление хранением и очистка journalctl

## Определения

**`Vacuum` (Очистка)** — процедура удаления архивных (неактивных) файлов журнала для освобождения дискового пространства. Очистка может выполняться по критериям размера, времени или количества файлов. Механизм `vacuum` **никогда** не удаляет активные файлы.

**`Rotation` (Ротация)** — процесс закрытия текущего активного файла журнала и создания нового. Ротация переводит активные записи в разряд архивных, что является необходимым условием для их последующего удаления через `vacuum`. Ротацию может триггерить достижение лимита по размеру (`SystemMaxFileSize`), времени (`MaxFileSec`) или команда `--rotate`.

**`Integrity Check` (Проверка целостности)** — верификация структуры бинарных файлов журнала на предмет повреждений или несанкционированных изменений (при использовании FSS).

**`Forward Secure Sealing` (FSS)** — механизм криптографического подписания журнала, позволяющий гарантировать, что записи не были изменены или удалены после их фиксации.

**`SplitMode`** — параметр конфигурации `journald.conf`, определяющий стратегию распределения логов между файлами:
- `SplitMode=uid` (по умолчанию): создает отдельные файлы для каждого пользователя (`user-<UID>.journal`)
- `SplitMode=machine`: все логи пишутся в единый системный файл
- `SplitMode=none`: аналогично `machine`, но без разделения

**`Compress`** — параметр, контролирующий сжатие архивных файлов журнала. По умолчанию `yes` для файлов больше 512 байт. Используется алгоритм LZ4 (быстрый, низкое сжатие) или XZ (медленное, высокое сжатие) в зависимости от дистрибутива.

## Основные концепции

### Жизненный цикл обслуживания журналов

Эффективное управление хранением требует понимания состояния файлов:

1. **Активные файлы (Active):** Файлы, в которые в данный момент производится запись. Механизм `vacuum` **никогда** не удаляет активные файлы.
2. **Архивные файлы (Archived):** Закрытые файлы, доступные только для чтения. Именно они подлежат очистке.
3. **Перемещенные файлы (Rotated/Moved):** При явной ротации активный файл получает суффикс `~` и становится архивным. Создается новый активный файл без суффикса.

Для гарантированного освобождения места рекомендуется использовать цепочку команд: `sync` (сброс кэша на диск) → `rotate` (архивация активных файлов) → `vacuum` (удаление старых архивов).

### Внутренняя структура файлов журнала

Файлы journald имеют расширение `.journal` и хранятся в следующих locations:

| Тип | Путь | Формат |
|-----|------|--------|
| Активный системный | `/var/log/journal/<machine-id>/system.journal` | Бинарный, записываемый |
| Архивный системный | `/var/log/journal/<machine-id>/system@<hash>.journal` | Бинарный, только чтение |
| Пользовательский | `/var/log/journal/<machine-id>/user-<UID>.journal` | Бинарный |
| Volatile | `/run/log/journal/<machine-id>/*.journal` | tmpfs, теряется при reboot |

**Именование архивных файлов:** При ротации systemd добавляет к имени файла хэш, например `system@c1234567890a.journal`. Это позволяет иметь несколько архивных сессий одновременно.

**Размер файлов:** По умолчанию journald не ограничивает размер одного файла жестко, но триггерит ротацию по времени (`MaxFileSec`) или при заполнении `SystemMaxFileSize`.

### Взаимодействие с файловой системой

journald использует `mmap()` для отображения файлов журнала в память, что обеспечивает высокую производительность при чтении. Однако это имеет последствия для управления:

- **Нельзя удалить активный файл:** journald держит файл открытым через mmap. Удаление в этом случае удалит только запись из директории, но пространство не освободится до закрытия файла (ротации).
- **Vacuum работает с архивными файлами:** Поскольку архивные файлы закрыты, их можно безопасно удалять.
- **Sync записывает кэш на диск:** `journalctl --sync` вызывает `fsync()` для всех открытых файлов журнала.

### Уровни управления

- **Автоматический:** Настраивается через параметры `SystemMaxUse`, `MaxRetentionSec`, `MaxFileSec` и др. в файле `journald.conf`. Демон самостоятельно выполняет ротацию и очистку. Подробнее см. в [Настройка journald](../../SystemAdministration/Logging/journald.md).
- **Ручной (Оперативный):** Использование утилиты `journalctl` для немедленного решения проблем с дисковым пространством или диагностики повреждений.

### Особенности SplitMode и их влияние на хранение

При `SplitMode=uid` (по умолчанию в большинстве дистрибутивах) логи распределяются по пользователям. Это имеет практические последствия:

- **Много мелких файлов:** Если на системе много пользователей или сервисов, создается множество небольших файлов `user-<UID>.journal`.
- **Ротация по каждому пользователю:** Логи каждого пользователя ротируются независимо, что может привести к большому общему количеству файлов.
- **Vacuum затрагивает все:** `--vacuum-files` считает все файлы в директории, включая пользовательские.
- **Monitoring:** `journalctl --disk-usage` показывает суммарный размер по всем файлам.

## Практические сценарии

### Анализ использования диска

```bash
# Суммарный объем всех файлов журнала (система + пользователи)
journalctl --disk-usage

# Подробный анализ по файлам
sudo du -sh /var/log/journal/* | sort -rh

# Поиск ошибок самого демона journald
journalctl -u systemd-journald -n 50

# Проверка количества файлов (предупреждение если > 1000)
ls -la /var/log/journal/<machine-id>/*.journal* | wc -l
```

### Ручная очистка (Vacuuming)

Команды `vacuum` удаляют только архивные файлы.

```bash
# 1. Сброс данных и архивация текущего лога
sudo journalctl --sync --rotate

# 2. Очистка по размеру (оставить не более 500МБ)
sudo journalctl --vacuum-size=500M

# 3. Очистка по времени (оставить логи за последние 7 дней)
sudo journalctl --vacuum-time=7d

# 4. Очистка по количеству файлов (оставить 5 последних архивов)
sudo journalctl --vacuum-files=5
```

**Валидация результата:**
```bash
# Проверить, что место освободилось
journalctl --disk-usage

# Убедиться, что старые архивы удалены
ls -lht /var/log/journal/<machine-id>/*.journal*
```

### Техническое обслуживание базы данных

#### Синхронизация и ротация
Необходимы перед созданием бэкапов или при переносе логов.

```bash
# Принудительная запись всех метаданных на диск
sudo journalctl --sync

# Немедленное закрытие текущих файлов
sudo journalctl --rotate
```

#### Проверка и исправление повреждений
Бинарные файлы могут быть повреждены при внезапном отключении питания.

```bash
# Проверка всех файлов на ошибки структуры
sudo journalctl --verify

# Криптографическая проверка (требуется Verification Key)
sudo journalctl --verify --verify-key=<your-fss-key>
```

**Если обнаружены поврежденные (corrupted) файлы:**
1. Выполните ротацию: `journalctl --rotate`.
2. Попробуйте выполнить очистку: `journalctl --vacuum-time=1s` (это удалит все архивы, включая битые).
3. Если очистка не помогает, удалите файлы вручную: `sudo rm -rf /var/log/journal/<machine-id>/*.journal~`.
4. Перезапустите `systemd-journald`: `sudo systemctl restart systemd-journald`.

#### Перенос логов из RAM на диск (Flush)
Используется, если `/var/log/journal` был создан после старта системы.

```bash
# Перенос накопленных данных из /run/log/journal в /var/log/journal
sudo journalctl --flush
```

#### Проверка режима хранения
```bash
# Проверить текущий режим
ls -ld /var/log/journal 2>/dev/null && echo "Persistent" || echo "Volatile"

# Проверить статус systemd-journald
systemctl show systemd-journald --property=Storage
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

### Автоматизация и мониторинг

#### Скрипт проверки свободного места

```bash
#!/bin/bash
# check-journal-disk.sh
# Проверка свободного места на разделе с логами

THRESHOLD=90
PARTITION=$(df /var/log --output=target | tail -1)
USAGE=$(df /var/log --output=pcent | tail -1 | tr -d '%')

if [ "$USAGE" -gt "$THRESHOLD" ]; then
    echo "WARNING: Journal partition usage is ${USAGE}%"
    
    # Автоматическая очистка
    sudo journalctl --sync --rotate
    sudo journalctl --vacuum-size=1G
    
    # Отправка алерта (пример для syslog)
    logger -p local0.crit "Journal disk usage critical: ${USAGE}%. Vacuum executed."
fi
```

Интеграция с `systemd`:

```ini
# /etc/systemd/system/journal-disk-check.service
[Unit]
Description=Check journal disk usage

[Service]
Type=oneshot
ExecStart=/usr/local/bin/check-journal-disk.sh

# /etc/systemd/system/journal-disk-check.timer
[Unit]
Description=Run journal disk check daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
# Активация
sudo systemctl enable --now journal-disk-check.timer
```

#### Мониторинг через node_exporter (Prometheus)

Для интеграции с Prometheus можно использовать текстовые файлы с метриками:

```bash
#!/bin/bash
# journal-metrics.sh
# Генерация метрик для Prometheus node_exporter textfile collector

METRICS_FILE="/var/lib/prometheus/node-exporter/journal-metrics.prom"
mkdir -p $(dirname $METRICS_FILE)

# Размер журнала
SIZE=$(journalctl --disk-usage 2>&1 | grep -oP '\d+\.\d+[MG]')

# Количество архивных файлов
FILES=$(ls /var/log/journal/*/*.journal 2>/dev/null | wc -l)

# Статус systemd-journald
STATUS=$(systemctl is-active systemd-journald)

cat > $METRICS_FILE <<EOF
# HELP journal_size_bytes Journal size in bytes
# TYPE journal_size_bytes gauge
journal_size_bytes $(du -sb /var/log/journal 2>/dev/null | cut -f1)
# HELP journal_files_count Number of journal files
# TYPE journal_files_count gauge
journal_files_count $FILES
# HELP journal_service_up Journal service status (1=up, 0=down)
# TYPE journal_service_up gauge
journal_service_up $([ "$STATUS" = "active" ] && echo 1 || echo 0)
EOF
```

### Профилактическое обслуживание (Runbook для SRE)

#### Еженедельные задачи

```bash
# 1. Проверка целостности
sudo journalctl --verify

# 2. Проверка размера и роста
journalctl --disk-usage
# Оценить тренд: compare with last week

# 3. Проверка флага "Suppressed messages"
journalctl -u systemd-journald | grep -i "suppressed"

# 4. Проверка режима хранения
systemctl show systemd-journald --property=Storage
```

#### Ежемесячные задачи

```bash
# 1. Очистка старых архивов (если не настроена автоматическая)
sudo journalctl --vacuum-time=30d

# 2. Проверка конфигурации journald
systemd-analyze cat-config systemd/journald.conf

# 3. Проверка прав доступа
sudo stat -c '%a %U:%G' /var/log/journal

# 4. Аудит размера по юнитам (топ-10 потребителей)
journalctl --disk-usage
journalctl --since "30 days ago" --output=short | \
  awk '{print $NF}' | sort | uniq -c | sort -rn | head -10
```

#### При инциденте "Диск заполнен логами"

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

### Управление через journald.conf (оперативное)

При необходимости быстро изменить параметры без полного редактирования файла:

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

### Перенос журнала с одного диска на другой

```bash
# 1. Остановка сервиса
sudo systemctl stop systemd-journald

# 2. Создание директории на новом диске
sudo mkdir -p /mnt/newdisk/var/log/journal
sudo cp -a /var/log/journal/* /mnt/newdisk/var/log/journal/

# 3. Обновление mount points или symlink
sudo mv /var/log/journal /var/log/journal.bak
sudo ln -s /mnt/newdisk/var/log/journal /var/log/journal

# 4. Запуск сервиса
sudo systemctl start systemd-journald

# 5. Валидация
journalctl --disk-usage
journalctl -n 5
```

## Дополнительная информация

### Производительность при очистке

- **Индексация:** Операция `vacuum` не требует перестроения индексов, так как она оперирует целыми файлами.
- **Блокировки:** Во время выполнения `vacuum` чтение логов не блокируется, однако запись может кратковременно замедлиться при ротации.
- **Сжатие:** Архивные файлы могут быть сжаты (LZ4/XZ). Работа с сжатыми архивами требует дополнительного CPU для декомпрессии при чтении.

### Сигналы journald

| Сигнал | Действие | Примечание |
| :--- | :--- | :--- |
| `SIGUSR1` | Сброс кэша на диск (`--flush`) | Аналог `journalctl --flush` |
| `SIGUSR2` | Перезапись файла идентификатора машины | Редко используется |
| `SIGRTMIN+1` | Принудительная ротация (`--rotate`) | Аналог `journalctl --rotate` |
| `SIGRTMIN+2` | Перезапуск демона | Используется при обновлении |
| `SIGRTMIN+3` | Остановка демона | Graceful shutdown |

### Особенности работы с контейнерами

При использовании драйвера `journald` в Docker:

```bash
# Просмотр логов конкретного контейнера
journalctl CONTAINER_NAME=myapp -n 50

# Проверка размера логов контейнера
journalctl CONTAINER_NAME=myapp --since "7 days ago" --disk-usage

# Очистка старых логов контейнера
journalctl CONTAINER_NAME=myapp --vacuum-time=7d
```

**Важно:** При активном использовании контейнеров количество файлов `.journal` может быстро расти. Рекомендуется настроить `SystemMaxUse` и `MaxRetentionSec`.

### Резервное копирование (Backup)

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

### Ограничения и известные проблемы

1. **Невозможность уменьшения размера активного файла:** Если активный файл уже занял много места, `--vacuum-size` не поможет, пока не будет выполнена ротация.
2. **Полный диск:** При заполнении корневого раздела journald может перестать писать логи. Включите `SystemKeepFree` в `journald.conf` для резервирования места.
3. **Производительность при большом объеме:** При миллионах записей `journalctl --grep` может быть медленным. Используйте фильтрацию по `_SYSTEMD_UNIT` или времени.
4. **Ограничение частоты:** При флуде journald подавляет сообщения. Проверяйте лог `journald` на предмет "Suppressed X messages".
5. **SplitMode=uid и Cinder/Virtuozzo:** В контейнерных средах с изоляцией пользователей `SplitMode=uid` может привести к неожиданному распределению файлов.

### Мониторинг метрик

```bash
# Статус службы
systemctl status systemd-journald

# Конфигурация
systemd-analyze cat-config systemd/journald.conf

# Статистика записи (через journalctl)
journalctl -u systemd-journald --since "1 hour ago" --output=short | \
  grep -E "Started|Stopped|Suppressed|Disk"
```

### Типичные ошибки управления

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Vacuum` удалил не всё | Активный файл слишком велик | Выполните `--rotate` перед `--vacuum`. |
| Ошибка доступа к `/var/log/journal` | Неверные права доступа | Проверьте права: `chown root:systemd-journal /var/log/journal`. |
| Логи не сохраняются после ребута | Режим `Storage=volatile` или нет папки | Проверьте `journald.conf` и наличие `/var/log/journal`. |
| Нет логов пользовательских сервисов | Не включен lingering | `loginctl enable-linger <username>` |
| `Suppressed X messages` | Сработал Rate Limit | Увеличьте `RateLimitBurst` в `journald.conf` |
| Поврежденные файлы после падения | Внезапное отключение питания | `journalctl --rotate && journalctl --vacuum-time=1s` |

### См. также

- [journalctl: Обзор и концепции](./journalctl_overview.md)
- [Практическое использование journalctl](./journalctl_usage.md)
- [Структурированное логирование приложений в journald](./journalctl_structured_logging.md)
- [Расследование инцидентов через journalctl](./journalctl_incident_response.md)
- [Производительность и масштабирование journalctl](./journalctl_performance.md)
- [Конфигурация journald](../../SystemAdministration/Logging/journald.md)
- [Диагностика дискового пространства](../Filesystem/filesystem_and_disk_space_diagnostics.md)
