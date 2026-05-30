# OOM Killer in Containers

## Определения

**OOM Killer в контейнерах** — поведение механизма OOM Killer при работе в изолированных средах (Docker, Kubernetes). Работает на двух уровнях: ядро хоста и cgroups контейнера.

**OOMKilled** — статус завершения контейнера, означающий что процесс был принудительно завершен OOM Killer из-за превышения лимита памяти.

## Основные концепции

### Уровни OOM Killer в контейнерах

| Уровень | Механизм | Результат |
| :--- | :--- | :--- |
| **Хост** | Ядро Linux | Убивает процесс контейнера как обычный процесс |
| **Контейнер** | cgroups `memory.max` (v2) / `memory.limit_in_bytes` (v1) | OOM внутри контейнера, контейнер падает с `OOMKilled` |

### Взаимодействие cgroups и OOM Killer

- **cgroups v2** используют `memory.max` — жесткий лимит, при достижении которого вызывается OOM Killer внутри cgroup.
- **cgroups v1** используют `memory.limit_in_bytes` — аналогичное поведение, но с иной иерархией.
- OOM Killer в контейнере убивает **процессы внутри cgroup**, а не весь контейнер. Runtime (Docker, containerd) обнаруживает падение и перезапускает контейнер.

### Kubernetes QoS классы и OOM

Kubernetes присваивает подам QoS классы на основе `requests` и `limits`, которые влияют на `oom_score_adj`:

| QoS класс | `oom_score_adj` | Описание |
| :--- | :--- | :--- |
| **Guaranteed** | -998 | Наивысшая защита (`requests` = `limits`) |
| **Burstable** | 2–999 | Средняя защита (зависит от соотношения request/limit) |
| **BestEffort** | 1000 | Первый кандидат на удаление (нет `requests`/`limits`) |

> **Важно:** QoS класс защищает от **Node Pressure Eviction**, но не от OOM Killer. Под с QoS `Guaranteed` будет убит OOM Killer при превышении собственного `limits.memory`.

## Практические сценарии

### Docker: Проверка и настройка OOM

```bash
# Проверить OOMKilled статус контейнера
docker inspect <container> --format '{{.State.OOMKilled}}'

# Запустить с измененным oom_score_adj
docker run --oom-score-adj=500 nginx

# Запустить с отключенным OOM Killer (только с лимитом памяти)
docker run -m 512m --oom-kill-disable=true nginx
```

> **Важно:** `--oom-kill-disable` работает только вместе с `-m` (ограничение памяти). Без лимита контейнер может исчерпать всю память хоста.

### Kubernetes: Диагностика OOMKilled

```bash
# Проверить причину завершения контейнера
kubectl describe pod <pod-name> | grep -A 5 "Last State"
# Ищем: Reason: OOMKilled, Exit Code: 137

# Проверить QoS класс пода
kubectl get pod <pod-name> -o jsonpath='{.status.qosClass}'

# Найти все поды с OOMKilled в namespace
kubectl get events --field-selector reason=OOMKilling -n <namespace>
```

### Kubernetes: Предотвращение OOMKilled

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app
spec:
  containers:
  - name: app
    image: my-app:latest
    resources:
      requests:
        memory: "256Mi"
        cpu: "250m"
      limits:
        memory: "512Mi"  # При превышении — OOMKilled
        cpu: "500m"
```

**Рекомендации по лимитам:**

1. Установите `requests` и `limits` для всех контейнеров
2. `limits.memory` должен быть выше пикового потребления (мониторинг через Prometheus/Grafana)
3. Для Java-приложений учитывайте JVM heap + non-heap память (установите `-XX:MaxRAMPercentage`)
4. Настройте алерты для своевременного обнаружения инцидентов. Полный перечень правил и YAML-конфигураций для Grafana представлен в SSoT-файле: [**Алерты для Kubernetes в Grafana**](../../../Grafana/alerting/kubernetes_alerts.md).

### Диагностика утечки памяти

```bash
# Проверить потребление памяти контейнером
docker stats <container>

# Проверить логи на предмет OOM
dmesg | grep -i "out of memory"
journalctl -k | grep -i "oom"

# Проверить лимиты cgroups (v2)
cat /sys/fs/cgroup/system.slice/docker-<container-id>.scope/memory.max
```

## Дополнительная информация

### OOM Killer и exit code 137

Контейнер, убитый OOM Killer, имеет exit code **137** (128 + 9 = SIGKILL). Это стандартный код завершения для процессов, принудительно завершенных ядром.

```bash
# Проверить код выхода
docker inspect <container> --format '{{.State.ExitCode}}'
# 137 = вероятный OOMKilled
```

### Различия OOM Killer и Eviction

| Характеристика | OOMKilled | Eviction |
| :--- | :--- | :--- |
| **Причина** | Превышение `limits.memory` контейнера | Нехватка ресурсов на узле |
| **Инициатор** | Ядро Linux (OOM Killer) | Kubelet |
| **Статус пода** | `OOMKilled` (Reason в Last State) | `Evicted` |
| **Код выхода** | 137 (SIGKILL) | 143 (SIGTERM) или другой |
| **QoS влияние** | Убивает независимо от QoS | BestEffort → Burstable → Guaranteed |

Подробнее: [Eviction в Kubernetes](../../../Kubernetes/Troubleshooting/Common_Errors/PodEvicted/memory_eviction.md).

### OOM Killer и cgroups v2

В cgroups v2 OOM Killer работает иначе, чем в v1:

- **v1:** При достижении `memory.limit_in_bytes` OOM Killer убивает процесс немедленно
- **v2:** При достижении `memory.max` OOM Killer пытается освободить память внутри cgroup перед убийством процесса
- **v2** поддерживает `memory.oom.group` — группировка процессов для совместного убийства (useful для контейнеров)

---

Механизм работы OOM Killer описан в [**OOM Killer Mechanism**](./oom_killer_mechanism.md). Управление поведением OOM Killer — в [**OOM Killer Management**](./oom_killer_management.md).
