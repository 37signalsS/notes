# auditd: Аудит событий безопасности

## Определения

**`auditd` (Audit Daemon)** — подсистема ядра Linux и соответствующая служба пользовательского пространства, предназначенная для глубокого мониторинга событий безопасности. Она перехватывает системные вызовы (syscalls) на уровне ядра и протоколирует действия, позволяя точно восстановить цепочку событий: **кто, когда, что, с каким объектом сделал и каков был результат**.

В отличие от стандартных средств логирования (rsyslog, systemd-journald), которые зависят от того, сообщают ли приложения о собственной активности, аудит работает на уровне ядра. Его нельзя обойти инструментами пользовательского пространства: даже если процесс скомпрометирован, его системные вызовы будут записаны (если не скомпрометировано само ядро).

### Linux Audit Framework

Архитектура подсистемы аудита состоит из нескольких компонентов:

- **Приложение:** Выполняет действия (доступ к файлам, выполнение команд), инициирующие системные вызовы (`open`, `execve`).
- **Подсистема аудита ядра:** Обнаруживает системные вызовы и генерирует события, если они соответствуют настроенным правилам. Работает в контексте ядра и не может быть отключена из пользовательского пространства без перезагрузки (при использовании режима неизменяемости).
- **`auditd`:** Получает события от ядра через файловую систему `audit` (`/proc/audit`) и записывает их на диск в структурированном формате.
- **Логи аудита:** Постоянные записи в `/var/log/audit/audit.log`, используемые для поиска и анализа.
- **`audispd` (optional):** Демон пересылки событий в реальном времени в сторонние системы (SIEM, внешние хранилища).

**Поток данных:**
```
Приложение → Системный вызов → Ядро (netlink/socket) → auditd → audit.log
                                              ↓
                                          audispd → SIEM/External
```

### Отличия от других систем логирования

| Система | Уровень | Основное назначение | Тип данных |
| :--- | :--- | :--- | :--- |
| **`auditd`** | Ядро | Аудит безопасности, контроль доступа к ФС, syscalls | Структурированные события (кто/что/как) |
| `journald` | User space | Сбор логов служб (stdout/stderr) через systemd | Текстовые сообщения и метаданные |
| `rsyslog` | User space | Фильтрация, агрегация и удаленная пересылка логов | Текстовые сообщения (RFC 5424) |

**Ключевое отличие:** `auditd` работает на уровне ядра и не может быть обхода пользовательским пространством. Даже процесс с root-привилегиями не может скрыть свои системные вызовы от аудита (если не скомпрометировано само ядро).

## Установка и начальная настройка

### Установка

Большинство современных дистрибутивов (RHEL, Rocky, Ubuntu Server) поставляются с предустановленным `auditd`. Если он отсутствует:

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install auditd audispd-plugins -y
sudo systemctl enable --now auditd

# RHEL/CentOS/Rocky
sudo dnf install audit audit-libs -y
sudo systemctl enable --now auditd
```

**Проверка статуса:**
```bash
sudo systemctl status auditd
sudo auditctl -s
# → АUID剑气无敌...
```

### Управление службой

`auditd` интегрирован с systemd. Важные аспекты управления:

```bash
# Перезагрузка правил без потери текущих
sudo systemctl reload auditd

# Перезапуск (сохраняет правила в памяти)
sudo systemctl restart auditd

# Проверка статуса
sudo systemctl status auditd
# → auditd.service - Security Auditing Service
```

**Важно:** При перезагрузке службы `auditd` правила из памяти сбрасываются. Для персистентности используйте `/etc/audit/rules.d/` и `augenrules`.

## Базовые концепции

### Типы правил (Rules)

Правила `auditd` делятся на три категории, которые обрабатываются в строгом порядке:

1.  **Контрольные правила (Control Rules):** Настраивают поведение самой системы аудита.
    - `-b <n>` — размер буфера сообщений (backlog). Для нагруженных систем рекомендуется `8192` и выше.
    - `-f [0|1|2]` — действие при критической ошибке (0 — silent, 1 — printk, 2 — panic).
    - `-e [0|1|2]` — флаг завершения (0 — disable, 1 — enable, 2 — immutable). Режим **2** блокирует изменение правил до перезагрузки.
2.  **Файловые правила (File system rules / Watches):** Отслеживание доступа к файлам и директориям.
    - Синтаксис: `-w <path> -p <perms> -k <key>`
    - Права (`-p`): `r` (read), `w` (write), `x` (execute), `a` (attribute change).
3.  **Правила системных вызовов (Syscall rules):** Перехват функций ядра.
    - Синтаксис: `-a <action>,<list> -S <syscall> -F <filter> -k <key>`
    - Списки: `exit`, `always` — наиболее частая комбинация для фиксации результата вызова.

**Порядок загрузки правил:**
Размещайте правила в пронумерованных файлах в `/etc/audit/rules.d/`. Утилита `augenrules` компилирует их в алфавитно-цифровом порядке в файл `/etc/audit/audit.rules`.

Пример структуры:
- `10-base-config.rules`
- `20-netsys.rules`
- `99-finalize.rules` (обычно содержит `-e 2`)

### Записи аудита (Audit Records)

Событие аудита может состоять из нескольких записей, объединенных временной меткой и серийным номером.
**Распространенные типы записей:**
- `SYSCALL`: Сведения о системном вызове (PID, UID, результат).
- `PATH`: Путь к файлу, участвующему в вызове.
- `EXECVE`: Аргументы запускаемого процесса.
- `USER_AUTH`: События аутентификации PAM.
- `USER_LOGIN`: Попытки входа в систему.
- `USER_CMD`: Команды, выполненные через `sudo`.
- `CONFIG_CHANGE`: Изменение конфигурации самого аудита.
- `PROCTITLE`: Полное имя процесса (аргументы execve).
- `CWD`: Рабочая директория процесса.
- `AVC`: Отказы SELinux.

**Важные поля записей:**
- `auid` (Audit UID): **Критически важное поле**. Идентифицирует пользователя, который изначально вошел в систему. Остается неизменным даже после `su` или `sudo`.
- `uid/gid`: Эффективные ID на момент события.
- `comm`: Имя команды (обрезается до 15 символов).
- `exe`: Полный путь к исполняемому файлу.
- `key`: Метка правила.
- `success`: Результат системного вызова (`yes`/`no`).
- `arch`: Архитектура (`b64` или `b32`).
- `a0`-`a6`: Аргументы системного вызова.

### Ключи аудита (Audit Keys)

**Ключ** (`-k key_name`) — текстовая метка для группировки событий. **Использование ключей обязательно** для эффективного поиска и анализа в SIEM-системах. Без ключа фильтрация в огромных логах становится крайне трудоемкой.

**Рекомендации по именованию ключей:**
- Используйте snake_case или kebab-case
- Добавляйте префикс с контекстом: `ssh_`, `docker_`, `kernel_`, `user_`
- Будьте краткими, но описательными: `ssh_failed_auth`, `docker_socket_access`

### Утилиты и инструменты

| Команда | Назначение |
| :--- | :--- |
| `auditctl` | Оперативное управление правилами в памяти (не сохраняются после ребута). |
| `augenrules` | Сборка правил из `/etc/audit/rules.d/` в один файл и их загрузка. |
| `ausearch` | Поиск по логам по ключам, времени, PID, UID и т.д. |
| `aureport` | Генерация сводных отчетов (статистика входов, исполняемых файлов, ошибок). |
| `autrace` | Трассировка конкретного процесса (аналог `strace`, но через аудит). |
| `audit2allow` | Генерация правил SELinux на основе отказов AVC (требует `policycoreutils-python-utils`). |
| `audit2why` | Объяснение причин отказов AVC. |

### Конфигурация демона (`auditd.conf`)

Основные параметры для высоконагруженных систем в `/etc/audit/auditd.conf`:

| Параметр | Рекомендация | Описание |
| :--- | :--- | :--- |
| `log_format` | `ENRICHED` | Добавляет расширенные метаданные (имена пользователей, syscall), упрощает чтение без `ausearch -i`. |
| `flush` | `INCREMENTAL_ASYNC` | Асинхронная запись на диск (снижает I/O overhead). |
| `max_log_file` | `50` (МБ) | Максимальный размер одного файла лога. |
| `num_logs` | `5-10` | Количество хранимых ротированных файлов. |
| `max_log_file_action` | `ROTATE` | Автоматическая ротация при достижении лимита. |
| `space_left_action` | `SYSLOG` | Действие при нехватке места на диске. |
| `admin_space_left_action` | `SUSPEND` | Приостановка записи при критическом дефиците места (защищает систему от сбоя из-за переполнения ФС). |
| `priority_boost` | `4` или `8` | Приоритет потока auditd. Для высоконагруженных систем установите `4` или выше. |
| `freq` | `50` | Частота синхронизации буфера на диск (в секундах). |
| `write_logs` | `yes` | Запись логов на диск. |
| `log_file` | `/var/log/audit/audit.log` | Путь к файлу логов. |
| `log_group` | `root` или `audit` | Группа-владелец файла логов. |
| `tcp_listen_queue` | `5` | Размер очереди для сетевых подключений (если используется `audispd` с сетью). |
| `tcp_max_per_addr` | `1` | Максимум подключений с одного адреса. |
| `tcp_client_max_idle` | `0` | Таймаут простоя клиентов (0 = бесконечно). |
| `q_depth` | `2000` | Глубина очереди событий в пользовательском пространстве. |
| `overflow_action` | `SYSLOG` | Действие при переполнении очереди. |
| `max_restarts` | `10` | Максимум перезапусков плагинов. |

**Пример оптимизированного `auditd.conf` для production:**
```ini
# /etc/audit/auditd.conf
log_format = ENRICHED
flush = INCREMENTAL_ASYNC
max_log_file = 50
num_logs = 10
max_log_file_action = ROTATE
space_left = 500
space_left_action = SYSLOG
admin_space_left = 50
admin_space_left_action = SUSPEND
priority_boost = 4
freq = 50
write_logs = yes
log_file = /var/log/audit/audit.log
log_group = root
tcp_listen_queue = 5
q_depth = 2000
overflow_action = SYSLOG
```

### Удаленное логирование

В современных дистрибутивах (Audit 3.x) удаленная пересылка настраивается через плагины в `/etc/audit/plugins.d/`.

1.  Включите плагин `au-remote` (установите `active = yes`).
2.  Настройте адрес сервера в `/etc/audit/audisp-remote.conf`.
3.  Для шифрования используйте `krb5` или туннелирование через TLS.

**Пример конфигурации `/etc/audit/plugins.d/au-remote.conf`:**
```ini
active = yes
direction = out
path = /usr/sbin/audisp-remote
type = always
args = /etc/audisp/audisp-remote.conf
```

**Пример `/etc/audit/audisp-remote.conf`:**
```ini
remote_server = audit-server.internal
port = 60
use_alternate_port = no
local_port = 60
transport = tls
mode = push
```

## Практические сценарии

### 1. Мониторинг критических конфигураций

Отслеживание попыток несанкционированного изменения системных настроек:

```bash
# Пароли и группы
sudo auditctl -w /etc/shadow -p wa -k shadow_access
sudo auditctl -w /etc/passwd -p wa -k user_db_modification

# Конфигурация аутентификации и sudo
sudo auditctl -w /etc/sudoers -p wa -k priv_escalation_config
sudo auditctl -w /etc/pam.d/ -p wa -k pam_config_change

# Сетевые настройки и SSH
sudo auditctl -w /etc/ssh/sshd_config -p wa -k sshd_config
sudo auditctl -w /etc/network/ -p wa -k network_config
```

**Ожидаемый результат:**
```bash
# После изменения sshd_config:
sudo ausearch -k sshd_config -i
# → type=CONFIG_CHANGE msg=audit(...): auid=1000 uid=0 gid=0 exe="/usr/sbin/sshd" key="sshd_config"
```

### 2. Мониторинг действий пользователей

Отслеживание выполнения команд (через системный вызов `execve`):

```bash
# Логирование всех запусков программ пользователями с UID >= 1000
sudo auditctl -a exit,always -F arch=b64 -F auid>=1000 -F auid!=4294967295 -S execve -k user_commands
```
*Примечание: `4294967295` — это значение (unset) для системных процессов без привязки к сессии пользователя.*

**Ожидаемый результат:**
```bash
# После выполнения команды пользователем:
sudo ausearch -k user_commands -i --start recent
# → type=EXECVE msg=audit(...): argc=3 a0="sudo" a1="apt" a2="update"
```

### 3. Снижение шума (Правила исключения)

Чтобы избежать переполнения логов малоценными событиями, используйте правила с действием `never`. Они должны располагаться **выше** правил `always` для тех же объектов.

```bash
# Игнорировать системные процессы без auid
-a never,exit -F arch=b64 -F auid=unset -k ignore_unset_auid

# Игнорировать активность самого демона auditd
-a never,exit -F exe=/sbin/auditd

# Игнорировать шумные системные утилиты (использовать с осторожностью)
-a never,exit -F path=/etc/mtab
-a never,exit -F arch=b64 -F exe=/lib/systemd/systemd-journald
```

### 4. Мониторинг удаления файлов

Для отслеживания удаления и переименования файлов:

```bash
# Аудит всех операций удаления/переименования
sudo auditctl -a always,exit -F arch=b64 -S unlink -S unlinkat -S rename -S renameat -F auid>=1000 -F auid!=-1 -k file_deletion
```

### 5. Мониторинг изменения прав доступа

Для отслеживания изменений прав доступа к файлам:

```bash
# Аудит chmod/chown
sudo auditctl -a always,exit -F arch=b64 -S chmod -S fchmod -S fchmodat -F auid>=1000 -F auid!=-1 -k perm_change
sudo auditctl -a always,exit -F arch=b64 -S chown -S fchown -S lchown -S fchownat -F auid>=1000 -F auid!=-1 -k perm_change
```

### 6. Мониторинг ошибок доступа (подозрение на сканирование)

Для обнаружения подозрительной активности (брутфорс, сканирование):

```bash
# Неудачные попытки открытия файлов
sudo auditctl -a always,exit -F arch=b64 -S open -S openat -S truncate -S ftruncate -F exit=-EACCES -F auid>=1000 -k access_denied
sudo auditctl -a always,exit -F arch=b64 -S open -S openat -S truncate -S ftruncate -F exit=-EPERM -F auid>=1000 -k access_denied
```

**Анализ:**
```bash
# Поиск подозрительной активности за последний час
sudo ausearch -k access_denied --start recent -i | grep -E "auid=|comm=" | sort | uniq -c | sort -rn
# → 142 /usr/sbin/sshd
# → 89 /usr/bin/sudo
```

### 7. Аудит контейнерной инфраструктуры (Docker)

Рекомендованный набор правил согласно CIS Docker Benchmark:

```bash
# Бинарные файлы и сокет (критично для защиты хоста)
sudo auditctl -w /usr/bin/dockerd -p wa -k docker_activity
sudo auditctl -w /var/run/docker.sock -p wa -k docker_socket

# Конфигурационные файлы
sudo auditctl -w /etc/docker -p wa -k docker_conf
sudo auditctl -w /etc/default/docker -p wa -k docker_conf
sudo auditctl -w /lib/systemd/system/docker.service -p wa -k docker_conf
```

### 8. Специальные сценарии для DevOps/SRE

#### Мониторинг изменений в CI/CD конфигурациях

```bash
# GitLab Runner
sudo auditctl -w /etc/gitlab-runner/ -p wa -k cicd_runner_config
sudo auditctl -w /etc/gitlab/gitlab.rb -p wa -k gitlab_config

# Jenkins
sudo auditctl -w /etc/default/jenkins -p wa -k jenkins_config
sudo auditctl -w /var/lib/jenkins/ -p wa -k jenkins_jobs

# Анализ изменений
sudo ausearch -k cicd_runner_config -ts today -i
```

#### Мониторинг системного времени

```bash
# Аудит изменений времени
sudo auditctl -a always,exit -F arch=b64 -S adjtimex -S settimeofday -S clock_settime -k time_change
sudo auditctl -w /etc/localtime -p wa -k timezone_change
```

#### Мониторинг загрузки модулей ядра

Детальные правила для отслеживания загрузки модулей см. в [Модули ядра Linux](../../Core/kernel/kernel_modules.md).

#### Мониторинг пользовательских процессов

Детальные сценарии учета процессов см. в [Практические сценарии мониторинга процессов](../../Core/processes/practical_scenarios.md#сценарий-14-учет-процессов-auditd).

#### Аудит событий SSH

Детальные правила для SSH см. в [SSH — лучшие практики укрепления безопасности](../../Security/ssh/server/ssh_hardening_best_practices.md#аудит-событий-ssh-through-auditd).

#### Мониторинг изменений файлов пользователей и групп

Детальные правила см. в [Файлы конфигурации пользователей и групп](../Users/users_config_files.md#мониторинг-изменений-auditd).

## Поиск и анализ (ausearch)

Утилита `ausearch` позволяет эффективно фильтровать гигабайты логов.

| Фильтр | Команда | Описание |
| :--- | :--- | :--- |
| **По ключу** | `ausearch -k ssh_config` | События, помеченные конкретным ключом. |
| **По файлу** | `ausearch -f /etc/passwd` | Доступ к конкретному файлу или директории. |
| **По пользователю** | `ausearch -ua alice` | События, инициированные пользователем (по имени или UID). |
| **По времени** | `ausearch -ts today` | События за сегодня (также `recent`, `yesterday`). |
| **По результату** | `ausearch -sv no` | Только неудачные попытки (ошибки доступа). |
| **По PID** | `ausearch -p 1234` | Все действия конкретного процесса. |
| **Интерпретация** | `ausearch -k key -i` | Преобразование UID в имена, syscall в названия. |
| **Необработанный вывод** | `ausearch -k key --raw` | Сырые данные для парсинга. |
| **По типу записи** | `ausearch -m SYSCALL` | Только записи определенного типа. |

**Примеры сложных запросов:**
```bash
# Что делал sudo за сегодня?
sudo ausearch -k exec -x /usr/bin/sudo --start today -i

# Поиск попыток изменения прав пользователем с UID 1000
sudo ausearch -k perm_mod -ui 1000 -i

# Поиск всех неудачных попыток входа
sudo ausearch -m USER_LOGIN -sv no --start recent -i

# Поиск изменений критических файлов за последний час
sudo ausearch -k shadow_access -ts recent -i

# Поиск всех событий для конкретного PID
sudo ausearch -p 1234 -i --start recent
```

### Валидация правил

Перед применением правил в production проверяйте их корректность:

```bash
# 1. Проверка синтаксиса
sudo auditctl -s
# → Audit enabled

# 2. Просмотр активных правил
sudo auditctl -l

# 3. Тестирование правила
sudo auditctl -w /etc/testfile -p wa -k test_rule
echo "test" | sudo tee /etc/testfile
sudo ausearch -k test_rule -i
# → type=SYSCALL msg=audit(...): key="test_rule"

# 4. Удаление тестового правила
sudo auditctl -w /etc/testfile -p wa -k test_rule
```

## Формирование отчетов (aureport)

`aureport` создает сводные статистические отчеты для быстрого обнаружения аномалий.

| Отчет | Команда | Описание |
| :--- | :--- | :--- |
| **Сводка** | `aureport --summary` | Общая статистика по всем типам событий. |
| **Входы** | `aureport -au` | Отчет о попытках аутентификации и входах. |
| **Программы** | `aureport -x --summary` | Топ запущенных исполняемых файлов. |
| **Файлы** | `aureport -f -i` | Статистика доступа к файлам. |
| **Аккаунты** | `aureport -m` | Изменения учетных записей (создание/удаление пользователей). |
| **Ошибки** | `aureport -au --failed` | Только неудачные попытки входа. |
| **Сессии** | `aureport -u` | Активность пользователей. |
| **События** | `aureport -e` | Хронология событий. |
| **Модули** | `aureport -k` | Статистика по ключам. |

**Пример анализа:**
```bash
# Топ-10 пользователей по активности
sudo aureport -u --summary | head -20

# Поиск подозрительных процессов
sudo aureport -x --summary | grep -E "nc|ncat|socat|bash.*tmp"
```

## Комплексный набор правил (Production-ready)

Ниже приведен эталонный набор правил для усиленной защиты сервера. Разместите их в `/etc/audit/rules.d/90-production.rules`.

```bash
# --- 1. Идентификация пользователей ---
-w /etc/group -p wa -k identity
-w /etc/passwd -p wa -k identity
-w /etc/gshadow -p wa -k identity
-w /etc/shadow -p wa -k identity
-w /etc/nsswitch.conf -p wa -k identity

# --- 2. Повышение привилегий ---
-w /etc/sudoers -p wa -k scope
-w /etc/sudoers.d/ -p wa -k scope
-a always,exit -F arch=b64 -S setuid -F a0=0 -F exe=/usr/bin/su -k priv_esc

# --- 3. Изменение прав и владельцев ---
-a always,exit -F arch=b64 -S chmod,fchmod,fchmodat -F auid>=1000 -F auid!=-1 -k perm_mod
-a always,exit -F arch=b64 -S chown,fchown,lchown,fchownat -F auid>=1000 -F auid!=-1 -k perm_mod

# --- 4. Ошибки доступа (подозрение на сканирование) ---
-a always,exit -F arch=b64 -S open,openat,truncate,ftruncate -F exit=-EACCES -F auid>=1000 -k access
-a always,exit -F arch=b64 -S open,openat,truncate,ftruncate -F exit=-EPERM -F auid>=1000 -k access

# --- 5. Удаление файлов ---
-a always,exit -F arch=b64 -S unlink,unlinkat,rename,renameat -F auid>=1000 -F auid!=-1 -k delete

# --- 6. Модули ядра ---
-w /sbin/insmod -p x -k modules
-w /sbin/rmmod -p x -k modules
-w /sbin/modprobe -p x -k modules
-a always,exit -F arch=b64 -S init_module,finit_module,delete_module -k modules

# --- 7. Сетевая конфигурация ---
-a always,exit -F arch=b64 -S sethostname,setdomainname -k network_modifications
-w /etc/hosts -p wa -k network_modifications
-w /etc/network/ -p wa -k network_modifications

# --- 8. Время и дата ---
-a always,exit -F arch=b64 -S adjtimex,settimeofday,clock_settime -k time_change
-w /etc/localtime -p wa -k time_change

# --- 9. Двухarchitectural поддержка (32/64 бита) ---
# Для 32-битных совместимых библиотек на 64-битных системах
-a always,exit -F arch=b32 -S execve -F auid>=1000 -F auid!=-1 -k user_commands_32
```

**Применение правил:**
```bash
# Компиляция и загрузка правил
sudo augenrules --load

# Проверка активных правил
sudo auditctl -l

# Сохранение текущих правил в файл (для резервного копирования)
sudo auditctl -s > /tmp/audit_status.txt
sudo auditctl -l > /tmp/audit_rules.txt
```

## Соответствие стандартам (Compliance)

В критических системах (FinTech, госсектор) аудит является обязательным требованием регуляторов (PCI DSS, HIPAA, GDPR, ФСТЭК).

### Требования PCI DSS (v4.0) и CESOP

| Требование | Описание | Реализация в Linux |
| :--- | :--- | :--- |
| **Retention** | Хранение минимум 1 год | Ротация логов и выгрузка во внешнее хранилище (локальный SIEM). |
| **Tamper-evident** | Защита от модификации | Использование режима неизменяемости (`-e 2`) и удаленного логирования. |
| **Privileged Access** | Аудит действий root/sudo | Правило `-a always,exit -S execve -F euid=0 -k root_action`. |
| **Access Control** | Контроль доступа к данным | Мониторинг ФС для директорий БД: `-w /var/lib/pgsql -p wa`. |
| **Log Integrity** | Проверка целостности | Использование внешних SIEM для сравнения локальных и удаленных копий. |

### Разделение обязанностей (Separation of Duties)

Для соответствия SOX и PCI DSS данные логов должны быть недоступны пользователям, за которыми ведется наблюдение.

1.  **Роль аудитора:** Создание отдельной группы `auditors` с доступом только на чтение к `/var/log/audit/`.
    ```bash
    sudo groupadd auditors
    sudo usermod -aG auditors alice
    sudo chgrp auditors /var/log/audit/
    sudo chmod 750 /var/log/audit/
    ```
2.  **Локальное хранилище:** Настройка выделенного сервера для приема логов через `audispd` с `au-remote` плагином.

### Проверка соответствия CIS

```bash
# Проверка: включен ли auditd
sudo systemctl is-active auditd
# → active

# Проверка: настроены ли базовые правила
sudo auditctl -l | grep -E "shadow|passwd|sudo"
# → -w /etc/shadow -p wa -k shadow_access

# Проверка: включен ли режим неизменяемости
sudo auditctl -s | grep enabled
# → enabled 2 (immutable)
```

## Анализ журналов и формат событий

Основной лог-файл `/var/log/audit/audit.log` содержит структурированные записи. Пример события `SYSCALL`:

```text
type=SYSCALL msg=audit(1691585421.123:456): arch=c000003e syscall=2 success=yes exit=3 a0=7ffed1... a1=0 a2=1fffffffffff a3=0 items=1 ppid=1234 pid=5678 auid=1000 uid=1000 gid=1000 euid=1000 suid=1000 fsuid=1000 egid=1000 sgid=1000 fsgid=1000 tty=pts0 ses=1 comm="cat" exe="/usr/bin/cat" subj=unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023 key="shadow_access"
```

**Разбор ключевых полей:**
- **`type`**: Тип записи (`SYSCALL`, `CWD`, `PATH`, `AVC`).
- **`msg=audit(timestamp:ID)`**: Временная метка и уникальный идентификатор события.
- **`arch`**: Архитектура системы в шестнадцатеричном формате.
- **`syscall`**: Номер системного вызова.
- **`success`**: Результат выполнения (`yes/no`).
- **`exit`**: Код возврата.
- **`auid` (Audit User ID)**: ID пользователя, который изначально вошел в систему (не меняется при `su`/`sudo`).
- **`uid/euid`**: Реальный и эффективный ID пользователя.
- **`comm/exe`**: Имя команды и путь к исполняемому файлу.
- **`key`**: Метка правила, сгенерировавшего событие.
- **`subj`**: Контекст SELinux (если применимо).
- **`items`**: Количество связанных записей (PATH, CWD).

### Декодирование событий

Для преобразования числовых ID в читаемые имена используйте флаг `-i`:

```bash
sudo ausearch -k shadow_access -i
# → type=SYSCALL msg=audit(1691585421.123:456): auid=alice uid=alice gid=alice exe="/usr/bin/cat" key="shadow_access"
```

Для экспорта в JSON используйте `--format=json` (Audit 3.x+):

```bash
sudo ausearch -k shadow_access --format=json | jq .
```

## Продвинутые сценарии и безопасность

### Детекция эксплуатации ядра (Page Cache Write)

Атаки класса Page Cache Write (Dirty Frag, Copy Fail) используют специфические системные вызовы для изменения памяти файлов.

**Правила для `/etc/audit/rules.d/kernel_exploit.rules`:**

```bash
# Использование splice() — основной примитив для атак на Page Cache
-a always,exit -F arch=b64 -S splice -k splice_call

# Создание сокетов AF_ALG (интерфейс криптографии ядра)
-a always,exit -F arch=b64 -S socket -F a0=38 -k af_alg_socket

# Изменение критических параметров ядра через /proc и /sys
-w /proc/sys/kernel/ -p wa -k kernel_params_modify
-w /sys/module/ -p wa -k module_params_modify
```

### Режим неизменяемости (Immutability)

Для предотвращения отключения аудита злоумышленником, получившим root-права, добавьте в конец файла правил:

```bash
# /etc/audit/rules.d/99-finalize.rules
-e 2
```

Это блокирует изменение правил и остановку службы до полной перезагрузки системы.

**Проверка режима:**
```bash
sudo auditctl -s
# → enabled 2 (immutable)
```

**Выход из режима неизменяемости:**
```bash
# Временно до перезагрузки
sudo auditctl -e 0
# Удалите правило -e 2 из правил и перезагрузитесь
```

### Аудит событий SELinux

Для отслеживания отказов SELinux и изменений политики используются отдельные правила. Детали см. в [SELinux: Аудит событий через auditd](../../Security/Mechanisms/SELinux.md#13-аудит-событий-through-auditd).

### Аудит загрузки модулей ядра

Для отслеживания загрузки модулей ядра используются отдельные правила. Детали см. в [Модули ядра Linux](../../Core/kernel/kernel_modules.md#аудит-through-auditd).

## Настройка и оптимизация

### Конфигурация демона (`auditd.conf`)

Основные параметры для высоконагруженных систем:

- **`log_format = ENRICHED`**: (Рекомендуется) Добавляет в лог расширенные метаданные (имена пользователей, syscall), что упрощает чтение без `ausearch -i`.
- **`flush = INCREMENTAL_ASYNC`**: Асинхронная запись на диск (снижает I/O overhead).
- **`max_log_file` (МБ)**: Максимальный размер одного файла лога.
- **`num_logs`**: Количество хранимых ротированных файлов.
- **`max_log_file_action = ROTATE`**: Автоматическая ротация при достижении лимита.
- **`space_left_action = SYSLOG`**: Действие при нехватке места на диске.
- **`admin_space_left_action = SUSPEND`**: Приостановка записи при критическом дефиците места (защищает систему от сбоя из-за переполнения ФС).
- **`priority_boost`**: Приоритет потока auditd. Для высоконагруженных систем установите `4` или выше.
- **`freq`**: Частота синхронизации буфера на диск (в секундах).

### Удаленное логирование

В современных дистрибутивах (Audit 3.x) удаленная пересылка настраивается через плагины в `/etc/audit/plugins.d/`.

1.  Включите плагин `au-remote` (установите `active = yes`).
2.  Настройте адрес сервера в `/etc/audit/audisp-remote.conf`.
3.  Для шифрования используйте `krb5` или туннелирование через TLS.

## Интеграция с локальным SIEM

Для централизации логов аудита без облачных технологий используйте локальные решения:

### Интеграция с Wazuh

Wazuh может собирать и анализировать логи auditd:

```bash
# Установка агента Wazuh на целевой хост
curl -so wazuh-agent.deb https://packages.wazuh.com/4.x/apt/pool/main/w/wazuh/wazuh-agent_4.7.0-1_amd64.deb
sudo dpkg -i wazuh-agent.deb

# Настройка агента для сбора auditd логов
# /var/ossec/etc/ossec.conf
<ossec_config>
  <localfile>
    <log_format>audit</log_format>
    <location>/var/log/audit/audit.log</location>
  </localfile>
</ossec_config>
```

### Интеграция с ELK Stack (локально)

```bash
# Настройка Filebeat для сбора audit логов
# /etc/filebeat/filebeat.yml
- type: log
  enabled: true
  paths:
    - /var/log/audit/audit.log
  json.keys_under_root: true
  json.add_error_key: true
```

### Интеграция через audispd

Используйте плагин `audispd` для пересылки событий в реальном времени:

```bash
# /etc/audit/plugins.d/au-remote.conf
active = yes
direction = out
path = /usr/sbin/audisp-remote
type = always
args = /etc/audisp/audisp-remote.conf
```

## Устранение неполадок

### Мониторинг потерянных событий (Lost Events)

Потерянные события возникают при переполнении буферов или высокой нагрузке на диск.
Проверьте текущее состояние:
```bash
sudo auditctl -s
# Ищите поле 'lost'. В исправной системе оно должно быть равно 0.
```

**Решение при `lost > 0`:**
1.  **Увеличение буфера backlog**: Установите `-b 16384` (или выше) в `/etc/audit/rules.d/10-base-config.rules`.
2.  **Оптимизация правил**: Удалите избыточные правила и слишком шумные системные вызовы.
3.  **Повышение приоритета**: Установите `priority_boost = 4` или `8` в `auditd.conf`.
4.  **Проверка диска**: Убедитесь, что I/O не является бутылочным горлышком.

### Частые ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `audit: backlog limit exceeded` | Буфер переполнен | Увеличить `-b` в правилах, оптимизировать правила |
| `auditd: no space left on device` | Диск заполнен | Настроить ротацию, увеличить `num_logs` |
| `auditd: audit_backlog_limit` | Слишком маленький буфер | Увеличить `-b 8192` или выше |
| `auditd: cannot open audit socket` | Ядро не поддерживает audit | Проверить `CONFIG_AUDIT` в ядре |
| `auditd: rule not found` | Неправильный синтаксис правила | Проверить синтаксис через `auditctl -l` |
| `ausearch: no events` | Правило не сработало | Проверить `auditctl -s`, убедиться что аудит включен |
| `auditd: permission denied` | Недостаточно прав | Запускать через `sudo` |
| `auditd: kernel audit interface not found` | audit не загружен в ядре | Проверить `cat /proc/net/audit` |

### Диагностика производительности

```bash
# Проверка размера логов
du -sh /var/log/audit/
# → 2.1G    /var/log/audit/

# Проверка скорости роста
sudo tail -f /var/log/audit/audit.log | pv -lri30 > /dev/null
# → 1500 lines/s

# Мониторинг потерь в реальном времени
watch -n1 'sudo auditctl -s | grep lost'
# → lost 0
```

### Восстановление после сбоя

Если `auditd` перестал записывать логи:

```bash
# 1. Проверка статуса
sudo systemctl status auditd

# 2. Проверка диска
df -h /var/log/audit/

# 3. Проверка буфера
sudo auditctl -s

# 4. Перезагрузка службы
sudo systemctl restart auditd

# 5. Проверка логирования
sudo ausearch -k test_rule -i --start recent
```

## Лучшие практики

1.  **Принцип необходимости**: Не пытайтесь логировать абсолютно всё. Это создает шум и нагрузку. Сосредоточьтесь на критических активах.
2.  **Использование ключей**: Всегда добавляйте `-k`. Это база для любого расследования.
3.  **Отслеживание auid**: При анализе всегда ориентируйтесь на `auid`, так как `uid` может быть подменен через `sudo`.
4.  **Правила для двух архитектур**: На 64-битных системах всегда добавляйте правила для `arch=b64` и `arch=b32` (для совместимости с 32-битными процессами).
5.  **Неизменяемость (Immutability)**: Используйте `-e 2` в production-средах, чтобы предотвратить отключение аудита злоумышленником.
6.  **Централизация**: Пересылайте логи в локальный SIEM. Локальные логи на скомпрометированном хосте могут быть удалены.
7.  **Регулярный аудит**: Сбор данных бесполезен без их периодического анализа через `aureport`.
8.  **Тестирование правил**: Всегда тестируйте правила на staging-среде перед production.
9.  **Ротация логов**: Настройте `max_log_file` и `num_logs` для предотвращения переполнения диска.
10. **Мониторинг потерь**: Регулярно проверяйте поле `lost` в `auditctl -s`.

## Безопасность и защита логов

### Защита от модификации

```bash
# Установка атрибута immutable на audit.log (дополнительная защита)
sudo chattr +i /var/log/audit/audit.log

# Настройка прав доступа
sudo chown root:root /var/log/audit/audit.log
sudo chmod 640 /var/log/audit/audit.log
sudo chgrp audit /var/log/audit/
sudo chmod 750 /var/log/audit/
```

### Проверка целостности логов

```bash
# Хэширование логов для проверки целостности
sudo sha256sum /var/log/audit/audit.log > /var/log/audit/audit.log.sha256

# Проверка
sudo sha256sum -c /var/log/audit/audit.log.sha256
# → /var/log/audit/audit.log: OK
```

## Дополнительная информация

### Структура файлов

- `/etc/audit/auditd.conf` — конфигурация демона.
- `/etc/audit/rules.d/` — директория для персистентных правил.
- `/etc/audit/audit.rules` — скомпилированные правила (генерируется `augenrules`).
- `/var/log/audit/audit.log` — основной файл событий.
- `/etc/audit/plugins.d/` — конфигурация плагинов `audispd`.
- `/etc/audit/audisp-remote.conf` — конфигурация удаленного аудита.

### См. также

- [Обзор системных журналов в Linux](./logging_overview.md)
- [Безопасность Docker: Hardening](../../../Docker/Docker_security/host_daemon_hardening.md)
- [Мониторинг ядра через Wazuh](../../../Security/Tools/Wazuh/kernel_monitoring.md)
- [SELinux: Аудит событий через auditd](../../Security/Mechanisms/SELinux.md#13-аудит-событий-through-auditd)
- [Мониторинг загрузки модулей ядра](../../Core/kernel/kernel_modules.md#аудит-through-auditd)
- [Учет процессов (auditd)](../../Core/processes/practical_scenarios.md#сценарий-14-учет-процессов-auditd)
- [Аудит событий SSH](../../Security/ssh/server/ssh_hardening_best_practices.md#аудит-событий-ssh-through-auditd)
- [Мониторинг изменений файлов пользователей](../Users/users_config_files.md#мониторинг-изменений-auditd)
