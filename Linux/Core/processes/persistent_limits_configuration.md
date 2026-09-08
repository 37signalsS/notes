# Постоянная настройка лимитов ресурсов в Linux

## Определения

**Постоянные лимиты (Persistent Limits)** — конфигурационные настройки, гарантирующие автоматическое применение ограничений ресурсов (rlimits и cgroups) при загрузке ОС, запуске системных служб или инициализации пользовательских сессий.

**sysctl.d** — модульный механизм ядра для установки общесистемных «потолков» ресурсов (например, `fs.nr_open`), которые служат абсолютными границами для всех процессов в системе.

**pam_limits.so** — модуль Pluggable Authentication Modules (PAM), который считывает настройки из `limits.conf` и применяет их к сессии пользователя в момент аутентификации (логина).

**DefaultLimit*** — группа параметров в конфигурации systemd, задающая значения rlimits по умолчанию для всех юнитов, если иное не указано в их индивидуальных файлах.

**Drop-in (переопределение)** — фрагмент конфигурации в `/etc/systemd/system/<unit>.d/`, который дополняет или переопределяет параметры основного unit-файла. Приоритет выше, чем у основного файла.

**LimitNOFILE, LimitNPROC, LimitCORE** — директивы systemd, задающие rlimits для конкретного сервиса. Устанавливают Soft=Hard одновременно.

**systemd-coredump** — демон, управляющий сохранением core-дампов в современных дистрибутивах. `LimitCORE` определяет максимальный размер дампа, который затем передается systemd-coredump.

**tmpfiles.d** — механизм systemd для создания и управления временными файлами и каталогами. Используется для персистентной настройки cgroups и sysctl-параметров на ранних стадиях загрузки.

## Основные концепции

### Иерархия и область действия конфигураций

Лимиты настраиваются на разных уровнях в зависимости от целевого объекта. Понимание иерархии критично для диагностики конфликтов:

| Уровень | Механизм | Файлы конфигурации | Влияние |
| :--- | :--- | :--- | :--- |
| **Глобальный (Kernel)** | `sysctl` | `/etc/sysctl.d/*.conf` | Весь хост (ядерные «потолки»). |
| **Глобальный (systemd Manager)** | `systemd` | `/etc/systemd/system.conf`, `/etc/systemd/user.conf` | Все сервисы или пользовательские юниты по умолчанию. |
| **Индивидуальный (Service)** | `systemd unit` | `/etc/systemd/system/<name>.service.d/*.conf` | Конкретная служба (drop-in имеет приоритет над основным unit-файлом). |
| **Сессионный (PAM)** | `PAM` | `/etc/security/limits.conf`, `/etc/security/limits.d/*.conf` | Только пользовательские сессии (SSH, TTY, GUI), активируемые через PAM. |
| **Контейнеры (Runtime)** | `Docker / CRI` | `/etc/docker/daemon.json`, `config.toml` | Все контейнеры данного рантайма. |

**Важное замечание:** Конфигурации `limits.conf` (PAM) **не применяются** к процессам, запущенным через systemd. Для них используются исключительно директивы `Limit*=` в unit-файлах или drop-in'ах. Это распространенная причина путаницы: администратор изменяет `limits.conf`, но systemd-сервисы продолжают работать со старыми значениями.

### Технические различия в синтаксисе

| Параметр | limits.conf (PAM) | systemd (Units / Global) |
| :--- | :--- | :--- |
| **Единицы памяти** | Строго в Килобайтах (KB) | Суффиксы (K, M, G, T) |
| **Бесконечность** | Строка `unlimited` | Ключевое слово `infinity` |
| **Тип лимита** | Разделение на `soft` и `hard` | Одно значение (устанавливает Soft=Hard) |
| **Приоритет файла** | Алфавитный порядок в `.d/` | Имя drop-in (обычно `10-`, `20-`) + `systemctl daemon-reload` |
| **Применение** | При логине (PAM session) | При запуске/перезагрузке юнита |

### Полный справочник директив systemd для лимитов

В отличие от `limits.conf`, systemd предоставляет отдельные директивы для каждого типа лимита:

| Директива systemd | rlimit_Resource | Описание |
| :--- | :--- | :--- |
| `LimitNOFILE` | `RLIMIT_NOFILE` | Максимум открытых файлов/сокетов. |
| `LimitNPROC` | `RLIMIT_NPROC` | Максимум процессов/потоков для UID. |
| `LimitMEMLOCK` | `RLIMIT_MEMLOCK` | Максимум заблокированной памяти (mlock). |
| `LimitAS` | `RLIMIT_AS` | Максимум адресного пространства. |
| `LimitRSS` | `RLIMIT_RSS` | Максимум резидентной памяти (устарело, игнорируется ядром). |
| `LimitSTACK` | `RLIMIT_STACK` | Максимум размера стека. |
| `LimitCORE` | `RLIMIT_CORE` | Максимум размера core-дампа (0 — отключено). |
| `LimitFSIZE` | `RLIMIT_FSIZE` | Максимум размера файла. |
| `LimitSIGPENDING` | `RLIMIT_SIGPENDING` | Максимум сигналов в очереди для UID. |
| `LimitRTTIME` | `RLIMIT_RTTIME` | Максимум непрерывного RT-время (мкс). |
| `LimitRTPRIO` | `RLIMIT_RTPRIO` | Максимум приоритета RT. |
| `LimitNICE` | `RLIMIT_NICE` | Максимум приоритета nice. |
| `LimitMSGQUEUE` | `RLIMIT_MSGQUEUE` | Максимум памяти для POSIX очередей. |

### Механизм применения PAM-лимитов

`pam_limits.so` работает только на этапе **открытия сессии** (`session` тип в `/etc/pam.d/`). Процесс:

1. Пользователь аутентифицируется (например, через SSH).
2. PAM читает конфигурацию из `/etc/pam.d/sshd` (или другого сервиса).
3. Если найдена строка `session required pam_limits.so`, модуль загружает `/etc/security/limits.conf` и `limits.d/`.
4. Для каждого правила (domain, type, item, value) применяется `setrlimit()` к процессу.
5. Лимиты наследуются всеми дочерними процессами через `fork()`.

**Ключевые ограничения:**
- **Не применяется** к системным сервисам systemd (они обходят PAM).
- **Не применяется** к процессам, запущенным через `sudo` без `-i` (сохраняет лимиты вызывающего пользователя).
- **Не применяется** к cron-задачам (если cron не настроен на загрузку PAM).
- **Требует перелогина** для применения изменений (существующие сессии не обновляются).

### Взаимодействие systemd и PAM

В современных дистрибутивах (systemd 230+) `pam_systemd.so` автоматически создает cgroup для пользовательской сессии. Это означает:

- Сессия пользователя помещается в `user-<UID>.slice` → `user@<UID>.service`.
- Настройки `Limit*` из `limits.conf` применяются к **всем** процессам сессии, включая графические приложения.
- При выходе из сессии cgroup автоматически уничтожается.

**Важность:** Даже если `limits.conf` установлен `nofile=65536`, а systemd для `user@1000.service` установлен `LimitNOFILE=1024`, победит systemd, так как PAM-лимиты применяются внутри уже существующего cgroup.

### Валидация и проверка

Никогда не доверяйте конфигурационным файлам, проверяйте живой процесс:

```bash
# 1. Проверка лимитов конкретного PID (источник истины)
cat /proc/$(pgrep nginx | head -1)/limits

# 2. Проверка, какой PAM файл применил лимиты (в логах при логине)
grep "pam_limits" /var/log/auth.log
# или для RHEL:
grep "pam_limits" /var/log/secure

# 3. Просмотр эффективных настроек sysctl
sysctl -a | grep fs.nr_open

# 4. Проверка лимитов systemd-сервиса (без чтения файлов юнитов)
systemctl show <service_name> -p LimitNOFILE -p LimitNPROC -p LimitMEMLOCK

# 5. Проверка cgroup лимитов (pids.max, memory.max)
systemctl show <service_name> -p TasksMax -p MemoryMax

# 6. Проверка сессии пользователя (какой slice и cgroup)
loginctl show-user <username> -p Display -p Slice
```

### Сравнение методов персистентной настройки

| Метод | Уровень | Применение | Когда использовать |
| :--- | :--- | :--- | :--- |
| `/etc/sysctl.d/*.conf` | Ядро | При загрузке (`sysctl --system`) | Абсолютные потолки (`fs.nr_open`, `kernel.pid_max`). |
| `/etc/systemd/system.conf` | systemd Manager | При `daemon-reexec` | Глобальные лимиты для всех сервисов. |
| Unit drop-in (`.d/`) | Сервис | При `daemon-reload` + restart | Индивидуальные сервисы (рекомендуемый метод). |
| `/etc/security/limits.conf` | PAM | При логине | Пользовательские сессии (SSH, TTY). |
| `systemd-coredump` | Core-дампы | При падении процесса | Управление сохранением core-файлов. |

## Практические сценарии

### Сценарий 1: Настройка глобальных «потолков» ядра (sysctl)

Если системный лимит `fs.nr_open` ниже, чем `ulimit -n`, процесс получит ошибку при попытке поднять лимит.

```bash
# Оптимизация для высоконагруженных узлов (L7-балансировщики, базы данных)
sudo tee /etc/sysctl.d/90-limits.conf <<EOF
# Максимальный rlimit_nofile, который может запросить любой процесс
fs.nr_open = 2097152
# Общий лимит открытых дескрипторов во всей системе
fs.file-max = 2097152
# Лимит на количество PID (актуально для систем с 1000+ контейнеров)
kernel.pid_max = 4194304
EOF

# Применение
sudo sysctl --system
```

**Проверка:**
```bash
sysctl fs.nr_open fs.file-max kernel.pid_max
# → fs.nr_open = 2097152
# → fs.file-max = 2097152
# → kernel.pid_max = 4194304
```

### Сценарий 2: Глобальные лимиты systemd (system.conf)

По умолчанию systemd устанавливает довольно низкие лимиты для сервисов (например, 1024 для файлов). Чтобы изменить это для **всех** служб:

```ini
# /etc/systemd/system.conf
[Manager]
# Установка базового уровня для всех юнитов
DefaultLimitNOFILE=65536:524288
DefaultLimitNPROC=16384
DefaultLimitCORE=infinity
```

Применение:
```bash
# systemd требует перезапуска менеджера для применения глобальных параметров
sudo systemctl daemon-reexec
```

**Проверка:**
```bash
systemctl show --property=DefaultLimitNOFILE,DefaultLimitNPROC,DefaultLimitCORE
```

### Сценарий 3: Модульные лимиты PAM для пользователей

Используйте `/etc/security/limits.d/` для изоляции настроек приложений:

```bash
# /etc/security/limits.d/90-postgresql.conf
# <domain>    <type>  <item>  <value>
postgres      soft    nofile  65536
postgres      hard    nofile  131072
postgres      soft    memlock unlimited
postgres      hard    memlock unlimited
```

**Важно:** Убедитесь, что в файлах `/etc/pam.d/common-session` и `sshd` присутствует строка:
`session required pam_limits.so`

Для RHEL/CentOS проверьте `/etc/pam.d/system-auth` и `/etc/pam.d/password-auth`.

**Диагностика применения:**
```bash
# Проверка, что модуль загружен
grep pam_limits /etc/pam.d/sshd /etc/pam.d/common-session /etc/pam.d/login

# Проверка логов
grep pam_limits /var/log/auth.log
# или
grep pam_limits /var/log/secure
```

### Сценарий 4: Лимиты в Container Runtimes

**Docker (`/etc/docker/daemon.json`):**
```json
{
  "default-ulimits": {
    "nofile": { "Name": "nofile", "Hard": 65536, "Soft": 65536 },
    "nproc": { "Name": "nproc", "Hard": 16384, "Soft": 16384 }
  }
}
```

Применение:
```bash
sudo systemctl restart docker
```

**Containerd (`/etc/containerd/config.toml`):**
```toml
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
  # Лимиты задаются через системные настройки или параметры запуска пода
  # Для глобального переопределения используйте systemd-юнит самого containerd
```

Для containerd рекомендуется настраивать лимиты через systemd-юнит:
```ini
# /etc/systemd/system/containerd.service.d/10-limits.conf
[Service]
LimitNOFILE=65536
LimitNPROC=16384
```

### Сценарий 5: Drop-in конфигурации для конкретных сервисов (systemd)

Рекомендуемый метод для production — использование drop-in'ов вместо редактирования основного unit-файла:

```bash
# Создание drop-in для PostgreSQL
sudo systemctl edit postgresql

# В открытом редакторе добавьте:
# [Service]
# LimitNOFILE=65536
# LimitMEMLOCK=unlimited
# LimitNPROC=65536
# TasksMax=512

# Применение
sudo systemctl daemon-reload
sudo systemctl restart postgresql

# Проверка
systemctl show postgresql -p LimitNOFILE -p LimitMEMLOCK -p LimitNPROC -p TasksMax
```

**Преимущества drop-in'ов:**
- Не изменяют исходный unit-файл (сохраняется при обновлении пакета).
- Поддерживаются приоритеты (10-*, 20-*, 30-*).
- Легко откатываются через `sudo systemctl revert <service>`.

### Сценарий 6: `systemctl set-property` для runtime-лимитов

Для применения лимитов без перезапуска службы используйте `systemctl set-property`:

```bash
# Изменение лимитов во время работы
sudo systemctl set-property nginx.service LimitNOFILE=1048576 LimitNPROC=8192

# Применение без перезапуска (требует systemd 230+)
sudo systemctl daemon-reload

# Проверка
systemctl show nginx -p LimitNOFILE -p LimitNPROC
```

**Ограничение:** `daemon-reload` перечитывает конфигурацию, но некоторые сервисы кэшируют лимиты при старте и не перечитывают их динамически. В этом случае требуется перезапуск.

### Сценарий 7: Настройка `systemd-coredump` для управления core-дампами

В современных системах core-дампы обрабатываются `systemd-coredump`, а не пишутся напрямую в файловую систему:

```bash
# /etc/systemd/coredump.conf
[Coredump]
# Ограничение размера дампа (соответствует LimitCORE)
ProcessSizeMax=2G
# Максимальный процент от свободной Filesystem
ExternalSizeMax=1G
# Сохранять дампы в /var/lib/systemd/coredump/
Storage=external
# Сжатие
Compress=yes
# Очистка старых дампов (старше 7 дней)
MaxRetentionSec=7day
```

Применение:
```bash
sudo systemctl daemon-reload
sudo systemctl restart systemd-coredump
```

### Сценарий 8: Персистентная настройка cgroups через systemd

Для ограничения количества процессов (`pids.max`) и памяти через cgroups используйте директивы в unit-файлах:

```ini
# /etc/systemd/system/myapp.service
[Service]
ExecStart=/usr/bin/myapp

# --- rlimits ---
LimitNOFILE=65536
LimitNPROC=4096

# --- cgroups ---
TasksAccounting=true
TasksMax=512
MemoryMax=1G
MemoryHigh=800M
```

**Взаимодействие:** `LimitNPROC` (rlimit) и `TasksMax` (cgroup) работают совместно. Если процесс исчерпает `LimitNPROC`, но `TasksMax` еще не достигнут, новые потоки будут блокироваться на уровне UID. Если исчерпан `TasksMax`, блокировка происходит на уровне cgroup.

### Сценарий 9: Пользовательские лимиты для сессий (user@.service)

Для ограничения ресурсов всех процессов пользовательской сессии:

```ini
# /etc/systemd/system/user@.service.d/10-resource-limits.conf
[Service]
# Ограничение всего пользовательского инстанса
MemoryMax=4G
CPUQuota=200%           # 2 ядра на всю сессию
TasksMax=512
IOWeight=50
```

Применение:
```bash
sudo systemctl daemon-reload
# Действует для всех новых сессий (логин/SSH)
```

**Важно:** Для текущих сессий требуется выход и повторный вход. Проверить можно через:
```bash
systemctl show user@1000 -p MemoryMax -p CPUQuota -p TasksMax
```

### Сценарий 10: `loginctl` для управления сессиями и лимитами

`loginctl` позволяет управлять сессиями пользователей и их cgroup-лимитами в runtime:

```bash
# Просмотр активных сессий
loginctl list-sessions

# Ограничение ресурсов сессии (runtime)
sudo loginctl enable-lifetime <session_id>
sudo systemctl set-property --session <session_id> MemoryMax=2G TasksMax=256

# Убить все процессы сессии
sudo loginctl terminate-session <session_id>
```

## Дополнительная информация

### Технические нюансы и подводные камни

1.  **Порядок загрузки:** Файлы в `.d` директориях загружаются по алфавиту. Префикс `00-` гарантирует приоритет над `99-`.
2.  **SSH и лимиты:** Если лимиты `limits.conf` не применяются по SSH, проверьте `UsePAM yes` в `sshd_config`.
3.  **Systemd vs PAM:** Помните, что `limits.conf` **игнорируется** всеми процессами, запущенными через systemd (включая Docker контейнеры, если их рантайм управляется systemd).
4.  **Capabilities:** Для повышения жесткого лимита (Hard Limit) процессу необходима привилегия **`CAP_SYS_RESOURCE`**. Понижать жесткий лимит может любой процесс, но это действие необратимо.
5.  **Threaded лимиты:** В многопоточных приложениях `pthread_create()` может вернуть `EAGAIN` как из-за `RLIMIT_NPROC`, так и из-за `pids.max` cgroup. Диагностика должна проверять оба источника.
6.  **Заметки по RLIMIT_MEMLOCK:** Без `CAP_IPC_LOCK` лимит по умолчанию — 64 КБ. При наличии capability — `unlimited` (на уровне rlimit) или `RLIMIT_MEMLOCK` (на уровне PAM). Некоторые дистрибутивы (RHEL) понижают лимит через `pam_limits` даже для root.
7.  **Взаимодействие с seccomp:** В контейнерах с `seccomp` профилем системные вызовы `prlimit()` и `setrlimit()` могут быть запрещены, что делает невозможным динамическое изменение лимитов изнутри контейнера.
8.  **Потокобезопасность ulimit:** `ulimit` является shell builtin и его вызовы не атомарны при параллельном выполнении в одном процессе. Для скриптов используйте `prlimit` или `systemd-run`.
9.  **Взаимодействие с namespaces:**
    - **PID Namespace:** `RLIMIT_NPROC` относится к **UID в namespace**, но ядро считает глобально по всем namespace для одного UID. Запуск 100 контейнеров от одного пользователя внутри разных PID namespace все равно суммируется в общий лимит.
    - **User Namespace:** При маппинге UID в user namespace, rlimits применяются к **внешнему UID**. Внутренний root (UID 0) внутри namespace имеет те же лимиты, что и отображаемый пользователь.
    - **Mount Namespace:** `/proc/<PID>/limits` привязан к PID namespace. Внутри контейнера `cat /proc/self/limits` показывает лимиты конкретного процесса, а не хоста.
10. **systemd-analyze security:** Используйте для проверки изоляции сервиса. Низкие лимиты (`LimitNOFILE=1024`) снижают оценку безопасности.
11. **Взаимодействие с tmpfiles.d:** Для создания временных файлов (например, pipe-буферов) используйте `/etc/tmpfiles.d/`. Это не влияет на rlimits, но важно для подготовки окружения.
12. **kernel.pid_max vs pids.max:** `kernel.pid_max` — абсолютный потолок для всех PID в системе. `pids.max` — лимит для конкретной cgroup. Если `pids.max` превышает `kernel.pid_max`, новые процессы в группе получат `EAGAIN`.

### Типичные ошибки и их причины

| Ошибка | Ресурс | Причина | Решение |
| :--- | :--- | :--- | :--- |
| `Too many open files` | `RLIMIT_NOFILE` / `fs.file-max` | Исчерпан лимит дескрипторов | Увеличить `ulimit -n`, `LimitNOFILE=`, проверить `fs.nr_open` |
| `Cannot allocate memory` при `fork()` | `RLIMIT_NPROC` / `pids.max` | Исчерпан лимит задач | Увеличить `ulimit -u`, `TasksMax=`, проверить `pids.max` cgroup |
| `ENOMEM` при `mlock()` | `RLIMIT_MEMLOCK` | Мало зафиксированной памяти | Увеличить `ulimit -l`, добавить `CAP_IPC_LOCK` |
| `SIGXFSZ` при записи | `RLIMIT_FSIZE` | Превышен размер файла | Увеличить `ulimit -f` или отключить `ulimit -f unlimited` |
| `SIGXCPU` / `SIGKILL` | `RLIMIT_CPU` | Превышено время CPU | Увеличить `ulimit -t` или оптимизировать алгоритм |
| `Operation not permitted` | `CAP_SYS_RESOURCE` | Попытка повысить Hard Limit без capability | Использовать `sudo`, настроить capability в unit-файле |
| `EMFILE` при высокой нагрузке | `fs.nr_open` | Системный потолок ниже запрашиваемого | `sudo sysctl -w fs.nr_open=2097152` |
| Лимиты не применяются к systemd-сервису | PAM vs systemd | `limits.conf` игнорируется systemd | Использовать `Limit*=` в unit-файле или drop-in |
| Лимиты не применяются после перезапуска | Отсутствие `daemon-reload` | systemd не перечитал конфигурацию | Выполнить `systemctl daemon-reload` перед restart |
| Core-дампы не создаются | `LimitCORE=0` или `systemd-coredump` | Лимит или конфигурация coredump | Проверить `LimitCORE` и `/etc/systemd/coredump.conf` |

### См. также

- [**Концепции лимитов ресурсов**](./resource_limits_concepts.md) — теория и иерархия.
- [**Использование ulimit и prlimit**](./ulimit_usage.md) — команды для оперативного управления.
- [**Контрольные группы (cgroups)**](../cgroups.md) — сравнение cgroups и rlimits.
- [**PAM (Pluggable Authentication Modules)**](../../Security/pam_overview.md) — детали работы стека аутентификации.
- [**Диагностика «too many open files»](../../Diagnostics/Troubleshooting/troubleshooting_too_many_open_files.md) — практическое руководство по исправлениям.
- [**Механизм OOM Killer**](./oom_killer_mechanism.md) — последствия нехватки памяти.
