# Мониторинг безопасности контейнеров в Runtime

**Актуально для:** Docker Engine 29.x. eBPF-инструменты (Falco 0.44.x, Tetragon) требуют ядра Linux 5.4+ с включённым `CONFIG_BPF_JIT` и `CONFIG_BPF_LSM`.

Данный документ описывает подходы к непрерывному наблюдению за состоянием запущенных контейнеров для обнаружения аномалий, атак и отклонений от эталонного состояния в реальном времени. Runtime Security Monitoring дополняет статическую проверку образов (сканеры уязвимостей, политики Admission Control) защитой на этапе выполнения, когда традиционные средства перестают быть эффективны.

## Предварительные требования

- **ОС:** Linux с ядром 5.4+ (требуется для eBPF CO-RE и Modern BPF driver). RHEL/CentOS 8+, Debian 11+, Ubuntu 20.04+.
- **Docker Engine:** 29.x. Docker 28.x и ранее достигли EOL (май 2026) и не получают исправлений безопасности.
- **eBPF:** `net.core.bpf_jit_enable=1`, `CONFIG_BPF_JIT=y`, `CONFIG_BPF_LSM=y` в ядре. Проверить: `sysctl -n net.core.bpf_jit_enable` и `ls /sys/kernel/tracing`.
- **Инструменты:** `auditd`, `jq`, `docker` CLI.

## Определения

**Мониторинг безопасности в Runtime (Runtime Security Monitoring)** — процесс непрерывного наблюдения за поведением запущенных контейнеров для выявления аномалий, подозрительной активности и несанкционированного доступа после этапа развертывания.

**eBPF (Extended Berkeley Packet Filter)** — технология ядра Linux для глубокого мониторинга системных вызовов, сетевых пакетов и файловых операций с минимальными накладными расходами. Позволяет перехватывать события до того, как они будут обработаны стандартными механизмами ОС. Подробнее см. в [**eBPF — виртуальная машина ядра**](../../Linux/Core/kernel/ebpf.md).

**Обнаружение и предотвращение дрейфа (Drift Detection & Prevention)** — выявление и блокировка изменений в файловой системе или процессах контейнера, которые отличают его от исходного состояния образа (например, запуск `sh` в контейнере без shell или модификация бинарных файлов).

**Runtime SBOM (Dynamic SBOM)** — актуализируемый в реальном времени перечень компонентов, который сопоставляет статический состав образа с фактически загруженными в память библиотеками и исполняемым кодом.

**Container Escape** — класс атак, при которых злоумышленник выходит за границы изоляции контейнера (namespaces, cgroups) и получает доступ к хосту или другим контейнерам. Обнаружение строится на мониторинге нетипичных mount-points (`/var/run/docker.sock`, `/proc`, `/sys`), системных вызовов и загрузки модулей ядра.

**Fileless Malware** — вредоносный код, который загружается в память без сохранения на диск. В контейнерах часто использует системный вызов `memfd_create` для запуска кода в RAM, что позволяет обходить файловую систему, антивирусное сканирование и файловые аудиторские правила.

**Execution Drift** — запуск бинарных файлов, скриптов или библиотек, не входящих в исходный образ контейнера. Включает как намеренные изменения (hot patches), так и инъекции кода (запуск `sh`, `curl`, `wget` из-под приложения).

**Privilege Escalation** — попытка получить повышенные привилегии через SUID-бинарники, избыточные capabilities (`CAP_SYS_ADMIN`, `CAP_SYS_PTRACE`), эксплуатацию уязвимостей ядра или злоупотребление группой `docker` на хосте.

**LSM (Linux Security Modules)** — подсистема ядра Linux, реализующая обязательный контроль доступа (MAC). Включает AppArmor (Ubuntu/Debian) и SELinux (RHEL/CentOS). Используется для принудительного ограничения действий процессов на уровне ядра, дополняя Seccomp и Capabilities.

## Базовые концепции

### Проблема «слепой зоны» стандартного логирования

Стандартные системные логи хоста (`/var/log/syslog`) и Docker (`docker logs`) не обеспечивают достаточной видимости для форензики. При совершении побега из контейнера (**container escape**) злоумышленник действует в контексте ядра, где `docker logs` (stdout/stderr) бесполезны. Современный мониторинг требует анализа системных вызовов (syscalls) с сохранением контекста контейнера (Container ID, Pod Name, Namespace).

### Модели мониторинга

1.  **Агентский (Agent-based):** Установка специализированного ПО (например, Wazuh-agent, Falco в контейнере) или запуск DaemonSet в K8s. Обеспечивает максимальную детализацию, но увеличивает потребление ресурсов.
2.  **Безагентский (Agentless / Sidecar-less):** Использование eBPF-зондов на уровне хоста. Инструмент (Tetragon, Falco) «слушает» ядро и видит активность всех контейнеров без необходимости внедрения внутрь них. Это стандарт для высоконагруженных сред в 2026 году.

### Инструментарий и уровни защиты

| Уровень | Инструмент | Метод | Назначение |
| :--- | :--- | :--- | :--- |
| **Уровень 1: Инфраструктурный аудит** | `docker events`, Docker Bench | Management Plane события | Отслеживание изменений в жизненном цикле (создание, удаление, exec) |
| **Уровень 2: Обнаружение (Detection)** | Falco, auditd, Wazuh | eBPF / auditd syscall monitoring | Анализ потока системных вызовов и генерация алертов на основе правил |
| **Уровень 3: Предотвращение (Enforcement)** | Tetragon (K8s), Falco + systemd | eBPF LSM | Мгновенная блокировка запрещенных действий (например, `kill` процесса при попытке записи в `/etc/shadow`) |

**Tetragon** — это инструмент Kubernetes, требующий Cilium CNI. Для Docker-сред без K8s используйте Falco с Modern eBPF driver или kernel module. Подробнее: [**Безопасность eBPF в Kubernetes**](../../Kubernetes/Networking/Network/CNI/ebpf.md).

## Установка и настройка

### Falco (standalone Docker, без Kubernetes)

Falco — опенсорсный стандарт для обнаружения угроз в среде выполнения на базе eBPF. Подробнее о правилах и архитектуре: [**Falco: Безопасность в Runtime**](../../Security/Tools/falco.md).

```bash
# 1. Pull образ Falco (версия 0.44.1 на 2026 год)
docker pull falcosecurity/falco:0.44.1

# 2. Запуск с минимальными привилегиями (Modern eBPF — рекомендуемый режим)
docker run -d --name falco \
  --cap-drop all \
  --cap-add sys_admin \
  --cap-add sys_resource \
  --cap-add sys_ptrace \
  -v /sys/kernel/tracing:/sys/kernel/tracing:ro \
  -v /var/run/docker.sock:/host/var/run/docker.sock:ro \
  -v /proc:/host/proc:ro \
  -v /etc:/host/etc:ro \
  -v /lib/modules:/host/lib/modules:ro \
  -v /usr:/host/usr:ro \
  falcosecurity/falco:0.44.1

# 3. Проверка работы
docker logs falco
# → Falco initialized, subscribing to events...
```

Минимальный набор capabilities для Modern eBPF (Docker не поддерживает `CAP_BPF` и `CAP_PERFMON` напрямую, поэтому используется `CAP_SYS_ADMIN`):
- `CAP_SYS_PTRACE` — трейсинг процессов
- `CAP_SYS_RESOURCE` — доступ к perf-буферам
- `CAP_BPF` / `CAP_PERFMON` — загрузка eBPF-программ

### auditd для мониторинга Docker

Auditd обеспечивает неизменяемый журнал низкоуровневых системных вызовов на хосте. Это единственный механизм, который нельзя обойти из пользовательского пространства без компрометации ядра.

```bash
# 1. Установка
sudo apt update && sudo apt install auditd audispd-plugins jq -y

# 2. Базовые правила для Docker и runtime
cat > /etc/audit/rules.d/10-docker.rules << 'EOF'
# Мониторинг доступа к Docker socket
-w /var/run/docker.sock -p rwxa -k docker_socket
# Мониторинг изменений конфигурации Docker
-w /etc/docker -p wa -k docker_config
-w /etc/docker/daemon.json -p wa -k daemon_config
# Мониторинг вызовов CLI
-w /usr/bin/docker -p x -k docker_cli
-w /usr/bin/containerd -p x -k containerd_runtime
-w /usr/bin/runc -p x -k runc_cli
# Мониторинг загрузки модулей ядра (container escape)
-w /sbin/insmod -p x -k module_loading
-w /sbin/modprobe -p x -k module_loading
EOF

# 3. Загрузка правил
sudo augenrules --load

# 4. Валидация
sudo auditctl -l | grep docker
# → должно отображаться все правила
```

### Централизация событий

Для сбора событий в реальном времени используйте `docker events` с перенаправлением в syslog или journald:

```bash
# Перенаправление docker events в systemd journal
docker events --format '{{json .}}' | systemd-cat -t docker-security -p warning
# → события доступны в journalctl -t docker-security

# Запуск как systemd-сервис
cat > /etc/systemd/system/docker-events-monitor.service << 'EOF'
[Unit]
Description=Docker Events Security Monitor
After=docker.service

[Service]
ExecStart=/usr/bin/docker events --filter 'type=container' --format '{{json .}}'
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
systemctl enable --now docker-events-monitor
```

## Практические сценарии

### 1. Базовый аудит через нативные события Docker

Команда `docker events` позволяет отслеживать критические изменения конфигурации в реальном времени. Для глубокой диагностики `docker events` см. [**Отладка с помощью Docker Events**](../Docker_troubleshooting/debugging_with_docker_events.md).

```bash
# Мониторинг попыток входа в контейнеры (exec) и изменения политик
docker events --filter 'event=exec_create' --filter 'event=exec_start' --filter 'type=network'
# → Результат: запись события с меткой времени, ID контейнера и командой

# Мониторинг создания и удаления контейнеров
docker events --filter 'type=container' --filter 'event=create' --filter 'event=die' --filter 'event=oom-kill'
# → контейнер die, код выхода, container_id

# Экспорт в JSON для последующего анализа
docker events --format '{{json .}}' --since 1h | jq 'select(.status=="exec_start")'
```

### 2. События, подлежащие обязательному мониторингу

Для обнаружения современных атак (майнеры, fileless malware, lateral movement) необходимо отслеживать:

1.  **Файловые аномалии:**
    - Запись в Read-only директории или создание исполняемых файлов в `/tmp`, `/dev/shm`.
    - Чтение конфиденциальных данных (секреты Kubernetes, `/etc/shadow`).
    - Изменение системных библиотек (`/usr/bin/`, `/usr/sbin/`).
2.  **Манипуляции с процессами:**
    - **Execution Drift:** Запуск любого бинарного файла, не входящего в исходный SBOM образа. Подробнее: [**Runtime SBOM drift detection**](../../Security/Supply_Chain_Security/runtime_drift_detection.md).
    - **Privilege Escalation:** Использование `setuid`, запуск оболочек из-под веб-сервера.
    - **Memory-only attacks:** Использование системного вызова `memfd_create` для запуска кода без сохранения на диск.
3.  **Сетевая активность:**
    - Исходящие соединения на нестандартные порты (C2-каналы).
    - Доступ к локальным сервисам по привилегированным портам (1-1023).
    - Сканирование портов внутри Docker-сети.
    - DNS-запросы на подозрительные домены.

### 3. Drift Prevention с помощью Tetragon

Tetragon — это Kubernetes-native инструмент, требующий Cilium CNI. TracingPolicy применяется как CRD в кластере K8s, где Docker выступает как container runtime.

Пример политики (TracingPolicy) для блокировки записи в чувствительные директории:

```yaml
apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: "block-write-sensitive-paths"
spec:
  kprobes:
  - call: "sys_write"
    syscall: true
    args:
    - index: 0
      type: "fd"
    selectors:
    - matchPIDs:
      - operator: NotIn
        followForks: true
        isNamespacePID: true
        values: ["0", "1"]
      matchArgs:
      - index: 0
        operator: Prefix
        values: ["/etc/", "/usr/bin/"]
      matchActions:
      - action: Sigkill
```

**Валидация:**

```bash
# Проверка загрузки политики
kubectl get tracingpolicy block-write-sensitive-paths
# → должно отображаться статус Loaded

# Просмотр событий блокировки
kubectl logs -n kube-system ds/tetragon -c export-stdout -f | \
  jq 'select(.process_kprobe.action == "Sigkill")'
# → события с указанием pod, пути и действия
```

### 4. Обнаружение попыток container escape

Выход за границы контейнера часто сопровождается монтированием хост-директорий или загрузкой модулей ядра. Falco обнаруживает такие попытки через анализ системных вызовов.

**Ключевые паттерны для обнаружения:**

| Паттерн | Что мониторить | Пример правила |
| :--- | :--- | :--- |
| **Mount host paths** | `mount` syscall с путями `/proc`, `/sys`, `/var/run/docker.sock` | `evt.type=mount and fd.name startswith "/proc"` |
| **Load kernel modules** | `init_module`, `finit_module` syscall | `evt.type in (init_module, finit_module)` |
| **Privileged container** | запуск с `--privileged` | `container.privileged == true` |
| **Docker socket mount** | `open` на `/var/run/docker.sock` внутри контейнера | `fd.name = /var/run/docker.sock and container` |
| **Namespace escape** | `setns` syscall | `evt.type = setns` |

Подробные правила Falco для обнаружения container escape: [**Falco: обзор правил**](../../Security/Tools/falco.md).

### 5. Обнаружение fileless malware (memfd_create)

Вредоносный код, загруженный в память через `memfd_create`, не оставляет следов на файловой системе. eBPF-мониторинг syscall позволяет перехватить такие атаки.

```bash
# Проверка наличия memfd_create в активных процессах
# (Falco-правило для обнаружения memfd_create в контейнерах)
# Правило определяется в /etc/falco/falco_rules.local.yaml:
# - rule: Detect memfd_create in container
#   desc: обнаружение запуска кода через memfd_create
#   condition: evt.type = memfd_create and container
#   output: "Fileless execution detected (container=%container.id process=%proc.cmdline)"
#   priority: CRITICAL
```

Для ручной диагностики:
```bash
# Поиск анонимных файлов в памяти процесса
ls -la /proc/*/fd/ 2>/dev/null | grep memfd
# → анонимные файлы, связанные с memfd_create
```

### 6. Обнаружение привилегированных процессов и эскалации привилегий

Запуск оболочки из-под веб-сервера, использование SUID-бинарников и запросы с повышенными capabilities — это ключевые индикаторы эскалации привилегий.

```bash
# Мониторинг через auditd: execve от веб-процесса
sudo auditctl -a exit,always -F arch=b64 -F auid>=1000 -F auid!=4294967295 -S execve -k privileged_exec

# Поиск следов эскалации
sudo ausearch -k privileged_exec -i | grep -E "sh|bash|nc|curl|wget"
```

### 7. Централизация и корреляция событий

Runtime события следует направлять в централизованное хранилище для корреляции и построения дашбордов. Интеграция с Wazuh обеспечивает XDR-подход к безопасности.

```bash
# Пример: Falco → stdout → systemd journal → Filebeat → SIEM
# Настройка вывода Falco в stdout (конфигурация внутри контейнера)
# /etc/falco/falco.yaml:
# outputs:
#   stdout:
#     enabled: true
#   file:
#     enabled: true
#     path: /var/log/falco_events.log
# webserver:
#   enabled: true
#   listen: 0.0.0.0
#   port: 28039
```

Подробнее о сборе событий через Wazuh: [**Мониторинг контейнеров в Wazuh**](../../Security/Tools/Wazuh/container_monitoring.md).

## Операции и команды

### Управление docker events

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `docker events --filter type=container` | Фильтр по типу объекта | `--filter 'type=container'` |
| `docker events --filter event=exec_create` | Фильтр по событию | `--filter 'event=exec_start'` |
| `docker events --filter label=stage=prod` | Фильтр по метке | `--filter 'label=compliance=sec'` |
| `docker events --since 1h` | События за период | `--since 1h` |
| `docker events --format '{{json .}}'` | Вывод в JSON | для парсинга `jq` |

### Управление Falco

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `docker exec falco falcoctl version` | Проверка версии | `falcoctl version` |
| `docker exec falco falcoctl artifact follow falco-rules` | Обновление правил | `falcoctl artifact follow falcosecurity/rules` |
| `docker logs falco --since 1h` | Просмотр алертов | фильтрация по `priority` |
| `docker exec falco cat /etc/falco/falco_rules.local.yaml` | Просмотр кастомных правил | редактирование локальных правил |

### Проверка auditd

| Команда | Назначение | Пример вывода |
| :--- | :--- | :--- |
| `sudo auditctl -l` | Список правил | `-w /var/run/docker.sock -p rwxa -k docker_socket` |
| `sudo auditctl -s` | Статус аудита | `enabled 1`, `backlog 64` |
| `sudo ausearch -k docker_socket -i` | Поиск по ключу | `type=SYSCALL ... key="docker_socket"` |
| `sudo aureport -x --summary` | Сводка по EXECVE | таблица вызовов execve |

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Falco не генерирует алерты** | eBPF не поддерживается на узле | Проверить: `ls /sys/kernel/tracing`; `sysctl -n net.core.bpf_jit_enable` (должно быть 1); для ядра < 5.4 использовать Kernel Module (`--set driver.kind=kmod`) |
| **Falco падает при запуске** | Недостаточно capabilities | Проверить: `CAP_SYS_PTRACE`, `CAP_SYS_RESOURCE`, `CAP_SYS_ADMIN`; для Modern eBPF требуется доступ к `/sys/kernel/tracing` и `/proc` |
| **docker events не генерирует события** | Демон перегружен или используется rootless режим | Для rootless: указать `DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock`; для централизованного сбора использовать `auditd` как резервный канал |
| **Tetragon policies не применяются** | Отсутствует BTF или Tetragon не установлен | `sudo bpftool feature probe \| grep lsm`; проверить `CONFIG_BPF_LSM=y`; обновить ядро до 5.10+ |
| **auditd: записи не появляются** | Правило не сработало или аудит отключен | Проверить `sudo auditctl -s` (поле `enabled 1` или `2`); проверить синтаксис правила через `sudo auditctl -l` |
| **auditd: переполнение буфера** | Слишком много событий | Увеличить `-b 16384` в `/etc/audit/rules.d/10-base-config.rules`; оптимизировать правила, убрать шумные syscall |
| **Большой объем событий** | Высокая динамика контейнеров без фильтров | Добавить `--filter` для `docker events`; в Falco использовать `ignore` для служебных контейнеров; в auditd использовать исключения по пользователям |

## Лучшие практики

1.  **Modern eBPF в первую очередь:** Используйте Falco с Modern eBPF driver — не требует сборки kernel module, минимальный overhead.
2.  **Least Privilege для Falco:** Запускайте Falco с `--cap-drop all --cap-add sys_admin --cap-add sys_ptrace` вместо `--privileged`.
3.  **Слои обнаружения:** Комбинируйте `docker events` (Management Plane), `auditd` (syscall-level), и Falco (eBPF) для defense-in-depth.
4.  **Исключайте шум:** Фильтруйте служебные контейнеры (`kube-system`, `docker-gc`) и healthcheck-процессы в правилах.
5.  **Централизуйте логи:** Перенаправляйте события в SIEM (через Falcosidekick, Filebeat, или journald) для корреляции.
6.  **Блокируйте на этапе enforcement:** Используйте Tetragon для K8s-сред или Falco + systemd для Docker standalone, чтобы не только обнаруживать, но и блокировать.
7.  **Регулярно пересматривайте правила:** Атаки эволюционируют — правила Falco и TracingPolicy следует обновлять на основе threat intelligence.
8.  **Не храните секреты в env:** Скрипты инвентаризации собирают `env` контейнеров. Используйте `<options>no_full_log</options>` в правилах Wazuh для предотвращения утечки.

## Граничные случаи и ограничения

- **Rootless Docker:** Сокет находится в `$XDG_RUNTIME_DIR/docker.sock` (обычно `/run/user/<UID>/docker.sock`). Агент мониторинга должен иметь доступ к runtime-директории пользоватся.
- **Docker-in-Docker (DinD):** Мониторинг затруднён из-за изолированных namespaces. Используйте outer Docker socket или sidecar-подход с пробросом ключей.
- **Высокая нагрузка:** При >500 контейнеров добавляйте `--filter` для `docker events`, используйте агрегацию на уровне коллектора и фильтруйте служебные события.
- **eBPF и SELinux:** На хостах с SELinux(strict) eBPF-программы могут быть ограничены политиками. Проверьте `sealert` на наличие AVC-отказов.
- **Kernel lockdown:** При включённом `Lockdown Mode` загрузка внешних BPF-программ может быть заблокирована.

## Дополнительная информация

**Связанные документы:**

- **[Falco: Runtime Security Monitoring](../../Security/Tools/falco.md)** — детальный разбор правил обнаружения, драйверов и установки.
- **[Wazuh: Мониторинг контейнеров](../../Security/Tools/Wazuh/container_monitoring.md)** — XDR-подход к безопасности.
- **[Укрепление безопасности контейнеров](./container_hardening.md)** — превентивная защита.
- **[eBPF — виртуальная машина ядра](../../Linux/Core/kernel/ebpf.md)** — технологическая база.
- **[auditd: Аудит событий](../../Linux/SystemAdministration/Logging/auditd.md)** — классический подход к мониторингу хоста.
- **[Отладка с помощью Docker Events](../Docker_troubleshooting/debugging_with_docker_events.md)** — фильтры и диагностика `docker events`.
- **[Runtime SBOM drift detection](../../Security/Supply_Chain_Security/runtime_drift_detection.md)** — обнаружение дрейфа состава образа.

**Глубокое изучение:**
- **[Tetragon](../../Kubernetes/Networking/Network/CNI/cilium.md#безопасность-среды-выполнения-tetragon)** — eBPF enforcement. В Docker (K8s): TracingPolicy для блокировки записи в `/etc/`, `Sigkill` при drift, защита от container escape.
- **[Аудит и комплаенс](../../Security/audit_and_compliance_overview.md)** — аудит для compliance. В Docker: `docker events` + auditd для `/var/run/docker.sock`, мониторинг `exec_create`/`exec_start`.
- **[Безопасность цепочки поставок](../../Security/Supply_Chain_Security/overview.md)** — SBOM, подписи, attestation.
- **[Контейнерная безопасность в Kubernetes](../../Kubernetes/Security/container_runtime_security.md)** — Seccomp, AppArmor, SELinux, Capabilities.

**Внешние ресурсы:**
- **Tetragon Documentation:** [github.com/cilium/tetragon](https://github.com/cilium/tetragon).
- **Falco Rules Library:** [falco.org/docs/rules/](https://falco.org/docs/rules/).
- **NIST SP 800-190:** Раздел "Runtime Analysis".
