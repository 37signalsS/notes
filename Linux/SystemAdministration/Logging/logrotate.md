# logrotate: Ротация и сжатие логов

## Определения

**`logrotate`** — стандартная системная утилита Linux (актуальная версия 3.22.0+), предназначенная для автоматизации жизненного цикла файлов журналов. Она выполняет ротацию (переименование), сжатие, удаление старых копий по расписанию или размеру, а также уведомляет приложения о необходимости начать запись в новый файл.

Основная задача инструмента — предотвращение переполнения дискового пространства и обеспечение соответствия политикам хранения данных (Retention Policy).

## Базовые концепции

### Жизненный цикл ротации

При каждом запуске `logrotate` выполняет следующие этапы для каждого совпавшего файла:

1. **Чтение конфигурации:** Загружаются глобальные (`/etc/logrotate.conf`) и локальные (`/etc/logrotate.d/*`) параметры.
2. **Проверка условий:** Утилита проверяет, прошло ли достаточно времени с момента последней ротации (сравнивает с записью в `/var/lib/logrotate/status`) и/или превышен ли размер файла.
3. **Переименование (rename):** Текущий активный файл переименовывается (например, `app.log` → `app.log.1`). Это атомарная операция на уровне ФС.
4. **Создание нового файла:** Если указано `create`, создаётся новый пустой файл с указанными правами и владельцем.
5. **Сжатие:** Если включено `compress`, архивный файл сжимается асинхронно (или синхронно, если не указано `delaycompress`).
6. **Выполнение скриптов:** Запускаются `prerotate`/`postrotate` (или `preremove`).
7. **Очистка:** Удаляются старые архивы сверх `rotate N` или `maxage DAYS`.

### Работа с файловыми дескрипторами и сигналами

После переименования файла приложение продолжает писать в **старый дескриптор** (inode), который теперь указывает на переименованный файл. Новый файл остаётся пустым до получения сигнала.

**Проблема:** Без переоткрытия файла приложение продолжает писать в архив, а новый файл остаётся пустым до следующей ротации.

**Решение:** В `postrotate` отправляется сигнал приложению:
- `SIGHUP` — большинство демонов (nginx, rsyslog)
- `USR1` — Nginx, PostgreSQL
- `USR2` — Some Java apps (нестандартно)

### Алгоритмы сжатия

| Алгоритм | Команда | Степень сжатия | Скорость | Применение |
| :--- | :--- | :--- | :--- | :--- |
| `gzip` | `gzip` | Средняя (~70%) | Высокая | По умолчанию |
| `bzip2` | `bzip2` | Высокая (~80%) | Низкая | Редко, архивы |
| `xz` | `xz` | Очень высокая (~90%) | Очень низкая | Архивирование, не для live-систем |
| `zstd` | `zstd` | Высокая (~85%) | Очень высокая | **Рекомендуется для production** |

Для production-систем с большим объёмом логов используйте `zstd`:
```ini
compresscmd /usr/bin/zstd
compressext .zst
uncompresscmd /usr/bin/unzstd
```

`zstd` даёт сжатие уровня xz со скоростью, близкой к gzip, и поддерживает многопоточность (`-T0`).

### Структура конфигурации

Конфигурация строится по иерархическому принципу:
1.  **Глобальные настройки:** `/etc/logrotate.conf` — содержит настройки по умолчанию для всех логов.
2.  **Специфичные настройки сервисов:** `/etc/logrotate.d/` — директория для отдельных файлов конфигурации (например, `/etc/logrotate.d/nginx`). Настройки здесь переопределяют глобальные.

### Параметры конфигурации

| Опция | Описание и эффект |
| :--- | :--- |
| `daily` / `weekly` / `monthly` | Периодичность ротации. |
| `hourly` | Почасовая ротация (требует настройки запуска утилиты каждый час). |
| `rotate N` | Количество хранимых архивных копий перед удалением. |
| `maxage DAYS` | Удалять архивы старше указанного количества дней (важно для GDPR). |
| `size 100M` | Ротировать файл, как только его размер превысит 100 МБ. |
| `compress` | Сжимать старые логи (по умолчанию gzip). |
| `delaycompress` | Не сжимать последний архив (позволяет приложению/сборщику логов дочитать файл). |
| `missingok` | Не генерировать ошибку, если файл лога отсутствует. |
| `notifempty` | Не ротировать пустой файл. |
| `create MODE USER GROUP` | Создать новый файл с указанными правами и владельцем. |
| `su USER GROUP` | Выполнять ротацию от имени указанного пользователя (обязательно для небезопасных путей). |
| `dateext` | Использовать дату в имени архива вместо порядкового номера. |
| `dateformat FORMAT` | Формат даты (например, `-%Y%m%d-%H%M%S` для высокой точности). |
| `sharedscripts` | Выполнять скрипты `postrotate` / `prerotate` один раз для всей группы файлов. |
| `nosharedscripts` | Выполнять скрипты для каждого ротируемого файла (по умолчанию). |
| `olddir PATH` | Перемещать архивные логи в указанную директорию. |
| `mail ADDRESS` | Отправлять удаляемые логи на указанный email. |
| `ignoreduplicates` | Игнорировать дубликаты, если файл лога попал под несколько масок. |

## Стратегии ротации

Выбор стратегии критически важен для предотвращения потери данных или блокировки записи.

### 1. Метод с сигналом (postrotate)
Стандартный и наиболее надежный метод. `logrotate` переименовывает активный файл, создает новый, а затем отправляет приложению сигнал (обычно `SIGHUP` или `USR1`) для переоткрытия дескриптора.
- **Плюсы:** Отсутствие потери строк лога, высокая производительность.
- **Минусы:** Приложение должно поддерживать обработку сигналов для переоткрытия файлов.
- **Пример:**
  ```conf
  postrotate
      /usr/bin/systemctl reload nginx > /dev/null 2>&1
  endscript
  ```

### 2. Метод copytruncate
Используется для приложений, которые нельзя перезагрузить или заставить переоткрыть файл. Утилита копирует содержимое в архив, а затем обнуляет (`truncate`) оригинальный файл.
- **Плюсы:** Работает с любым приложением (Java, старые скрипты).
- **Минусы:** **Риск потери данных.** Строки, записанные в микросекунду между копированием и очисткой, будут потеряны.
- **Применение:** Только в крайнем случае, когда переоткрытие файлов невозможно.

### Обработка символьных ссылок и жёстких ссылок

По умолчанию `logrotate` **не следует** по символьным ссылкам. Если файл лога является симлинком, он будет пропущен с предупреждением.

**Безопасная ротация через симлинк:**
```ini
/var/log/myapp/current.log {
    daily
    rotate 7
    copytruncate
    missingok
    notifempty
}
```
Здесь `/var/log/myapp/current.log` — симлинк на `/var/log/myapp/app.log.1`. `logrotate` увидит симлинк и пропустит его. Вместо этого ротируйте **целевой** файл.

**Жёсткие ссылки (hardlinks):** При переименовании файла жёсткие ссылки продолжают указывать на старое имя (старые данные). Это может привести к неожиданному поведению, если приложение хранит дескриптор открытого файла.

### Рекомендации по выбору стратегии

| Сценарий | Стратегия | Обоснование |
| :--- | :--- | :--- |
| **Nginx, rsyslog, PostgreSQL** | postrotate + сигнал | Приложение поддерживает переоткрытие файлов. Нулевые потери. |
| **Java-приложения (Spring, Tomcat)** | copytruncate или log4j2 RollingFileAppender | JVM не переоткрывает файлы по сигналам. |
| **Приложения в Docker** | Встроенная ротация Docker | Внешний logrotate не видит файлы контейнеров. |
| **Критичные логи (аудит)** | postrotate + fsync + сигнал | Требуется максимальная надёжность. |

## Практические сценарии

### Сценарий 1: Высоконагруженный веб-сервер (Nginx)
Ротация по размеру и времени с использованием точного формата даты и группового выполнения скриптов.

```conf
/var/log/nginx/*.log {
    daily
    size 500M
    rotate 30
    compress
    delaycompress
    dateext
    dateformat -%Y%m%d-%H%M%S
    missingok
    notifempty
    sharedscripts
    postrotate
        /usr/sbin/nginx -s reopen
    endscript
}
```

### Сценарий 2: Безопасная ротация пользовательского приложения
Использование директивы `su` для защиты от атак через символические ссылки и перемещение архивов в отдельную папку.

```conf
/home/app-user/logs/*.log {
    su app-user app-group
    daily
    rotate 7
    olddir /home/app-user/logs/archives
    create 0640 app-user app-group
    copytruncate
}
```

### Сценарий 3: Почасовая ротация для критичных логов
Требует настройки `logrotate.timer` для запуска каждую минуту или час.

```conf
/var/log/critical_app.log {
    hourly
    rotate 24
    size 10M
    compress
}
```

### Сценарий 4: Java-приложение без поддержки сигналов

Java-приложения (Spring Boot, Tomcat, Jetty) часто не переоткрывают файлы по сигналам. Используйте `copytruncate` или настройте ротацию на уровне фреймворка (log4j2/logback).

```conf
/var/log/java-app/*.log {
    daily
    rotate 30
    size 100M
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

**Важно:** `copytruncate` не атомарен. Для критичных Java-приложений лучше использовать `log4j2 RollingFileAppender` с `CronTriggeringPolicy` или `SizeBasedTriggeringPolicy`.

### Сценарий 5: Полная настройка systemd-timer для почасовой ротации

По умолчанию `logrotate.timer` запускается раз в сутки. Для почасовой ротации создаём отдельный таймер:

```ini
# /etc/systemd/system/logrotate-hourly.timer
[Unit]
Description=Hourly logrotate

[Timer]
OnCalendar=*-*-* *:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/logrotate-hourly.service
[Unit]
Description=Run logrotate hourly

[Service]
Type=oneshot
ExecStart=/usr/sbin/logrotate /etc/logrotate.conf
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now logrotate-hourly.timer
```

Проверка:
```bash
systemctl list-timers logrotate-hourly.timer
# → NEXT                        LEFT     LAST                        PASSED  UNIT
# → Mon 2026-09-14 17:00:00 UTC 12min    Mon 2026-09-14 16:00:00 UTC 34min   logrotate-hourly.timer
```

### Сценарий 6: Мониторинг и алертинг ротации

Добавьте проверку в вашу систему мониторинга (Prometheus + node_exporter или bash-скрипт):

```bash
#!/bin/bash
# /usr/local/bin/check-logrotate.sh
STATUS_FILE="/var/lib/logrotate/status"
EXPECTED_INTERVAL_DAYS=1

LAST_ROTATION=$(stat -c %Y "$STATUS_FILE")
NOW=$(date +%s)
DIFF_DAYS=$(( (NOW - LAST_ROTATION) / 86400 ))

if [ "$DIFF_DAYS" -gt "$EXPECTED_INTERVAL_DAYS" ]; then
    echo "CRITICAL: logrotate not run for $DIFF_DAYS days"
    exit 2
fi

# Проверка размера /var/log
THRESHOLD=90
USAGE=$(df /var/log | awk 'NR==2 {print $5}' | tr -d '%')
if [ "$USAGE" -gt "$THRESHOLD" ]; then
    echo "WARNING: /var/log is ${USAGE}% full"
    exit 1
fi

echo "OK: logrotate is running, /var/log is ${USAGE}% full"
exit 0
```

```bash
# Запуск через systemd timer
sudo nano /etc/systemd/system/check-logrotate.timer
```

```ini
[Unit]
Description=Check logrotate status

[Timer]
OnCalendar=*-*-* *:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/check-logrotate.service
[Unit]
Description=Check logrotate status

[Service]
Type=oneshot
ExecStart=/usr/local/bin/check-logrotate.sh
```

### Сценарий 7: Инцидент "Диск заполнен логами"

```bash
# 1. Немедленная диагностика
df -h /var/log
du -sh /var/log/* | sort -rh | head -10
ls -lh /var/log/syslog* 2>/dev/null

# 2. Проверка статуса logrotate
sudo logrotate -d /etc/logrotate.conf 2>&1 | grep -i error
cat /var/lib/logrotate/status

# 3. Принудительная ротация
sudo logrotate -f /etc/logrotate.conf

# 4. Если не помогло — ручная очистка (осторожно!)
sudo truncate -s 0 /var/log/syslog.1
sudo rm -f /var/log/syslog.*.gz

# 5. Постоянное решение — настройка лимитов
sudo nano /etc/logrotate.d/syslog
# Добавить: size 100M, rotate 14, compress, delaycompress

# 6. Проверка, что система работает
sudo systemctl status rsyslog
tail -f /var/log/syslog
```

### Сценарий 8: Ротация логов приложения, запущенного через systemd

Для сервисов, управляемых systemd, лучше использовать **StdoutJournalctl** + `journald` retention. Если же логи пишутся в файл:

```ini
# /etc/systemd/system/myapp.service.d/logging.conf
[Service]
StandardOutput=file:/var/log/myapp/stdout.log
StandardError=file:/var/log/myapp/stderr.log
```

```conf
# /etc/logrotate.d/myapp
/var/log/myapp/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        systemctl kill -s SIGUSR1 myapp.service
    endscript
}
```

### Сценарий 9: Автоматизация через Ansible

```yaml
- name: Deploy logrotate config
  ansible.builtin.copy:
    dest: /etc/logrotate.d/myapp
    content: |
      /var/log/myapp/*.log {
          daily
          rotate 30
          compress
          delaycompress
          missingok
          notifempty
          create 0640 myapp myapp
          postrotate
              systemctl reload myapp
          endscript
      }
    owner: root
    group: root
    mode: '0644'

- name: Ensure logrotate timer is enabled
  ansible.builtin.systemd:
    name: logrotate.timer
    enabled: true
    state: started
```

### Сценарий 10: Chroot-сервисы (DNS, FTP)

Сервисы, работающие в chroot (например, `named`, `vsftpd`), требуют особой внимательности:

```conf
/var/named/chroot/var/log/named/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    su named named
    postrotate
        /usr/sbin/rndc freeze > /dev/null 2>&1
        /usr/sbin/rndc thaw > /dev/null 2>&1
    endscript
}
```

`su` обязателен, так как `logrotate` запускается от root, а файлы принадлежат непривилегированному пользователю внутри chroot.

## Диагностика и отладка

### Тестирование конфигурации
Всегда проверяйте новые правила перед применением:

```bash
# Режим отладки (dry-run): показывает действия без их выполнения
sudo logrotate -d /etc/logrotate.d/myapp

# Принудительный запуск ротации (игнорируя расписание и размер)
sudo logrotate -f /etc/logrotate.d/myapp

# Проверка конкретного файла конфигурации
sudo logrotate -v /etc/logrotate.d/myapp
```

### Файл состояния (Status File)
`logrotate` запоминает дату последней ротации в файле `/var/lib/logrotate/status` (или `/var/lib/logrotate.status`). Если вы хотите "обмануть" утилиту и заставить её думать, что ротация не проводилась, можно отредактировать дату в этом файле.

### Мониторинг выполнения

Проверяйте, что `logrotate` работает штатно. Добавьте в мониторинг:

```bash
# 1. Проверка времени последней ротации
LAST=$(stat -c %Y /var/lib/logrotate/status)
NOW=$(date +%s)
DIFF=$(( (NOW - LAST) / 86400 ))
if [ "$DIFF" -gt 1 ]; then
    echo "WARNING: logrotate ran $DIFF days ago"
fi

# 2. Проверка наличия ошибок в syslog/journal
sudo journalctl -u logrotate.service --since "24h ago" | grep -i error

# 3. Проверка размера архивов
find /var/log -name "*.gz" -size +100M -exec ls -lh {} \;
```

### Типичные ошибки и решения

| Ошибка | Возможная причина | Решение |
| :--- | :--- | :--- |
| **"parent directory has insecure permissions"** | Директория доступна на запись другим. | Используйте `su USER GROUP` или исправьте права (`chmod 755`). |
| **"log does not need rotating"** | Условия (период/размер) не выполнены. | Запустите с флагом `-f` для принудительной ротации. |
| **Заполнен диск, но логи маленькие** | Приложение пишет в удаленный дескриптор. | Настройте `postrotate` с сигналом или используйте `copytruncate`. Диагностика: `lsof +L1`. |
| **"error: ... is not a regular file"** | Путь указывает на директорию или сокет. | Проверьте маску в конфигурации (избегайте `*` если там есть подпапки). |
| **"error: skip ... because of su"** | Несоответствие пользователя в `su` и владельца файла. | Убедитесь, что `su` указывает на владельца директории/файла. |
| **Ротация не происходит для файлов в NFS** | NFS не поддерживает атомарный rename. | Используйте `copytruncate` или монтируйте NFS с опцией `noac`. |
| **"compress: command not found"** | Указанный в `compresscmd` бинарник отсутствует. | Установите пакет (например, `zstd`). |
| **Потеря логов при `copytruncate`** | Race condition между copy и truncate. | Перейдите на стратегию с сигналом. |
| **Inodes exhausted** | Слишком много маленьких файлов. | Проверьте `maxsize`, `rotate`, удалите старые архивы. |
| **"bad filename"** | Специальные символы в пути файла. | Экранируйте путь или используйте кавычки. |

### Сценарий 11: Ротация логов нестандартных сервисов

Для сервисов, которые не используют стандартные файловые логи или не поддерживают сигналы, требуются специальные конфигурации.

#### PostgreSQL

```conf
# /etc/logrotate.d/postgresql
/var/log/postgresql/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    su postgres postgres
    postrotate
        /usr/bin/pg_ctlcluster $(ls /var/log/postgresql/ | head -1 | sed 's/postgresql-\([0-9]*\)-.*/\1/') main reload > /dev/null 2>&1 || true
    endscript
}
```

Альтернатива — через `ALTER SYSTEM` (без перезапуска):
```sql
-- Включить логирование в CSV (для последующей ротации)
ALTER SYSTEM SET logging_collector = on;
ALTER SYSTEM SET log_directory = 'pg_log';
ALTER SYSTEM SET log_filename = 'postgresql-%Y-%m-%d.log';
ALTER SYSTEM SET log_rotation_age = 1440;  -- 24 часа в минутах
ALTER SYSTEM SET log_rotation_size = 102400;  -- 100 МБ
SELECT pg_reload_conf();
```

#### Redis

```conf
# /etc/logrotate.d/redis
/var/log/redis/redis-server.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    su redis redis
    postrotate
        /usr/bin/redis-cli -p 6379 -a "$(grep requirepass /etc/redis/redis.conf | awk '{print $2}')" DEBUG RELOAD > /dev/null 2>&1 || \
        /bin/kill -USR1 $(cat /var/run/redis/redis-server.pid 2>/dev/null) 2>/dev/null || true
    endscript
}
```

#### MongoDB

```conf
# /etc/logrotate.d/mongodb
/var/log/mongodb/mongod.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    su mongodb mongodb
    postrotate
        /usr/bin/mongosh --quiet --eval "db.adminCommand({getParameter: 1, diagnosticDataRoutingEnabled: 1})" > /dev/null 2>&1 || true
    endscript
}
```

#### HAProxy

```conf
# /etc/logrotate.d/haproxy
/var/log/haproxy/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    sharedscripts
    postrotate
        /usr/bin/systemctl reload haproxy > /dev/null 2>&1 || true
    endscript
}
```

#### Kafka (Confluent/Open Source)

```conf
# /etc/logrotate.d/kafka
/var/log/kafka/server.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    size 500M
    postrotate
        # Kafka не поддерживает сигналы для ротации — используйте copytruncate
        # Или через JMX: kafka-log-dirs.sh --describe
        /usr/bin/kafka-configs.sh --entity-type brokers --entity-default --alter --add-config log.retention.hours=168 > /dev/null 2>&1 || true
    endscript
}

# Kafka Connect / Schema Registry
/var/log/kafka/connect.log /var/log/kafka/schema-registry.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    size 200M
}
```

#### Docker (json-file driver)

```conf
# /etc/logrotate.d/docker-containers
/var/lib/docker/containers/*/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    size 100M
    maxsize 100M
}
```

**Примечание:** Docker не поддерживает `postrotate`-сигналы для контейнеров. `copytruncate` — единственный вариант. Рассмотрите переход на `local` logging driver для production.

#### Java-приложения (Spring Boot, Tomcat, Payara)

```conf
# /etc/logrotate.d/java-app
/var/log/java-app/*.log {
    daily
    rotate 30
    size 100M
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    maxage 30
}
```

**Важно:** Java-приложения не переоткрывают файлы по сигналам. Используйте:
1. `copytruncate` в logrotate (риск потери данных)
2. Встроенную ротацию (log4j2 `RollingFileAppender`, logback `TimeBasedRollingPolicy`)
3. Вывод в stdout → journald (рекомендуется для systemd-окружений)

### Безопасность

* **Директива `su`:** Всегда используйте `su USER GROUP` для путей, доступных не-root пользователям. Это предотвращает атаки через символические ссылки (symlink race).
* **Права на конфигурацию:** `/etc/logrotate.conf` и `/etc/logrotate.d/*` должны принадлежать `root:root` с правами `0644`. Любые изменения должны быть проверены.
* **Сжатие:** Убедитесь, что утилита сжатия (`gzip`, `zstd`) не имеет SUID-бита. Проверка: `find /usr/bin -perm -4000 -name '*zip*'`.
* **Логи в `/tmp`:** Избегайте размещения логов в `/tmp`, если они содержат чувствительные данные. `/tmp` может быть смонтирован с `noexec` или очищаться при перезагрузке.
* **Сетевая файловая система (NFS):** На NFS атомарный `rename` может не работать. Используйте `copytruncate` или локальное хранение.

### Производительность

* **Асинхронная компрессия:** `logrotate` по умолчанию сжимает файлы синхронно, блокируя запуск. Для больших файлов (>1GB) рассмотрите `nice`/`ionice`:
  ```ini
  compress
  compresscmd /usr/bin/nice -n 19 /usr/bin/zstd
  ```
* **`delaycompress`:** Не сжимает последний архив, позволяя приложению дочитать файл. Используйте для высоконагруженных сервисов.
* **`maxsize`:** Ротирует файл только если он превышает указанный размер, даже если прошло меньше времени. Полезно для burst-логгирования.
* **`minsize`:** Не ротирует файл, если он меньше указанного размера, даже если прошло достаточно времени. Экономит операции сжатия для пустых/маленьких файлов.
* **Ограничение ресурсов:** Для систем с низким CPU/I/O используйте `gzip` вместо `zstd`/`xz` и увеличивайте интервалы ротации.

### Best Practices

1. **Всегда используйте `missingok` и `notifempty`:** Избегают лишних ошибок и операций с пустыми файлами.
2. **Используйте `delaycompress`** для файлов, которые могут ещё читаться приложением после сигнала.
3. **Настраивайте `postrotate` только при необходимости:** Лишние скрипты замедляют ротацию.
4. **Используйте `su USER GROUP`** для всех пользовательских логов.
5. **Мониторьте выполнение:** Добавьте проверку в систему мониторинга.
6. **Храните логи отдельно от системы:** Для критичных сервисов используйте отдельный раздел или диск для `/var/log`.
7. **Тестируйте конфигурацию:** `logrotate -d` перед применением.
8. **Используйте `dateext` + `dateformat`** для легкой идентификации архивов.
9. **Для journald-систем:** Настройте `SystemMaxUse` и `MaxRetentionSec` в `journald.conf`, а `logrotate` используйте только для текстовых логов rsyslog.
10. **Избегайте `copytruncate`** в production для критичных логов. Риск потери данных перевешивает удобство.

### Compliance

* **PCI DSS v4.0.1:** Требует хранения логов не менее 12 месяцев. Настройте `rotate 365` для критичных логов.
* **GDPR:** Удаление архивов через `maxage` или `rotate` должно быть задокументировано. Используйте `maxage 365d` для политики хранения.
* **ФЗ-152 (Россия):** Требует защиты персональных данных. Убедитесь, что логи не содержат незамаскированных PAN/паспортных данных. Используйте `mask` в rsyslog перед передачей в `logrotate`.

### Известные ограничения

1. **Не атомарная запись:** `copytruncate` может потерять строки, записанные между копированием и обнулением.
2. **Отсутствие inotify:** `logrotate` не реагирует на изменения файлов в реальном времени. Он работает по расписанию.
3. **Сложность с chroot:** Файлы в chroot требуют `su` и корректных путей.
4. **Ограничение на количество файлов:** Очень большое количество файлов (`>10000`) замедляет работу из-за обхода директорий.
5. **Версия:** Некоторые параметры (`maxsize`, `minsize`, `dateformat`) доступны только в logrotate 3.7+. Проверяйте версию: `logrotate --version`.
6. **Потоки (threads):** `logrotate` не потокобезопасен для приложений, пишущих в один файл из нескольких потоков без внешней синхронизации.

### Интеграция с journald

В системах на базе systemd предпочитайте встроенную ротацию journald перед `logrotate`:

* `logrotate` работает с **текстовыми файлами** (`/var/log/syslog`, `/var/log/messages`).
* `journald` управляет **бинарным журналом** (`/run/log/journal`, `/var/log/journal`).

Для текстовых логов rsyslog используйте `logrotate`. Для journald настраивайте `SystemMaxUse`, `MaxRetentionSec` в `/etc/systemd/journald.conf`. Подробнее: [journald](./journald.md).

### См. также

- [Обзор логирования в Linux](./logging_overview.md)
- [systemd-journald: Сбор и хранение](./journald.md)
- [rsyslog: Фильтрация и пересылка](./rsyslog.md)
