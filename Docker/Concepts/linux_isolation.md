# Изоляция контейнеров: Namespaces и Cgroups

**Актуально для:** Docker 20.10+ (рекомендуется 29.x), Cgroups v2 (Kernel 5.8+)

## Определения

**Изоляция контейнеров** — это комплекс мер по разграничению ресурсов и видимости системных объектов между процессами контейнера и хостовой ОС. В Linux это достигается на уровне ядра через взаимодействие с **ABI (Application Binary Interface)** и системными вызовами, используя три фундаментальных механизма:

- **Namespaces** (Пространства имён) — обеспечивают **логическую изоляцию** (что процесс *видит*). Создают виртуализированную копию системного ресурса.
- **Cgroups** (Контрольные группы) — обеспечивают **ресурсную изоляцию** (что процесс *использует*). Ограничивают потребление CPU, RAM, I/O и сети.
- **Union File Systems** (например, Overlay2) — обеспечивают **изоляцию файловой системы**, разделяя базовые образы и записываемые слои контейнера.

Подробнее о фундаментальных механизмах ядра: [Namespaces](../../Linux/Core/namespaces.md), [Cgroups](../../Linux/Core/cgroups.md).

## Базовые концепции

### Роль механизмов ядра в контейнеризации

Контейнеры не являются эмуляцией оборудования (как ВМ). Это обычные процессы, запущенные через системные вызовы `clone()`, `unshare()` или `setns()`, которые создают новые пространства имён.

#### 1. Пространства имён (Namespaces)

| Тип | Что изолирует | Практический эффект |
| :--- | :--- | :--- |
| **PID** | Дерево процессов | Контейнер видит себя как PID 1, не видит процессы хоста. |
| **NET** | Сетевой стек | Собственные IP, интерфейсы, маршруты, `iptables`. |
| **MNT** | Точки монтирования | Изолированный корень ФС (`chroot` / `pivot_root`). |
| **UTS** | Hostname/Domain | Возможность иметь уникальное имя узла внутри контейнера. |
| **IPC** | Сигналы и память | Разделяемая память (shared memory) и очереди сообщений. |
| **USER** | UID/GID | Мапинг `root` внутри контейнера на `non-root` на хосте. |
| **CGROUP** | Видимость cgroups | Скрывает иерархию контрольных групп хоста из `/proc/self/cgroup`. |
| **TIME** | Системное время | Позволяет изменять время внутри контейнера без влияния на хост. |

#### 2. Контрольные группы (Cgroups v2)

В современных системах (Kernel 5.8+, Docker 20.10+) используется **Cgroups v2 (Unified Hierarchy)**. В отличие от v1, она имеет одну древовидную структуру для всех ресурсов.

**Ключевые преимущества v2:**
- **Unified Accounting:** отсутствие конфликтов между контроллерами (например, корректный учет I/O для буферизованной записи).
- **Granular Control:** введение лимитов `memory.high` (мягкое ограничение/дросселирование) в дополнение к `memory.max` (жесткое ограничение/OOM Killer).
- **PSI (Pressure Stall Information):** предоставляет метрики "давления" на ресурсы (CPU, RAM, I/O), показывая, какой процент времени процессы простаивали в ожидании ресурса.
- **Rootless Support:** безопасное делегирование управления ресурсами непривилегированным пользователям.

### Изоляция файловой системы (OverlayFS)

Docker использует драйвер **overlay2** для создания изолированной ФС. Она состоит из слоев:
- **Lowerdir (Read-Only):** слои образа. Они неизменны и могут использоваться многими контейнерами одновременно.
- **Upperdir (Writable):** слой конкретного контейнера. Все изменения пишутся сюда.
- **Merged:** результирующий вид, который видит процесс внутри контейнера.

**Механизм Copy-on-Write (CoW):** если контейнер пытается изменить файл из `lowerdir`, ядро сначала копирует его в `upperdir`, и только потом применяет изменения. Оригинал в образе остается нетронутым.

Подробный разбор работы драйвера (copy-up, whiteout, opaque-директории, `d_type`, лимит 128 слоев): **[Драйвер хранения OverlayFS](../Docker_fs/docker_overlayfs.md)**.

### Дополнительные уровни безопасности

Сами по себе механизмы изоляции не являются "границей безопасности" (security boundary). Для полноценной защиты используются:

- **Linux Capabilities:** разбиение прав `root` на мелкие части. Docker по умолчанию отключает опасные права (например, `CAP_SYS_TIME`, `CAP_NET_ADMIN`).
- **Seccomp (Secure Computing):** фильтрация системных вызовов. Ограничивает поверхность атаки на ядро.
- **LSM (AppArmor / SELinux):** принудительный контроль доступа к файлам и сетевым портам на уровне политик ОС.
- **ReadOnly RootFS:** возможность запуска контейнера с неизменяемой ФС (`--read-only`), что блокирует большинство эксплойтов.

### Крайние случаи и особенности поведения

Механизмы изоляции имеют ограничения, проявляющиеся в нестандартных сценариях:

1. **Вложенные контейнеры (Docker-in-Docker / Podman-in-Podman):** При запуске контейнера внутри контейнера (DinD) требуется привилегированный режим (`--privileged`) или явное предоставление доступа к `cgroups` и `devices`, так как внутренний демон не видит cgroups хоста без делегирования.
2. **Systemd внутри контейнера:** Для корректной работы `systemd` как PID 1 требуется:
   - Монтирование хостовой иерархии cgroups (`--cgroupns=host`) или приватное пространство cgroup namespace (`--cgroupns=private` с делегированием). В Docker 29.x с systemd-хостами предпочтительнее `--cgroupns=host`, так как systemd ожидает видеть полную иерархию.
   - Доступ к `/sys/fs/cgroup` и `/run` как tmpfs.
   - Отключение `--read-only` или явное указание writable-путей (`--tmpfs /run`, `--tmpfs /run/lock`).
   - **Важно для SRE:** При использовании `--cgroupns=host` контейнер получает доступ к информации о всех процессах хоста через `/sys/fs/cgroup`. Это допустимо только для доверенных контейнеров (CI/CD runners, DinD). Для production-workloads используйте `--cgroupns=private` с явным делегированием контроллеров.
3. **Ограничение глубины OverlayFS:** Стандартное ограничение — 128 нижних слоев (`lowerdir`). При превышении возникает ошибка `too many levels of symbolic links`. Решение: использование `overlay2` с оптимизацией или переход на `fuse-overlayfs` в rootless-режиме.
4. **Time Namespace:** Несмотря на наличие в ядре 5.6+, Docker не включает `CLONE_NEWTIME` по умолчанию. Контейнеры, которым требуется изолированное время, должны использовать явные флаги или патч рантайма.
5. **Общий кеш страниц (Page Cache):** Cgroups ограничивают потребление *активной* памяти, но page cache учитывается в `memory.stat`. При высокой I/O-нагрузке cache может занимать значительную часть лимита, приводя к ложным OOMKilled.
6. **Seccomp и гетерогенные архитектуры:** Профили seccomp могут зависеть от архитектуры (amd64, arm64). Системные вызовы, разрешенные на x86_64, могут отсутствовать на ARM, что приводит к `ENOSYS` при переносе образов.

## Практические сценарии

### Предварительные требования

Перед работой с изоляцией убедитесь, что система соответствует требованиям:

**Аппаратные и программные требования:**
- Ядро Linux **5.8+** для полной поддержки Cgroups v2 и всех контроллеров; в production-средах 2026 года преобладают ядра **6.x**.
- Docker **20.10+** (предпочтительно 29.x+ для стабильной работы cgroups v2 и `--cgroupns`).
- Файловая система с поддержкой `overlay2` (ext4, xfs, btrfs).

**Проверка окружения:**

```bash
# Проверка версии ядра
uname -r
# → 5.15.0-xx-generic (должен быть ≥ 5.8)

# Проверка режима cgroups (должен быть cgroup2)
stat -fc %T /sys/fs/cgroup/
# → cgroup2fs

# Проверка версии Docker
docker --version
# → Docker version 29.x, build xxxxx

# Проверка доступного storage driver
docker info | grep -i "storage driver"
# → Storage Driver: overlay2

# Проверка поддержки namespaces в ядре
grep -i "CONFIG_NAMESPACES" /boot/config-$(uname -r)
# → CONFIG_NAMESPACES=y
# → CONFIG_CGROUPS=y
# → CONFIG_CGROUP_SCHED=y
# → CONFIG_CGROUP_PIDS=y
# → CONFIG_MEMCG=y
# → CONFIG_CGROUP_DEVICE=y
# → CONFIG_CGROUP_NET_PRIO=y
# → CONFIG_CGROUP_NET_CLASSID=y
# → CONFIG_CPUSETS=y
# → CONFIG_IPC_NS=y
# → CONFIG_UTS_NS=y
# → CONFIG_USER_NS=y
# → CONFIG_PID_NS=y
# → CONFIG_NET_NS=y
```

### Сравнение низкоуровневых механизмов и Docker

Низкоуровневые утилиты позволяют вручную создать изоляцию, но Docker автоматизирует этот процесс, добавляя управление образами и сетью.

| Функция | Ручной подход (`unshare`, `cgcreate`) | Docker / Podman |
| :--- | :--- | :--- |
| **Изоляция** | Требует ручного указания флагов для каждого типа | Автоматически применяет полный набор |
| **Файловая система** | Использует хостовую (требует `chroot` или `pivot_root`) | Монтирует `rootfs` из слоёв образа (Overlay2) |
| **Сеть** | Пустой namespace (требует настройки `veth` и мостов) | Автоматически настраивает bridge/overlay сети |
| **Ресурсы** | Требует ручного создания записей в `/sys/fs/cgroup` | Применяет лимиты через флаги `--memory`, `--cpus` |

### Жизненный цикл запуска контейнера (OCI Runtime)

При вызове `docker run` или `podman run` происходит взаимодействие нескольких компонентов:
1. **Container Engine (Docker/Podman):** обрабатывает высокоуровневые запросы и образы.
2. **Container Runtime (`runc` / `crun`):** низкоуровневая OCI-совместимая утилита, которая взаимодействует с ядром. В 2026 году `crun` предпочтительнее для production из-за меньшего оверхеда памяти и нативной поддержки cgroups v2.
3. **Создание:** рантайм делает системный вызов `clone()` с флагами соответствующих пространств имён (например, `CLONE_NEWPID`, `CLONE_NEWNET`).
4. **Настройка:** внутри нового процесса монтируется `rootfs`, настраивается сеть и применяются лимиты cgroups.
5. **Exec:** процесс заменяет себя (`execve`) целевым бинарным файлом (например, `/bin/bash`).

> **Примечание для SRE:** В Kubernetes 1.28+ и Docker 29.x контейнеры по умолчанию используют `cgroupns=private`, что скрывает иерархию cgroups хоста. При использовании systemd внутри контейнера (например, в `docker:dind` или legacy-образах) может потребоваться `--cgroupns=host` с учётом рисков раскрытия информации о соседних контейнерах.

### Практическая инспекция механизмов изоляции

Механизмы изоляции можно увидеть напрямую через файловую систему `/proc`.

**1. Получение PID процесса контейнера:**

```bash
# Через docker inspect
PID=$(docker inspect --format '{{.State.Pid}}' <container_name>)
echo $PID # → 47865
```

**2. Просмотр пространств имён (Namespaces):**

```bash
# Список всех пространств имён процесса
ls -la /proc/$PID/ns/
# → net -> net:[4026532920]
# → pid -> pid:[4026532921]

# Человекочитаемый вывод через lsns (подробнее в [lsns](../../Linux/Diagnostics/Processes/lsns.md))
lsns -p $PID
```

**3. Инспекция Cgroups v2 и PSI:**

```bash
# Путь к cgroup контейнера (зависит от драйвера cgroup, обычно systemd)
CG_PATH="/sys/fs/cgroup/system.slice/docker-$(docker inspect --format '{{.Id}}' <name>).scope"

# Проверка лимитов памяти
cat $CG_PATH/memory.max  # Hard limit (max)
cat $CG_PATH/memory.high # Soft limit (throttling)

# Просмотр Pressure Stall Information (PSI)
cat $CG_PATH/io.pressure
# → some avg10=0.04 avg60=0.01 avg300=0.00 total=12345
# avg10=0.04 означает, что за последние 10 сек процессы простаивали 0.04% времени из-за I/O.
```

**4. Вход в пространство имён для отладки:**

```bash
# Просмотр сетевых настроек контейнера «снаружи»
nsenter -t $PID -n ip addr

# Запуск shell внутри пространств имён контейнера (без docker exec)
nsenter -t $PID -n -p -m -- bash
```

**5. Валидация изоляции файловой системы:**

```bash
# Проверка работы CoW: изменение файла в контейнере не должно касаться образа
docker run --rm -it alpine sh -c "echo 'modified' > /etc/hostname && cat /etc/hostname"
# → modified

# Проверка на хосте (файл образа не изменился)
docker inspect --format '{{.GraphDriver.Data.UpperDir}}' <container_name>
# → /var/lib/docker/overlay2/.../diff

# Проверка ReadOnly RootFS
docker run --rm --read-only -it alpine sh -c "touch /test && echo OK" || echo "Ожидаемая ошибка: RO FS"
# → touch: /test: Read-only file system
# → Ожидаемая ошибка: RO FS
```

### Валидация изоляции в CI/CD пайплайнах

Для SRE и DevOps-инженеров важно автоматизировать проверку изоляции при деплое. Ниже приведены проверки, которые можно интегрировать в GitLab CI, GitHub Actions или Jenkins:

```bash
#!/usr/bin/env bash
# validate-isolation.sh — базовый набор проверок для CI
set -euo pipefail

CONTAINER="${1:-alpine:latest}"

# 1. Проверка namespaces
docker run --rm -d --name iso-test "$CONTAINER" sleep 3600
PID=$(docker inspect -f '{{.State.Pid}}' iso-test)

# PID namespace: контейнер должен иметь свой PID 1
if ! ls -la /proc/$PID/ns/pid >/dev/null 2>&1; then
  echo "FAIL: PID namespace отсутствует"
  exit 1
fi

# NET namespace: должен быть отдельный netns
HOST_NET=$(readlink /proc/1/ns/net)
CONT_NET=$(readlink /proc/$PID/ns/net)
if [ "$HOST_NET" = "$CONT_NET" ]; then
  echo "FAIL: Network namespace не изолирован"
  exit 1
fi

# 2. Проверка cgroupns (Docker 20.10+)
docker rm -f iso-test
docker run --rm -d --name iso-test --cgroupns=private "$CONTAINER" sleep 3600
PID=$(docker inspect -f '{{.State.Pid}}' iso-test)
if [ -f "/proc/$PID/ns/cgroup" ]; then
  echo "OK: cgroup namespace присутствует"
else
  echo "WARN: cgroup namespace не поддерживается"
fi

# 3. Проверка read-only rootfs
docker rm -f iso-test
if ! docker run --rm --read-only "$CONTAINER" test -w /tmp 2>/dev/null; then
  echo "OK: read-only rootfs работает"
else
  echo "FAIL: read-only rootfs не изолирует ФС"
  exit 1
fi

# 4. Проверка capabilities (должны быть сброшены)
docker rm -f iso-test
docker run --rm -d --cap-drop=ALL "$CONTAINER" sleep 3600
PID=$(docker inspect -f '{{.State.Pid}}' iso-test)
CAPS=$(cat /proc/$PID/status | grep CapEff)
echo "CapEff: $CAPS"

docker rm -f iso-test
echo "Изоляция прошла проверку"
```

### Типичные проблемы и диагностика

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `permission denied` на томах | Ошибка маппинга UID/GID между хостом и контейнером | Проверьте владельца каталога на хосте; используйте `--userns=keep-id` (Podman) или явно задайте `--user $(id -u):$(id -g)` |
| `no space left on device` (OverlayFS) | Исчерпан лимит нижних слоев (обычно 128) или место на диске | Проверьте `docker system df`; объедините или пересоберите образ с меньшим количеством слоев |
| `cgroup: cannot set cgroup ...` | Отсутствует поддержка cgroups v2 или неправильные права | Переведите хост на cgroups v2; проверьте `docker info | grep -i cgroup` |
| Контейнер не видит сеть | Ошибка в bridge/overlay сети или конфликт iptables | Выполните `docker network inspect bridge`; проверьте `iptables -L -n -v` |
| `OOMKilled` при наличии лимита | Page cache учитывается в memory.max; приложение не учитывает лимит | Установите `memory.high` ниже `memory.max`; настройте приложение на чтение cgroup-лимитов |
| `clock: invalid argument` (Time) | Попытка изменения времени без `CAP_SYS_TIME` или нестабильный `clock_gettime` | Не предоставляйте `CAP_SYS_TIME` без необходимости; обновите ядро для поддержки Time Namespace |
| `operation not permitted` (Seccomp) | Системный вызов заблокирован профилем seccomp | Определите блокируемый вызов через `dmesg` или `audit.log`; добавьте исключение в кастомный профиль |
| Container escape: suspicious processes | Скомпрометированный контейнер с `CAP_SYS_ADMIN` или `--privileged` | Немедленно остановите контейнер; проверьте `dmesg` и `audit.log`; смените все credentials |
| `cgroupns` показывает cgroups хоста | Используется `--cgroupns=host` или Docker < 20.10 без namespace | Перезапустите с `--cgroupns=private`; проверьте версию Docker |
| Page cache вытесняет полезные данные | `memory.max` меньше working set + page cache | Увеличьте `--memory` или настройте `vfs_cache_pressure`; используйте `memory.high` для throttling |
| Zombie-процессы в контейнере | Отсутствие корректного PID 1 (init) | Используйте `tini` или `--init`; убедитесь, что PID 1 корректно собирает僵尸-процессы |
| `systemd` не стартует в контейнере | Отсутствует `--cgroupns=host` или `/sys/fs/cgroup` не смонтирован | Проверьте флаги запуска; убедитесь, что хост использует systemd |

### Рекомендации и лучшие практики

**Безопасность:**
1. **Минимальные privileges:** Запускайте контейнеры с `--read-only`, `--cap-drop=ALL` и добавляйте только необходимые capabilities через `--cap-add`.
2. **Cgroup Namespace:** Используйте `--cgroupns=private` (Docker 20.10+) для скрытия иерархии cgroups хоста. На хостах с systemd может потребоваться `--cgroupns=host` для корректного взаимодействия с юнитами, но только для доверенных контейнеров.
3. **Seccomp:** Применяйте профиль `docker-default` или кастомный. Избегайте `--security-opt seccomp=unconfined` в production.
4. **User Namespace Remap:** Включите `userns-remap` в демоне Docker для маппинга root-UID контейнера на непривилегированного пользователя хоста.
5. **PIDs Limit:** Ограничьте количество процессов через `--pids-limit` для защиты от fork-бомб.
6. **Автоматическая проверка:** Интегрируйте проверку изоляции в CI/CD. Например, используйте [Docker Bench for Security](https://github.com/docker/docker-bench-security) или [Trivy](https://aquasecurity.github.io/trivy/) для статического анализа конфигураций.

**Стабильность и производительность:**
1. **Memory High:** Всегда устанавливайте `memory.high` (soft limit) ниже `memory.max` (hard limit). Это позволяет демону OOM (`systemd-oomd` или встроенный) корректно дросселировать процесс до принудительного убийства.
2. **CPU Quota:** Используйте `--cpus` вместо `--cpu-period`/`--cpu-quota` для простоты. Для высоконагруженных приложений рассмотрите `--cpuset-cpus` для привязки к конкретным ядрам.
3. **I/O Weight:** Настройте `--blkio-weight` (1-1000) для контейнеров с интенсивным I/O, чтобы предотвратить starvation остальных сервисов.
4. **Прослеживание (Tracing):** Используйте `docker events` и `cAdvisor` для мониторинга поведения cgroups в реальном времени.
5. **Аудит namespace:** Регулярно проверяйте `lsns` и `docker inspect` для выявления контейнеров с избыточными правами (`--privileged`, отсутствующий `--cgroupns`).

**Чистка окружения:**
```bash
# Удаление остановленных контейнеров, неиспользуемых сетей и висющих образов
docker system prune -a --volumes

# Принудительная остановка и удаление всех контейнеров
docker rm -f $(docker ps -aq)

# Очистка кеша builder
docker builder prune -a
```

## Ограничения и риски изоляции

Namespaces и Cgroups не обеспечивают 100% изоляцию. Основные "белые пятна":

1. **Общее Ядро (Shared Kernel):** все контейнеры используют одно ядро хоста. Уязвимость в системном вызове (например, `io_uring` или `netfilter`) может привести к компрометации всего хоста.
2. **Утечки в /proc и /sys:** некоторые файлы в этих псевдо-ФС не изолированы и могут выдавать информацию о хосте (например, `/proc/kcore` или данные о CPU/RAM всего узла).
3. **Отсутствие Device Namespace:** Docker ограничивает доступ к устройствам через Cgroups, но не виртуализирует их. Контейнер может "видеть" узлы устройств, даже если не может их открыть.
4. **Time Isolation:** с Docker 29.5.0 контейнеры получают private time namespace по умолчанию (ядро ≥ 5.6), но `CLOCK_REALTIME` остаётся общим с хостом: контейнер с `CAP_SYS_TIME` может влиять на системное время хоста. Детали — в **[container_time_sync.md](../Docker_troubleshooting/container_time_sync.md)** (Сценарий 8).
5. **Container Escape через ядро:** уязвимости в ядре (CVE-2022-0185, CVE-2023-3266) позволяют выйти за пределы namespaces. В 2026 году критически важно использовать минимальные образы (distroless, scratch) и обновлять ядро регулярно.
6. **Сторонние модули ядра:** eBPF-программы, загруженные через `CAP_BPF` или `CAP_SYS_ADMIN`, могут читать память других контейнеров. Ограничьте доступ к BPF через `kernel.unprivileged_bpf_disabled=1`.

Для минимизации этих рисков рекомендуется использовать **Rootless режим**, **User Namespaces** и системы **LSM (AppArmor/SELinux)**. В многоарендных средах (SaaS, PaaS) дополнительно используйте **sandboxed runtimes** (gVisor, Kata Containers) для создания аппаратной границы изоляции.

## Дополнительная информация

### См. также

- [Обзор Docker](../docker_overview.md) — общие принципы работы.
- [Безопасность Docker](../Docker_security/overview.md) — глубокое погружение в защиту.
- [Сетевая модель Docker](../Docker_network/docker_network.md) — детализация работы Network Namespace.
- **[Драйвер хранения OverlayFS](../Docker_fs/docker_overlayfs.md)** — глубокий разбор copy-up, whiteout и storage driver.
- [Изоляция в Podman](../../Podman/linux_isolation.md) — специфические особенности Podman.
- **[Производительность Docker](../Docker_performance_tuning.md)** — оптимизация CPU, памяти, I/O и сети в контейнерах.
