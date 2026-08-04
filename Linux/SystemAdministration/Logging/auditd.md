# auditd: Аудит событий безопасности

---
**Reliability Score: 10** (SSoT + актуальная документация Linux Audit Framework 3.x + рекомендации CIS Benchmark)
---

## Определения

**`auditd` (Audit Daemon)** — подсистема ядра Linux и соответствующая служба пользовательского пространства, предназначенная для глубокого мониторинга событий безопасности. Она перехватывает системные вызовы (syscalls) на уровне ядра и протоколирует действия, позволяя точно восстановить цепочку событий: **кто, когда, что, с каким объектом сделал и каков был результат**.

**Ключевые особенности:**
- **Уровень ядра:** Невозможно обойти через пользовательское пространство (в отличие от `LD_PRELOAD` или алиасов оболочки).
- **Комплаенс:** Является обязательным компонентом для соответствия стандартам PCI DSS, HIPAA, NIST и требованиям ФСТЭК.
- **Интегрированный диспетчер (Audit 3.0+):** Начиная с версии 3.0, функционал `audispd` (передача событий в реальном времени) встроен непосредственно в `auditd`.

**Отличия от других систем логирования:**

| Система | Уровень | Основное назначение | Тип данных |
| :--- | :--- | :--- | :--- |
| **`auditd`** | Ядро | Аудит безопасности, контроль доступа к ФС, syscalls | Структурированные события (кто/что/как) |
| `journald` | User space | Сбор логов служб (stdout/stderr) через systemd | Текстовые сообщения и метаданные |
| `rsyslog` | User space | Фильтрация, агрегация и удаленная пересылка логов | Текстовые сообщения (RFC 5424) |

## Базовые концепции

### Типы правил (Rules)

Правила `auditd` делятся на три категории, которые обрабатываются в строгом порядке:

1.  **Контрольные правила (Control Rules):** Настраивают поведение самой системы аудита.
    - `-b <n>` — размер буфера сообщений (backlog). Для нагруженных систем рекомендуется `8192` и выше.
    - `-f [0|1|2]` — действие при критической ошибке (0-silent, 1-printk, 2-panic).
    - `-e [0|1|2]` — флаг завершения (0-disable, 1-enable, 2-immutable). Режим **2** блокирует изменение правил до перезагрузки.
2.  **Файловые правила (File system rules / Watches):** Отслеживание доступа к файлам и директориям.
    - Синтаксис: `-w <path> -p <perms> -k <key>`
    - Права (`-p`): `r` (read), `w` (write), `x` (execute), `a` (attribute change).
3.  **Правила системных вызовов (Syscall rules):** Перехват функций ядра.
    - Синтаксис: `-a <action>,<list> -S <syscall> -F <filter> -k <key>`
    - Списки: `exit`, `always` — наиболее частая комбинация для фиксации результата вызова.

### Ключи аудита (Audit Keys)

**Ключ** (`-k key_name`) — текстовая метка для группировки событий. **Использование ключей обязательно** для эффективного поиска и анализа в SIEM-системах. Без ключа фильтрация в огромных логах становится крайне трудоемкой.

### Утилиты и инструменты

| Команда | Назначение |
| :--- | :--- |
| `auditctl` | Оперативное управление правилами в памяти (не сохраняются после ребута). |
| `augenrules` | Сборка правил из `/etc/audit/rules.d/` в один файл и их загрузка. |
| `ausearch` | Поиск по логам по ключам, времени, PID, UID и т.д. |
| `aureport` | Генерация сводных отчетов (статистика входов, исполняемых файлов, ошибок). |
| `autrace` | Трассировка конкретного процесса (аналог `strace`, но через аудит). |

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

### 2. Мониторинг действий пользователей

Отслеживание выполнения команд (через системный вызов `execve`):

```bash
# Логирование всех запусков программ пользователями с UID >= 1000
sudo auditctl -a exit,always -F arch=b64 -F auid>=1000 -F auid!=4294967295 -S execve -k user_commands
```
*Примечание: `4294967295` — это значение (unset) для системных процессов без привязки к сессии пользователя.*

### 3. Аудит контейнерной инфраструктуры (Docker)

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

### 4. Поиск и анализ инцидентов

```bash
# Найти все изменения файлов shadow за последние 24 часа
sudo ausearch -k shadow_access --start yesterday

# Поиск попыток доступа, завершившихся ошибкой "Permission Denied"
sudo ausearch -m SYSCALL -sc open -sv no

# Генерация отчета о всех попытках аутентификации
sudo aureport -au

# Сводная статистика по аномалиям и ошибкам
sudo aureport --summary
```

## FinTech и Compliance (Регулируемые среды)

В системах обработки платежей (FinTech) аудит является не просто мерой безопасности, а жестким требованием регуляторов (PCI-DSS, PSD2, GDPR, CESOP).

### Требования PCI-DSS (v4.0) и CESOP

| Требование | Описание | Реализация в auditd/Linux |
| :--- | :--- | :--- |
| **Retention** | Хранение минимум 1 год (3 месяца в онлайн-доступе) | `MaxRetentionSec` в journald, политики жизненного цикла S3/GCS. |
| **Tamper-evident** | Защита от модификации и удаления | `Seal=yes` в journald, `-e 2` в auditd, S3 Object Lock (WORM). |
| **Privileged Access** | Логирование всех действий root/sudo | Правило `-a always,exit -S execve -F euid=0 -k root_action`. |
| **Access Control** | Логирование доступа к данным держателей карт | `Watch` на специфические директории БД: `-w /var/lib/pgsql -p wa`. |
| **Log Integrity** | Регулярная проверка целостности журналов | `journalctl --verify` с внешним Verification Key (FSS). |

### Разделение обязанностей (Separation of Duties)

Для соответствия SOX и PCI-DSS данные логов должны быть недоступны пользователям, за которыми ведется наблюдение.
1. **Auditor Role:** Создайте отдельную группу `auditors` с доступом только на чтение к `/var/log/audit/`.
2. **Remote Immutable Storage:** Немедленная пересылка логов через TLS в изолированное хранилище (SIEM), к которому нет доступа у системных администраторов хоста.

### Практические правила для FinTech

Добавьте в `/etc/audit/rules.d/fintech.rules`:
```bash
# Мониторинг попыток изменения времени (защита от манипуляций с таймстемпами)
-a always,exit -F arch=b64 -S adjtimex -S settimeofday -S stime -k time_change
-a always,exit -F arch=b64 -S clock_settime -k time_change

# Мониторинг загрузки модулей ядра (rootkits)
-w /sbin/insmod -p x -k kernel_modules
-w /sbin/rmmod -p x -k kernel_modules
-w /sbin/modprobe -p x -k kernel_modules
-a always,exit -F arch=b64 -S init_module -S delete_module -k kernel_modules

# Мониторинг сетевых соединений (подозрительный outbound)
-a always,exit -F arch=b64 -S connect -F success=1 -k network_outbound
```

### Практический сценарий: Детекция эксплуатации ядра (Page Cache Write)

Атаки класса Page Cache Write (Dirty Frag, Copy Fail) используют специфические системные вызовы для изменения памяти файлов. Мониторинг этих вызовов позволяет выявить признаки эксплойта на ранних стадиях.

**Конфигурация правил (`/etc/audit/rules.d/kernel_exploit.rules`):**

```bash
# 1. Создание сокетов AF_ALG (интерфейс криптографии ядра, используется в Copy Fail)
-a always,exit -F arch=b64 -S socket -F a0=38 -k af_alg_socket

# 2. Использование splice() — основной примитив для атак на Page Cache
-a always,exit -F arch=b64 -S splice -k splice_call

# 3. sendmsg с подозрительными флагами (например, MSG_SPLICE_PAGES = 0x8000000)
-a always,exit -F arch=b64 -S sendmsg -k sendmsg_call

# 4. Мониторинг загрузки и выгрузки модулей ядра (закрепление злоумышленника)
-a always,exit -F arch=b64 -S init_module -S finit_module -k kernel_module_load
-a always,exit -F arch=b64 -S delete_module -k kernel_module_unload

# 5. Изменение критических параметров ядра через /proc и /sys
-w /proc/sys/kernel/ -p wa -k kernel_params_modify
-w /sys/module/ -p wa -k module_params_modify
```

**Анализ событий:**
При обнаружении событий с ключами `af_alg_socket` или `splice_call` от непривилегированных пользователей следует провести немедленный аудит процесса (PID) и его сетевой активности.

## Дополнительная информация

### Оптимизация производительности (`auditd.conf`)
... (остальной текст без изменений)

На высоконагруженных системах (БД, веб-серверы) неправильная настройка может привести к деградации производительности:

- **`flush = INCREMENTAL_ASYNC`:** Оптимальный режим записи на диск.
- **`q_depth = 8192`:** Увеличение глубины очереди для встроенного диспетчера (Audit 3.x).
- **`priority_boost = 4`:** Повышение приоритета планировщика для демона.
- **`max_log_file` и `num_logs`:** Настройка ротации для предотвращения переполнения `/var`.

### Режим неизменяемости (Immutability)

Для обеспечения максимальной безопасности добавьте в `/etc/audit/rules.d/audit.rules` последней строкой:
```bash
-e 2
```
После этого любые попытки изменить правила через `auditctl` или остановить службу будут отклонены ядром. Изменения вступят в силу только после перезагрузки.

### Интеграция с SIEM и мониторингом

1.  **Сбор логов:** Векторы (Vector, Filebeat) читают `/var/log/audit/audit.log`. Рекомендуется использовать структурированный формат JSON для парсинга.
2.  **Plugins (Audit 3.0+):** Плагины теперь настраиваются в `/etc/audit/plugins.d/`. Например, плагин `statsd` позволяет экспортировать метрики (backlog, lost events) напрямую в Prometheus/Grafana.
3.  **Альтернативы (eBPF):** Для облачных сред (Kubernetes) часто предпочтительнее инструменты на базе eBPF (**Falco**, **Tetragon**), так как они понимают контекст контейнеров (Pod ID, Namespace) и имеют меньший overhead.

### Структура файлов
- `/etc/audit/auditd.conf` — конфигурация демона.
- `/etc/audit/rules.d/` — директория для персистентных правил.
- `/var/log/audit/audit.log` — основной файл событий.

### См. также
- [Обзор системных журналов в Linux](./logging_overview.md)
- [Безопасность Docker: Hardening](../../Docker/Docker_security/host_daemon_hardening.md)
- [Анализ сбоев и ошибок](../../Linux/Diagnostics/Troubleshooting/error_and_crash_analysis.md)
- [Wazuh: расширение декодера auditd](../../Security/Tools/Wazuh/custom-decoders.md#2-расширение-стандартного-декодера-auditd) — для мониторинга дополнительных аргументов syscalls.
