# Механизмы сохранения и восстановления процессов

## Определения

**Checkpoint/Restore** — технология сохранения полного состояния запущенного процесса (или группы процессов) в файлы-образы на диске с возможностью последующего восстановления его работы с того же места. Отличается от обычного бэкапа тем, что сохраняет **живое** состояние — регистры, состояние памяти, открытые дескрипторы и сетевые соединения.

**CRIU (Checkpoint/Restore In Userspace)** — основной инструмент в Linux для реализации механизмов «заморозки» и восстановления процессов. CRIU работает преимущественно в пространстве пользователя, используя `ptrace` и интерфейсы `/proc`. Входит в состав проекта [Linux Foundation](https://criu.org) и активно развивается.

**Pre-Dump (Итеративный дамп)** — механизм оптимизации, позволяющий снять предварительный снимок памяти процеса без его остановки. Это критично для «живой» миграции, так как сокращает время финальной заморозки (downtime).

**Lazy Restore (Отложенное восстановление)** — стратегия восстановления, при которой страницы памяти подгружаются из образа по требованию (через `userfaultfd`), а не сразу при старте процесса. Сокращает время старта восстановленного процесса.

**Page Server** — сетевой демон CRIU, предназначенный для передачи страниц памяти процесса напрямую на другой хост по сети во время миграции, минуя сохранение на локальный диск.

**Container Checkpointing** — создание контрольной точки (snapshot) работающего контейнера: его файловой системы, процессов, сетевых соединений и состояния памяти. Аналогично процессному checkpoint, но на уровне контейнера (namespaces + cgroups).

**Shell Job (Shell Job Mode)** — режим CRIU (`--shell-job`), при котором CRIU не пытается восстанавливать состояние терминала и shell-сессии. Используется для процессов, запущенных из интерактивного терминала.

### Иерархия инструментов

| Инструмент | Уровень | Overhead | Применимость | Описание |
| :--- | :--- | :--- | :--- | :--- |
| `cp /proc/PID/exe` | Легкий снимок | ~0% | Emergency | Восстановление удалённого бинаря |
| `criu dump/restore` | Полный дамп | ~5-15% (stop-the-world) | Production/Staging | Full process state snapshot |
| `criu pre-dump` | Инкремент | ~5% (online) | Production | Pre-dump + iterative pages |
| `criu page-server` | Сеть | ~5% + network | Migration | Direct memory streaming, no disk |
| `podman/docker checkpoint` | Container | ~5-15% | Production | CLI-level container CRIU |
| **CRaC (Coordinated Restore at Checkpoint)** | Java | ~0-5% | Staging | JVM-aware checkpoint, hooks |

> **Выбор инструмента:** Для production-миграций с минимальным downtime используйте `pre-dump` + `page-server`. Для отладки и emergency-recovery — `criu dump/restore`. Для контейнеров — `podman/docker checkpoint`.

## Основные концепции

### Технические компоненты состояния

Для успешного восстановления CRIU должен сериализовать:

- **Адресное пространство:** Все сегменты памяти (стек, куча, mmap), включая `MAP_SHARED`/`MAP_ANONYMOUS`/`MAP_LOCKED`.
- **Ресурсы ядра:** Открытые дескрипторы (FD), включая пайпы, сокеты, терминалы. Сокеты требуют `--tcp-established`.
- **Сетевые состояния:** TCP-сокеты в состоянии `ESTABLISHED` (флаг `--tcp-established`), а также Unix domain sockets (`--ext-unix-sk`).
- **Ghost files:** Файлы, которые были удалены с диска, но остаются открытыми процессом. CRIU сохраняет их содержимое внутри образа.
- **Иерархия:** Дерево PID/TID, PGID, SID и параметры планировщика (`nice`, `cgroup`).
- **Таймеры:** `timerfd`, `ITIMER_REAL` и POSIX таймеры (восстанавливаются с поправкой на время).
- ** inotify/fsnotify:** Отслеживание изменений в файловой системе (с ограничениями).
- **Параметры cgroups:** CRIU может сохранять cgroup-путь процесса (`--cgroup-file`), но не все контроллеры восстанавливаются автоматически.

### Метаданные образа CRIU

Образ состоит из набора файлов в `--images-dir`. Основные файлы:

| Файл | Описание |
| :--- | :--- |
| `pid.img` | Информация о PID'ах (маппинг старых → новых) |
| `psr.ind` | Информация о потоках |
| `mm-*.swp` | Дамп страниц памяти (или `.pgi` — page-map) |
| `fdinfo-N.img` | Метаданные дескрипторов файлов |
| `files.img` | Метаданные файлов (ghost files, ссылки) |
| `net*.img` | Сетевые состояния (сокеты, адреса, маршруты) |
| `cgroup*.img` | Информация о cgroup-членстве |
| `tty.in` / `tty.out` | Состояние терминала (TTY) |

### Механизмы оптимизации миграции

1.  **Iterative Checkpoint (`pre-dump`):**
    - Снимается первый дамп памяти (процесс продолжает работать).
    - Ядро отслеживает измененные страницы (через `/proc/PID/pagemap` и `soft-dirty` биты).
    - Снимается инкрементальный дамп (только изменения).
    - Финальная остановка и перенос только последних дельт.
2.  **Lazy Restore:**
    - Процесс запускается на целевом хосте сразу.
    - Страницы памяти подгружаются из образа «по требованию» (через `userfaultfd`) по мере обращения процесса к ним.
    - Требует `--lazy` на этапе restore и `--lazy-pages` — отдельный демон-странице.
3.  **Page Server Mode:**
    - Страницы памяти процесса потоками (через `/proc/PID/pagemap`) отправляются напрямую на удалённый `page-server` по TCP.
    - Исключает промежуточное сохранение на локальный диск.

### Ограничения и зависимости

- **Привилегии:** Требуются права `root` или наличие `CAP_CHECKPOINT_RESTORE` (введено в Linux 5.9) и `CAP_SYS_PTRACE` для работы с `ptrace`.
- **Ядро:** Требуется поддержка `CONFIG_CHECKPOINT_RESTORE=y`. Проверить: `grep CONFIG_CHECKPOINT_RESTORE /boot/config-$(uname -r)`.
- **Внешние ресурсы:** CRIU не может автоматически сохранить состояние внешних баз данных или распределенных замков. Приложение должно восстанавливать соединения самостоятельно (через hooks).
- **Критические сети:** Приложения с `SO_REUSEPORT` или BPF-картами требуют ручной обработки.
- **Hardware state:** GPU, DPDK NIC и т.п. не сохраняются CRIU.

## Практические сценарии

### Базовое сохранение и восстановление процесса (локальный)

Самый простой сценарий — снятие и восстановление процесса на одном хосте.

```bash
# 1. Подготовка: убедитесь, что CRIU установлен
apt install criu  # Debian/Ubuntu
dnf install criu  # RHEL/CentOS

# 2. Снятие чекпоинта (остановит процесс на ~секунду)
sudo criu dump -t <PID> --images-dir /tmp/cp --shell-job -vvv

# 3. Восстановление
sudo criu restore --images-dir /tmp/cp --shell-job -vvv
```

**Флаги пояснения:**
- `-t <PID>` — целевой PID (корень дерева процессов).
- `--shell-job` — не восстанавливать TTY, если процесс запущен из shell.
- `-vvv` — verbose-режим для отладки.

### Живая миграция процесса (Network)

Сценарий переноса процесса с хоста A на хост B с использованием `page-server`.

**На хосте B (приемник):**
```bash
sudo criu restore --page-server --address <IP_B> --port 12345 --images-dir /tmp/restore
```

**На хосте A (источник):**
```bash
sudo criu dump -t <PID> --page-server --address <IP_B> --port 12345 --images-dir /tmp/dump --shell-job
```

### Использование итеративного дампа (Pre-dump)

Позволяет минимизировать время простоя для тяжелых приложений.

```bash
# 1. Первый проход (без остановки процесса)
sudo criu pre-dump -t <PID> --images-dir /tmp/cp/1 --track-mem

# 2. Повторный pre-dump (инкремент)
sudo criпе pre-dump -t <PID> --images-dir /tmp/cp/2 --prev-images-dir ../1 --track-mem

# 3. Финальный дамп (с остановкой)
sudo criu dump -t <PID> --images-dir /tmp/cp/3 --prev-images-dir ../2
```

### CRIU для systemd-сервисов

Для сервисов managed через systemd checkpoint/restore можно автоматизировать через unit-файлы:

```bash
# Снятие дампа через systemd (если ExecStartPre настроен)
sudo systemctl kill --signal=SIGSTOP myapp.service

# Снятие чекпоинта
sudo criu dump -t $(systemctl show -p MainPID myapp.service | cut -d= -f2) \
  --images-dir /var/lib/checkpoints/myapp-$(date +%s) --shell-job --leave-running

# Восстановление как сервис
sudo criu restore --images-dir /var/lib/checkpoints/myapp-... --shell-job
```

**Рекомендация:** Используйте `--leave-stopped`, а затем `systemctl start` для управления статусом.

### CRIU в контейнерах (Podman/Docker)

```bash
# Podman: сохранить контейнер
sudo podman container checkpoint mycontainer -e mycheckpoint

# Восстановить
sudo podman container restore mycheckpoint

# Docker (实验性): Docker Desktop / Docker Engine 20.10+
docker commit <container>  # для filesystem
# CRIU в Docker Enterprise/EE требует --checkpoint-dir и --runtime=runsc
```

> **Важно:** В rootless-контейнерах CRIU недоступен (см. [Podman rootless](../../../../Podman/podman_rootless.md)). Требуются привилегии `CAP_SYS_ADMIN` и `CAP_SYS_PTRACE`.

### Checkpoint через Kubelet API (v1.30+)

В современных кластерах доступен нативный API для снятия дампов контейнеров через Kubelet.

```bash
# Снятие чекпоинта контейнера (требует включенного Feature Gate 'ContainerCheckpoint')
curl -X POST "https://<node-ip>:10250/checkpoint/<ns>/<pod>/<container>"

# Список доступных чекпоинтов
curl "http://<node-ip>:10250/checkpoints/<ns>/<pod>"

# Восстановление
kubectl debug <pod> --image=<original-image> --checkpoint=<checkpoint-name>
```

Файл-образ сохраняется на узле в `/var/lib/kubelet/checkpoints/`.

### Восстановление удаленного бинарного файла

Если исполяемый файл был случайно удален, но процесс ещё запущен:

```bash
# Восстановление файла из памяти процесса
cp /proc/<PID>/exe /path/to/restored_binary
chmod +x /path/to/restored_binary

# Проверка: md5sum /proc/<PID>/exe (частично недоступен после удаления)
ls -l /proc/<PID>/exe  # покажет "(deleted)" в имени
```

### Lazy Restore для минимального времени простоя

```bash
# Снятие дампа
sudo criu dump -t <PID> --images-dir /tmp/lazy --leave-stopped

# Запуск page-server daemon (на целевом хосте или локально)
sudo criu page-server --images-dir /tmp/lazy --port 9999 --address 0.0.0.0

# Восстановление с lazy-флагом
sudo criu restore --images-dir /tmp/lazy --lazy --page-server --port 9999
```

## Дополнительная информация

### Отладка и устранение типовых ошибок

#### Частые сообщения об ошибках

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Cannot find cr_XXX syscall` | CRIU не поддерживается ядром | `grep CONFIG_CHECKPOINT_RESTORE /boot/config-$(uname -r)` |
| `ptrace operation not permitted` | `ptrace_scope` или CAP_SYS_PTRACE | `sudo sysctl kernel.yama.ptrace_scope=0`; добавить `--caps +sys_ptrace` |
| `Can't dump Ghost map` | Не удалось сохранить `MAP_SHARED`/`MAP_LOCKED` | Использовать `--leave-shared` или `--leave-locked` |
| `Unix socket SK_* has peer` | Сокет соединён с внешним процессом | Добавить `--ext-unix-sk` |
| `TCP socket in ESTABLISHED` | Требуется `--tcp-established` | Добавить флаг |
| `Cannot restore PID` | PID уже существует | Дождитесь завершения старого процесса или используйте `--pid fd` |
| `Failed to set CLONE_NEWNS` | Namespace недоступен | Проверить `--skip-mnt` или namespace-права |

#### Диагностический вывод

```bash
# Увеличьте verbosity для трассировки
sudo criu dump -t <PID> --images-dir /tmp/cp -vvv --log-file=/tmp/criu-dump.log

# Для restore: аналогично
sudo criu restore --images-dir /tmp/cp -vvv --log-file=/tmp/criu-restore.log

# Проверка образа после dump
criu exec -t <PID> -- ps aux  # dry-run, не работает без restore
```

#### Проверка обратимости (dry-run)

```bash
# Снятие только метаданных без остановки
sudo criu pre-dump --images-dir /tmp/check --just-checking -t <PID>
```

### Production debugging checklist

1. **Перед чекпоинтом:** Проверили, что процесс не имеет внешних соединений, которые нельзя восстановить?
2. **Время простоя:** Используют `pre-dump` для минимизации stop-the-world?
3. **Тест restore:** Провели сухой запуск `restore` на тестовой машине? Образ не поврежден?
4. **Сеть:** `--tcp-established` включён, если есть активные сокеты?
5. **TTY:** `--shell-job` используется, если процесс из интерактивного терминала?
6. **cgroup:** `--cgroup-file` настроен для восстановления cgroup-пути?
7. **Лимиты PID:** `pid_max` больше количества замороженных процессов? Восстановление не создаст дубли?
8. **Разрешения:** `CAP_CHECKPOINT_RESTORE` выдана сервис-аккаунту (Linux 5.9+)?

### Typical edge cases (Типовые ошибки и ограничения)

1. **PID-namespace пересечения:** Внутри контейнера PID 1 может конфликтовать с хостовым PID при restore вне контейнера. Всегда используйте `--root` + `--pid` с namespace-aware режимом.

2. **Состояние inotify:** CRIU частично восстанавливает `inotify`. Если ваш процесс слушает файлы, проверьте, что watch-список восстановлен (требуется `--inflight` для больших наборов).

3. **Timer drift:** `timerfd`, `ITIMER` восстанавливаются с поправкой на `CLOCK_MONOTONIC`. Если используется `CLOCK_REALTIME`, время может сместиться после перезагрузки. Используйте `--epoch` для синхронизации.

4. **Сокеты с TLS-сессиями:** TLS-соединения не могут быть просто «перенесены» — сертификаты и сессии будут недействительны. Приложение должно повторно аутентифицироваться. CRIU сохраняет raw TCP, но не TLS state.

5. **Файлы с `O_DIRECT`:** Дескрипторы с `O_DIRECT` восстанавливаются с потерей выравнивания буферов. Для БД с `O_DIRECT` рекомендуется `--leave-stopped` и ручной перезапуск.

6. **Блокировки (flock):** `flock`, `fcntl` не восстанавливаются на удалённых NFS-файлах. Используйте `--leave-locked` для локальных FS.

7. **Состояние ядра в Page Server:** Если page-server падает во время передачи, образ может быть повреждён. Всегда используйте `--final` для финального согласования.

8. **Cgroup v1 vs v2:** CRIU требует `--cgroup-version=2` для cgroup v2 (systemd). Для cgroup v1 используйте `--cgroup-file /etc/crictl.yaml`.

9. **Ранний сигнал SIGPIPE:** При восстановлении сокеты могут быть в «наполовину» восстановлены — приложение получит `SIGPIPE` при первой попытке записи. Убедитесь, что обработчики сигналов настроены.

10. **Ghost file size limits:** CRIU хранит удалённые файлы в образе. Если приложение имело большие удалённые логи — образ может стать огромным. Используйте `--no-ghost` для исключения.

### Инструменты для сравнения образов

```bash
# Сравнение двух образов (бета-фича)
criru diff --images-dir1 /tmp/cp1 --images-dir2 /tmp/cp2

# Просмотр образа в JSON-формате (удобно для CI/CD)
criu exec -- images-dir /tmp/cp --action show --format json
```

### См. также

- [**Устранение неисправностей процессов**](./index.md) — общая методология.
- [**Пространства имен (Namespaces)**](../../namespaces.md) — изоляция, которую CRIU должен воссоздать.
- [**Диагностика контейнеров**](../../../../Docker/Docker_troubleshooting/docker_debug.md) — контекст использования в Docker.
- [**Отладка процессов**](./debugging.md) — связанные методы (coredump, zombie, D-state).
- [**Утилита reptyr**](../../../Diagnostics/Processes/reptyr.md) — альтернативные методы сохранения сессии терминала.
- [**OOM Killer**](../oom_killer_mechanism.md) — взаимосвязь: CRIU часто используется для live-migrate перед OOM.
