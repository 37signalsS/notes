# Управление лимитами ресурсов: ulimit и prlimit

## Определения

**Лимиты ресурсов (Resource Limits)** — системные ограничения на потребление вычислительных ресурсов (процессорное время, память, количество файлов), накладываемые ядром Linux на процессы для обеспечения стабильности системы. Полная теория: [Концепции лимитов ресурсов](./resource_limits_concepts.md).

**ulimit** — встроенная команда оболочки (shell builtin), предназначенная для управления лимитами текущего сеанса и всех его дочерних процессов. Поскольку это builtin, изменения применяются мгновенно внутри адресного пространства shell.

**prlimit** — внешняя утилита (часть `util-linux`), позволяющая просматривать и изменять лимиты любого запущенного процесса по его PID, а также запускать новые программы с заданными ограничениями.

**getrlimit / setrlimit / prlimit** — фундаментальные системные вызовы ядра Linux, на которых базируются все инструменты управления лимитами.

## Основные концепции

### Типы лимитов: Мягкие и жесткие

Каждый ресурс имеет два связанных с ним значения:
- **Soft Limit (Мягкий):** Действующее ограничение. При его достижении ядро может отправить сигнал (например, `SIGXCPU`) или вернуть ошибку (например, `EMFILE`). Пользователь может самостоятельно увеличивать его до значения жесткого лимита.
- **Hard Limit (Жесткий):** Абсолютный потолок для мягкого лимита. Только привилегированный пользователь (`root`) или процесс с capability `CAP_SYS_RESOURCE` может повышать жесткий лимит. Обычный пользователь может только понижать его (необратимо для текущей сессии).

### Полный справочник RLIMIT_*

| Ресурс | Флаг ulimit | Техническое имя | Описание | Единицы |
| :--- | :--- | :--- | :--- | :--- |
| **Открытые файлы** | `-n` | `RLIMIT_NOFILE` | Максимум файловых дескрипторов. Включает сокеты, пайпы, fifo. | дескрипторы |
| **Процессы** | `-u` | `RLIMIT_NPROC` | Лимит на количество задач (потоков) для всего UID. | задачи |
| **Виртуальная память** | `-v` | `RLIMIT_AS` | Лимит на общее адресное пространство. Влияет на `mmap` и `brk`. | KB |
| **Резидентная память** | `-m` | `RLIMIT_RSS` | **Устарело** в ядрах 2.6+. Заменено на cgroups. | KB |
| **Время CPU** | `-t` | `RLIMIT_CPU` | Суммарное время CPU. `SIGXCPU` при мягком, `SIGKILL` при жестком. | секунды |
| **Блокировка памяти** | `-l` | `RLIMIT_MEMLOCK` | Память, фиксируемая в RAM через `mlock()`. | KB |
| **Core-дампы** | `-c` | `RLIMIT_CORE` | Максимальный размер core-файла (0 — откл). | KB |
| **Размер стека** | `-s` | `RLIMIT_STACK` | Максимальный размер стека потока. Превышение → `SIGSEGV`. | KB |
| **Размер файла** | `-f` | `RLIMIT_FSIZE` | Максимальный размер создаваемого файла. Превышение → `SIGXFSZ`. | блоки |
| **RT Timeout** | — | `RLIMIT_RTTIME` | Время непрерывного выполнения в RT-режиме (`SCHED_FIFO`/`RR`). | мкс |
| **Сигналы** | `-i` | `RLIMIT_SIGPENDING` | Очередь сигналов для UID. | сигналы |
| **Приоритет nice** | `-e` | `RLIMIT_NICE` | Максимальный приоритет, который процесс может установить. | nice |
| **RT Приоритет** | `-r` | `RLIMIT_RTPRIO` | Максимальный приоритет RT через `sched_setscheduler`. | приор. |
| **POSIX очереди** | `-q` | `RLIMIT_MSGQUEUE` | Память для POSIX очередей сообщений для UID. | байты |

### Области применения инструментов

| Инструмент | Метод управления | Область действия |
| :--- | :--- | :--- |
| **ulimit** | Встроенная команда shell | Текущий shell и его потомки |
| **prlimit** | Утилита / системный вызов | Любой процесс по PID |
| **systemd-run** | Временный (transient) юнит | Процесс в изолированном окружении |
| **/proc/PID/limits** | Интерфейс ядра (procfs) | Только просмотр текущих лимитов |

### Иерархия применения лимитов

Лимиты проверяются ядром в порядке от наиболее строгих к наименее строгим:

```
Глобальные лимиты ядра (sysctl)        → fs.nr_open, fs.file-max
         ↓
Контрольные группы (cgroups v2)        → memory.max, pids.max
         ↓
Системные сервисы (systemd)            → LimitNOFILE=...
         ↓
PAM / limits.conf (пользователи)       → SSH/Login сессии
         ↓
ulimit (текущая сессия)                → Временный
```

**Ключевые правила:**
- Cgroups имеют приоритет над rlimits. Если `memory.max=512M`, а `RLIMIT_AS=1G`, процесс упадет по OOM при 512MB.
- Настройки `limits.conf` (PAM) **не влияют** на системные сервисы systemd.
- Некоторые rlimits (`NPROC`, `SIGPENDING`) суммируются по всем процессам пользователя (UID).

## Практические сценарии

### Работа с текущей сессией (ulimit)

`ulimit` используется для оперативной настройки окружения перед запуском приложений или скриптов.

**Основные флаги:**

| Флаг | Ресурс | Техническое имя | Единицы |
| :--- | :--- | :--- | :--- |
| `-n` | Открытые файлы | `RLIMIT_NOFILE` | дескрипторы |
| `-u` | Количество процессов/потоков | `RLIMIT_NPROC` | задачи |
| `-v` | Виртуальная память (Address Space) | `RLIMIT_AS` | KB |
| `-c` | Размер Core-дампа | `RLIMIT_CORE` | KB (0 — откл) |
| `-t` | Время использования CPU | `RLIMIT_CPU` | секунды |
| `-s` | Размер стека | `RLIMIT_STACK` | KB |
| `-l` | Блокировка памяти | `RLIMIT_MEMLOCK` | KB |
| `-a` | Показать все лимиты | — | — |

**Примеры использования:**
```bash
# Просмотр всех лимитов текущей сессии
ulimit -a

# Просмотр жесткого лимита на открытые файлы
ulimit -Hn

# Увеличение мягкого лимита на количество процессов до 4096 (в пределах Hard)
ulimit -Su 4096

# Полное снятие ограничений на размер файла (в текущей сессии)
ulimit -f unlimited

# Отключение core-дампов
ulimit -c 0

# Установка лимита виртуальной памяти на 8GB
ulimit -v 8388608
```

### Управление живыми процессами (prlimit)

`prlimit` — основной инструмент SRE для динамического изменения лимитов без перезапуска приложения.

```bash
# Просмотр всех лимитов конкретного процесса
prlimit -p 1234

# Изменение лимита открытых файлов (soft=4096, hard=8192) для PID 1234
sudo prlimit --pid 1234 --nofile=4096:8192

# Установка нескольких лимитов одновременно
sudo prlimit --pid 1234 --nproc=1024 --as=2G --memlock=65536

# Установка лимита на runtime CPU (10 секунд)
sudo prlimit --pid 1234 --cpu=10

# Получение конкретного значения для использования в скриптах
prlimit -p 1234 --nofile --raw --noheadings --output SOFT
```

### Запуск процессов с ограничениями (systemd-run)

Современная альтернатива `ulimit` для запуска фоновых задач с гарантированными лимитами:

```bash
# Запуск скрипта с ограничением на количество файлов и процессов
systemd-run --user --scope -p LimitNOFILE=65536 -p LimitNPROC=4096 ./my_heavy_script.sh

# Запуск с лимитом памяти и runtime
systemd-run --user --scope \
  -p LimitNOFILE=65536 \
  -p LimitNPROC=4096 \
  -p MemoryMax=1G \
  -p CPUQuota=200% \
  -p TasksMax=256 \
  ./worker.sh

# Просмотр созданного временного юнита
systemctl --user list-units --type=scope --all
```

### Лимиты в контейнерах (Docker/Podman)

В контейнеризированных средах `ulimit` хоста игнорируется, если не настроен проброс:

```bash
# Запуск контейнера с кастомным лимитом
docker run --ulimit nofile=1024:2048 --ulimit nproc=512 my-app

# Запрет core-дампов и блокировка memlock
docker run --ulimit core=0:0 --ulimit memlock=-1:-1 postgres

# Проверка лимитов внутри запущенного контейнера
docker exec -it my-app sh -c "ulimit -n"

# Глобальные настройки в daemon.json
sudo tee /etc/docker/daemon.json <<EOF
{
  "default-ulimits": {
    "nofile": { "Name": "nofile", "Hard": 65536, "Soft": 65536 },
    "nproc": { "Name": "nproc", "Hard": 16384, "Soft": 16384 }
  }
}
EOF
sudo systemctl restart docker
```

### Диагностика и проверка через procfs

Файл `/proc/PID/limits` — единственный источник истины о том, какие лимиты *фактически* видит процесс:

```bash
# Проверка лимитов процесса Nginx
cat /proc/$(pgrep nginx | head -1)/limits
# → Max open files            1024                 4096                 files
# → Max processes             63714                63714                processes
# → Max locked memory         67108864             67108864              bytes

# Мониторинг FD в реальном времени
watch -n1 'ls /proc/$(pgrep nginx | head -1)/fd | wc -l'
```

### Постоянная настройка через PAM и systemd (кратко)

Для production систем настройка должна быть постоянной. Подробнее: [Постоянная настройка лимитов](./persistent_limits_configuration.md).

```bash
# /etc/security/limits.d/90-app.conf
appuser    soft    nofile    65536
appuser    hard    nofile    131072
appuser    soft    memlock   unlimited
appuser    hard    memlock   unlimited

# Проверка применения для systemd-сервиса
systemctl show myapp -p LimitNOFILE
# → LimitNOFILE=65536
```

### Production сценарии

#### Веб-серверы (Nginx/Angie)

```bash
# Проверка текущих лимитов worker-процесса
cat /proc/$(pgrep -n 'nginx: worker')/limits | grep "Max open files"

# Для Nginx: worker_rlimit_nofile должен быть >= worker_connections * 2
# (клиент + бэкенд на каждое проксируемое соединение)
```

#### Базы данных (PostgreSQL/MySQL)

```bash
# PostgreSQL требует memlock для блокировки shared_buffers в RAM
sudo prlimit --pid $(pgrep -n postgres) --memlock=unlimited

# Проверка, что shared_buffers зафиксированы
grep -i "locked" /proc/$(pgrep -n postgres)/smaps
```

#### Java-приложения

```bash
# Java создает поток на каждое соединение. Низкий nproc приведет к OOM
ulimit -u 65536
java -Xmx4g -jar app.jar

# Или через systemd юнит
# [Service]
# LimitNPROC=65536
# LimitNOFILE=65536
```

#### Kafka/RabbitMQ

```bash
# Kafka открывает FD для каждого сегмента партиции + сокеты клиентов
# Минимум 65536 для production кластеров
echo "kafka soft nofile 65536" >> /etc/security/limits.d/90-kafka.conf
echo "kafka hard nofile 262144" >> /etc/security/limits.d/90-kafka.conf
```

### Интеграция с мониторингом

#### Prometheus (node_exporter)

```promql
# Процент использования лимита дескрипторов процессом
process_open_fds / process_max_fds > 0.8

# Обнаружение CLOSE_WAIT шторма
node_netstat_Tcp_CloseWait > 1000

# LOF of open files по процессам
sum by(process) (process_open_fds)
```

#### Встроенные метрики через /proc

```bash
# Статистика использования FD системой
cat /proc/sys/fs/file-nr
# → <выделено>   <свободно>   <максимум>

# LOF конкретного процесса
ls /proc/<PID>/fd | wc -l

# D-статусы процессов (может указывать на утечки)
ps aux | awk '$8 ~ /D/ {print $0}' | wc -l
```

### Валидация и проверка

```bash
# 1. Проверка всех лимитов процесса
cat /proc/<PID>/limits

# 2. Проверка системных «потолков»
sysctl fs.nr_open
sysctl fs.file-max

# 3. Проверка применения systemd-юнита
systemctl show <service> -p LimitNOFILE -p LimitNPROC -p LimitMEMLOCK

# 4. Проверка через prlimit (сравнение с ulimit)
prlimit --pid <PID> --nofile
```

## Дополнительная информация

### Типичные ошибки и их решение

1. **Operation not permitted:**
   - *Причина:* Попытка обычного пользователя увеличить мягкий лимит выше жесткого.
   - *Решение:* Настройте `/etc/security/limits.conf` или используйте `sudo prlimit`.

2. **Лимит не применяется:**
   - *Причина:* Процесс запущен через `systemd`, который игнорирует `/etc/security/limits.conf`.
   - *Решение:* Используйте директивы `LimitNOFILE=` и др. в юнит-файле или drop-in.

3. **ulimit -n возвращает ошибку при больших значениях:**
   - *Причина:* Попытка выставить значение выше системного «потолка» `fs.nr_open`.
   - *Решение:* `sudo sysctl -w fs.nr_open=2097152`.

4. **Java: Unable to create native thread:**
   - *Причина:* Исчерпан `RLIMIT_NPROC` или `pids.max` cgroup.
   - *Решение:* Увеличьте `ulimit -u` / `LimitNPROC=` и проверьте `pids.max`.

5. **"Too many open files" при низком значении `ulimit -n`:**
   - *Причина:* Исчерпан `RLIMIT_NOFILE`. Также проверьте `fs.file-max` (общесистемный лимит).
   - *Решение:* Увеличьте лимит на уровне процесса и проверьте системный `file-max`. Подробнее: [Диагностика «too many open files»](../../Diagnostics/Troubleshooting/troubleshooting_too_many_open_files.md).

### Технические нюансы

- **Наследование:** Лимиты наследуются при `fork()` и сохраняются при `execve()`.
- **Bash vs Zsh:** В разных shell `ulimit` может иметь разные флаги или единицы измерения.
- **Capabilities:** Для повышения жесткого лимита требуется `CAP_SYS_RESOURCE`.
- ** prlimit(2):** Универсальный системный вызов (Linux 2.6.36+). Позволяет атомарно считывать/устанавливать лимиты другого процесса.
- **Взаимодействие с Cgroups:** `ulimit` (rlimits) работает параллельно с cgroups. Cgroups обычно более строгие.

### См. также

- [**Концепции лимитов ресурсов**](./resource_limits_concepts.md) — теория, типы лимитов и иерархия.
- [**Постоянная настройка лимитов**](./persistent_limits_configuration.md) — настройка через systemd и PAM.
- [**Диагностика «too many open files»**](../../Diagnostics/Troubleshooting/troubleshooting_too_many_open_files.md) — практическое руководство по исправлениям.
- [**Файловые дескрипторы**](../../FileSystems/file_descriptors.md) — устройство FD в ядре.
- [**Механизм OOM Killer**](./oom_killer_mechanism.md) — последствия превышения лимитов памяти.
- [**Контрольные группы (cgroups)**](../cgroups.md) — сравнение cgroups и rlimits.
- [**Утилита lsof**](../../Diagnostics/Processes/lsof.md) — мониторинг открытых файлов.
