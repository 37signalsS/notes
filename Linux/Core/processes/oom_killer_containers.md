# OOM Killer в контейнерных средах

## Определения

**OOM Killer в контейнерах** — это режим работы ядра Linux, при котором механизмы принудительного завершения процессов применяются в рамках изолированных ресурсов (контрольных групп). Это позволяет ядру пресекать утечки памяти внутри контейнера (Docker/Kubernetes), не допуская деградации всей хост-системы.

**Memory QoS** — механизм (введен в K8s 1.22+), использующий возможности cgroups v2 для более гранулярного управления памятью контейнеров через мягкие лимиты и приоритеты.

**Silent OOM (Тихий OOM)** — ситуация в cgroups v2, когда ядро убивает только конкретный дочерний процесс внутри контейнера, превысившего лимит. Если при этом PID 1 контейнера остается жив, сам контейнер продолжает работу, что затрудняет внешнюю диагностику.

**Cgroup-local OOM** — срабатывание OOM Killer в рамках одной контрольной группы при превышении `memory.max`. Жертва выбирается только среди процессов данной группы.

**System-wide OOM** — глобальная нехватка памяти на хосте. Ядро сканирует все процессы системы, включая процессы контейнеров, и выбирает жертву по алгоритму `oom_badness()`.

## Основные концепции

### Двухуровневая модель срабатывания

В контейнеризированных ОС сосуществуют два уровня защиты:

1.  **Системный (Global OOM):**
    - **Триггер:** Исчерпание всей доступной физической RAM и Swap на хосте.
    - **Логика:** Ядро сканирует все процессы в системе. Выбирается процесс с наибольшим `oom_score`.
    - **Результат:** Может быть убит любой процесс (включая критичные службы хоста), если их рейтинг высок.
2.  **Групповой (Cgroup OOM):**
    - **Триггер:** Превышение жесткого лимита контрольной группы (`memory.max` в v2 или `memory.limit_in_bytes` в v1).
    - **Логика:** Сканируются процессы только внутри данной cgroup.
    - **Результат:** Убивается «виновник» внутри контейнера. Хост и другие контейнеры не страдают.

### Пути к cgroup в зависимости от рантайма

Для диагностики и ручной настройки необходимо знать путь к cgroup контейнера на хосте. Путь зависит от используемого container runtime:

| Runtime | Стандартный путь cgroup (v2) |
| :--- | :--- |
| **Docker** | `/sys/fs/cgroup/system.slice/docker-<id>.scope/` |
| **containerd** | `/sys/fs/cgroup/system.slice/containerd-<id>.scope/` |
| **CRI-O** | `/sys/fs/cgroup/system.slice/crio-<id>.scope/` |
| **Kubernetes (kubelet)** | `/sys/fs/cgroup/kubepods.slice/kubepods-pod<uid>.slice/` |

**Автоматическое обнаружение cgroup контейнера:**
```bash
# Найти cgroup по имени контейнера (Docker)
CONTAINER_ID=$(docker inspect --format '{{.Id}}' <container_name>)
find /sys/fs/cgroup -name "*${CONTAINER_ID}*" -type d 2>/dev/null

# Найти cgroup по PID процесса (универсальный метод)
PID=$(docker inspect --format '{{.State.Pid}}' <container_name>)
cat /proc/$PID/cgroup
# → 0::/system.slice/docker-abc123.scope
```

### Механизмы cgroups v2 для управления памятью

Cgroups v2 (стандарт для ядер 5.x+ и современных дистрибутивов) предлагает 4 уровня контроля:

- **`memory.min` (Hard Guarantee):** Память, которая **никогда** не будет отобрана ядром для нужд системы. Если группа требует больше, чем `min`, а памяти нет — сразу OOM. В K8s соответствует `requests.memory`.
- **`memory.low` (Best-effort Guarantee):** Ядро пытается не отбирать эту память, пока это возможно. Если давление на RAM становится критическим, эта память может быть рекультивирована (reclaimed).
- **`memory.high` (Throttle Threshold):** Мягкий лимит. При его достижении ядро начинает принудительно замедлять (throttle) процессы группы, заставляя их тратить циклы CPU на очистку собственной памяти, чтобы избежать жесткого OOM.
- **`memory.max` (Hard Limit):** Абсолютный потолок. Превышение ведет к немедленному срабатыванию OOM Killer. В K8s соответствует `limits.memory`.

### События cgroups v2 (`memory.events`)

Файл `memory.events` предоставляет счетчики ключевых событий памяти для контрольной группы:

| Счетчик | Описание |
| :--- | :--- |
| **`low`** | Количество раз, когда потребление достигло `memory.low` и ядро начало reclaim. |
| **`high`** | Количество раз, когда потребление достигло `memory.high` и ядро применило throttling. |
| **`max`** | Количество раз, когда потребование достигло `memory.max`. |
| **`oom`** | Количество раз, когда ядро вызвало OOM Killer внутри данной cgroup. |
| **`oom_kill`** | Количество процессов, убитых OOM Killer внутри данной cgroup. |

**Пример интерпретации:**
```text
low: 0
high: 42
max: 3
oom: 2
oom_kill: 2
```
- `high: 42` — приложение 42 раза приближалось к пределу, но throttling успевал сработать.
- `max: 3` — 3 раза потребление достигло абсолютного лимита.
- `oom: 2` / `oom_kill: 2` — 2 раза OOM Killer убивал процессы внутри cgroup.

### PSI и Memory Pressure в контейнерах

Cgroups v2 интегрированы с **[Pressure Stall Information (PSI)](../kernel/psi.md)**. В каждой cgroup доступен файл `memory.pressure`:

```bash
# Внутри cgroup контейнера
cat /sys/fs/cgroup/kubepods.slice/.../memory.pressure
# → some avg10=12.34 avg60=5.67 avg300=2.34 total=123456789
# → full avg10=0.00 avg60=0.00 avg300=0.00 total=0
```

- **`some`** — процент времени, когда хотя бы один процесс ждал памяти.
- **`full`** — процент времени, когда **все** процессы группы ждали памяти (критическое состояние).

**Пороги для алертинга:**
- `some avg10 > 10%` — приложение испытывает дефицит памяти.
- `full avg10 > 1%` — система парализована ожиданием памяти (imminent OOM).

### Swap в cgroups v2

В cgroups v2 управление swap контейнера вынесено в отдельные файлы:

| Файл | Описание |
| :--- | :--- |
| **`memory.swap.current`** | Текущее потребление swap контейнером. |
| **`memory.swap.max`** | Жесткий лимит swap. При достижении процессы получают `-ENOMEM`. |
| **`memory.zswap.current`** | Потребление сжатого swap (zswap). |
| **`memory.zswap.max`** | Лимит сжатого swap. |

**Пример:**
```bash
# Установить лимит swap = 1GB
echo 1G | sudo tee /sys/fs/cgroup/.../memory.swap.max

# Проверить текущее использование
cat /sys/fs/cgroup/.../memory.swap.current
```

### Расчет oom_score_adj в Kubernetes

Kubernetes транслирует бизнес-приоритеты (QoS) в ядро Linux. Формула расчета `oom_score_adj` для подов:

| Класс QoS | Значение `oom_score_adj` | Формула / Логика |
| :--- | :--- | :--- |
| **Guaranteed** | **-997** | Практически неуязвим для системного OOM. |
| **BestEffort** | **1000** | Первые в очереди на удаление. |
| **Burstable** | **2 – 999** | Вычисляется динамически (см. ниже). |

**Формула для Burstable:**
`oom_score_adj = min(max(2, 1000 - (1000 * memory_requests) / node_capacity), 999)`
*Логика:* Чем большую долю памяти узла резервирует под (через `requests`), тем ниже его `oom_score_adj` и тем выше шансы выжить при глобальной нехватке памяти.

## Практические сценарии

### Групповое завершение (memory.oom.group)

Для приложений с архитектурой «Master-Worker» (Nginx, PostgreSQL) смерть одного воркера может быть критична. В cgroups v2 можно гарантировать атомность завершения:
```bash
# Включить групповой OOM (все или ничего)
# При срабатывании OOM в любом процессе группы, ядро убивает ВСЮ группу целиком.
echo 1 > /sys/fs/cgroup/system.slice/container-id.scope/memory.oom.group
```

**Почему это важно:** Без `memory.oom.group=1` при превышении лимита ядро убивает только один «виновный» процесс. Если это воркер в пуле, остальные продолжат работать, но приложение может потерять целостность данных или повиснуть в неопределенном состоянии. Атомарное завершение позволяет оркестратору (Kubernetes, systemd) перезапустить контейнер в чистом состоянии.

### Диагностика «Тихого OOM» (Silent OOM)

Если контейнер «глючит», но Kubernetes показывает статус `Running`, проверьте счетчики событий cgroups внутри контейнера:
```bash
# Внутри контейнера или через nsenter
cat /sys/fs/cgroup/memory.events
# → low: 0, high: 45, max: 2, oom: 1, oom_kill: 1
```
Если `oom_kill` > 0, значит подпроцесс был убит, но PID 1 контейнера выжил.

**Пошаговый ранбук Silent OOM:**
1. Проверьте `memory.events` на наличие `oom_kill > 0`.
2. Сравните код завершения подпроцесса: если `137` — это SIGKILL от OOM Killer.
3. Проверьте логи приложения на наличие `segmentation fault`, `SIGABRT`, или внезапных `connection reset`.
4. Увеличьте `limits.memory` или настройте `memory.high` для throttling вместо kill.

### Docker: полный спектр флагов OOM

#### Запуск с защитой от OOM

```bash
# Повышенный приоритет выживания на хосте (-1000 = иммунитет)
docker run --oom-score-adj=-500 my-app

# Мягкий лимит (throttling перед OOM)
docker run -m 1g --memory-reservation 512m my-app

# Отключение OOM killer (опасно! только с жестким лимитом)
docker run -m 1g --oom-kill-disable my-app
```

#### Управление swap

```bash
# Запрет swap (memory + swap = memory)
docker run -d --memory=512m --memory-swap=512m nginx

# Разрешить swap до 1GB
docker run -d --memory=512m --memory-swap=1g nginx

# Отключить swappiness (swap только при memory.max)
docker run -d --memory=512m --memory-swappiness=0 nginx
```

**Формула `--memory-swap`:** `--memory-swap` = `--memory` + swap. Если `--memory-swap=-1` — без ограничений swap.

#### Динамическое изменение лимитов

```bash
# Увеличить память без перезапуска
docker update --memory=2g <container>

# Установить все лимиты
docker update \
  --memory=2g \
  --memory-swap=2g \
  --cpus=2.0 \
  --pids-limit=500 \
  <container>
```

**Ограничения:** `--memory` можно только увеличить (уменьшение требует перезапуска). `--cpus` можно менять свободно.

#### Docker Compose

```yaml
services:
  app:
    image: my-app:latest
    deploy:
      resources:
        limits:
          memory: 2g
          cpus: '2.0'
        reservations:
          memory: 1g
    mem_swappiness: 0
    oom_score_adj: -500
```

### Kubernetes: манифесты и диагностика

#### Полный манифест пода с защитой от OOM

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: oom-protected-app
spec:
  containers:
  - name: app
    image: my-app:latest
    resources:
      requests:
        memory: "1Gi"
        cpu: "500m"
      limits:
        memory: "2Gi"
        cpu: "2"
    securityContext:
      # Не позволяет ядру менять oom_score_adj (K8s перезапишет на основе QoS)
      allowPrivilegeEscalation: false
    # cgroups v2: групповой OOM (atomic kill)
    # Примечание: в K8s настраивается через RuntimeClass или kubelet config
```

#### Проверка класса QoS и oom_score_adj

```bash
# Проверить QoS класс пода
kubectl get pod <pod-name> -o jsonpath='{.status.qosClass}'
# → Guaranteed / Burstable / BestEffort

# Проверить oom_score_adj внутри работающего пода
kubectl exec <pod-name> -- cat /proc/1/oom_score_adj
# → -997 (Guaranteed) или 1000 (BestEffort)

# На хосте: найти cgroup пода и проверить memory.events
POD_UID=$(kubectl get pod <pod-name> -o jsonpath='{.metadata.uid}')
cat /sys/fs/cgroup/kubepods.slice/kubepods-pod${POD_UID}.slice/memory.events
```

### Поиск cgroup-пути на хосте

```bash
# Метод 1: через PID процесса
PID=$(docker inspect --format '{{.State.Pid}}' <container_name>)
cat /proc/$PID/cgroup
# → 0::/system.slice/docker-abc123.scope

# Метод 2: через systemd-cgls
systemd-cgls /system.slice/docker-<id>.scope

# Метод 3: через kubectl и node SSH
POD_UID=$(kubectl get pod <pod-name> -o jsonpath='{.metadata.uid}')
find /sys/fs/cgroup -path "*kubepods*pod${POD_UID}*" -name memory.max
```

### Проактивная защита через memory.high

Настройка `memory.high` позволяет избежать жесткого OOM, заставляя приложение очищать память до достижения `memory.max`:

```bash
# Docker: мягкий лимит 80% от жесткого
docker run -d \
  --memory=2g \
  --memory-reservation=1.6g \
  my-app

# Kubernetes: memory.high не является нативным полем API,
# но может быть применен через RuntimeClass или kubelet config:
# --cgroup-driver=systemd
# В node-уровневом runtime class:
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: runsc
scheduling:
  nodeSelector:
    memory.high: "1.6g"  # Пример, зависит от реализации рантайма
```

**Принцип:** `memory.high` генерирует CPU throttle, давая GC (Garbage Collector) время освободить память. Это превращает внезапный OOMKilled в предсказуемое замедление.

### Мониторинг и алертинг

```bash
# Скрипт мониторинга для контейнера (запускать на хосте)
CONTAINER_CGROUP="/sys/fs/cgroup/system.slice/docker-<id>.scope"

# Проверка счетчиков OOM
if [ $(cat $CONTAINER_CGROUP/memory.events | awk '/oom_kill/ {print $2}') -gt 0 ]; then
    echo "ALERT: OOM kills detected in container"
    # Отправка алерта в Prometheus/Alertmanager/Slack
fi

# Мониторинг PSI
while true; do
    FULL=$(cat $CONTAINER_CGROUP/memory.pressure | awk '/full/ {print $4}' | cut -d= -f2)
    if (( $(echo "$FULL > 1.0" | bc -l) )); then
        echo "ALERT: Memory pressure full > 1%"
    fi
    sleep 5
done
```

### Стресс-тестирование контейнера

```bash
# Установка stress-ng
docker run -it --rm --privileged alpine sh -c "apk add stress-ng"

# Стресс-тест с контролем cgroup
docker run -d --memory=512m --name stress-test alpine stress-ng --vm 1 --vm-bytes 400M --timeout 60s

# Мониторинг в реальном времени
watch -n 1 'cat /sys/fs/cgroup/system.slice/docker-stress-test.scope/memory.events'

# Ожидаемый результат:
# high растет (throttling), затем max (достигнут лимит), затем oom_kill
```

### Восстановление после OOMKilled

```bash
# 1. Проверить статус контейнера
docker ps -a --filter "status=exited" --filter "exited=137"

# 2. Получить логи до падения
docker logs <container_name> --tail 100

# 3. Проверить dmesg хоста
dmesg -T | grep -i "killed process"

# 4. Проверить cgroup события
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.events

# 5. Экспорт метрик для анализа
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.stat > /tmp/memory_stat.txt
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.current >> /tmp/memory_stat.txt
```

## Дополнительная информация

### Код завершения 137 и контейнеры

Код `137` (128 + 9) — это «черная метка» OOM Killer.
- Если контейнер завершился с кодом 137, в K8s вы увидите `Reason: OOMKilled`.
- Если код 137 у подпроцесса, контейнер может остаться `Running` (см. Silent OOM).

**Проверка в Docker:**
```bash
docker inspect <container> --format '{{.State.OOMKilled}}'
# → true
```

### Почему лимиты Sidecar-контейнеров критичны

Sidecar-контейнеры (например, Istio, Fluent-bit) делят тот же лимит памяти, если они в одном поде? Нет, в K8s у каждого контейнера в поде свои cgroups лимиты. Однако `oom_score_adj` вычисляется для пода в целом. Если прожорливый sidecar вызовет **системный** OOM, ядро может убить основной контейнер приложения, если его `oom_score` окажется выше.

### Взаимодействие с container runtime (runc/crun)

Современные container runtimes (runc, crun, kata) реализуют cgroups через системные вызовы ядра. Поведение при OOM может незначительно отличаться:

- **runc (Docker, containerd по умолчанию):** Использует libcontainer для настройки cgroups. При OOM в контейнере runc завершает контейнер с кодом 137.
- **crun:** Более легковесная альтернатива runc, написанная на C. Поддерживает все cgroups v2 фичи, включая `memory.oom.group`.
- **Kata Containers:** Легковесные ВМ. OOM обрабатывается на уровне гостевого ядра, но хостовое ядро также может убить процесс Kata при системном дефиците.

**Практический совет:** При миграции с runc на crun или Kata перетестируйте поведение при OOM, особенно групповое завершение (`memory.oom.group`).

### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Silent OOM в K8s** | `oom_kill` > 0, но контейнер жив | Увеличить `limits.memory` или настроить `memory.high` |
| **System-wide OOM убивает контейнер** | `oom_score_adj` слишком высок | Перевести под в класс `Guaranteed` или `Burstable` |
| **OOM при наличии free RAM** | `memory.min` превышен или фрагментация | Уменьшить `memory.min`, проверить `buddyinfo` |
| **Throttling вместо OOM** | `memory.high` слишком близко к `memory.max` | Увеличить gap между `high` и `max` до 20-30% |
| **OOMKilled после обновления образа** | Утечка памяти в новой версии | Профилировать память, увеличить лимиты или исправить утечку |

### См. также

- [**Механизм OOM Killer**](./oom_killer_mechanism.md) — общая теория и алгоритм badness.
- [**Управление OOM Killer**](./oom_killer_management.md) — настройка `oom_score_adj`, systemd-oomd, `choom`.
- [**Диагностика OOM Killer**](./oom_killer_diagnostics.md) — разбор логов, bpftrace, eBPF.
- [**Контрольные группы (cgroups)**](../cgroups.md) — архитектура изоляции ресурсов.
- [**Давление на ресурсы (PSI)**](../kernel/psi.md) — превентивный мониторинг и метрики.
- [**Ограничение ресурсов в Docker**](../../../Docker/Docker_security/resource_limits.md) — Docker-флаги и cgroups.
- [**Управление ресурсами в Kubernetes**](../../../Kubernetes/Scheduling/qos_limit_and_requests.md) — детальный разбор requests/limits и QoS.
