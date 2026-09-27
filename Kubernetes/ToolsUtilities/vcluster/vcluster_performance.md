# vCluster — производительность и масштабирование

> Документ описывает оптимизацию производительности vCluster: бенчмарки, настройки Syncer, масштабирование на большие нагрузки. Архитектура — в [обзоре](./vcluster_overview.md), мониторинг — в [vcluster_monitoring.md](./vcluster_monitoring.md), HA — в [vcluster_high_availability.md](./vcluster_high_availability.md).

## Определения

**Throughput (Пропускная способность)** — количество операций в единицу времени. Для vCluster — число успешных API-запросов и синхронизированных объектов.

**Latency (Задержка)** — время от отправки запроса до получения ответа. Для vCluster —额外ная задержка через слой Syncer (100-300ms типично).

**Syncer Interval** — интервал реконсиляции Syncer. Меньше = быстрее реакция, больше = нагрузка на API.

**Object Count** — количество Kubernetes-объектов в vCluster. Влияет на время старта API Server и потребление памяти.

**Watch Cache** — кэш API-сервера для watch-запросов. Увеличение размера снижает нагрузку на etcd.

## Основные концепции

### Оверхед vCluster: реальная задержка

| Операция | Без vCluster | С vCluster | Дополнительный оверхед |
| :--- | :--- | :--- | :--- |
| `kubectl get pods` | ~50ms | ~150ms | +100ms (Syncer proxy) |
| `kubectl create deployment` | ~200ms | ~500ms | +300ms (雙方向 синхронизация) |
| Pod Ready | ~30s | ~35s | +5s (Syncer реконсиляция) |
| Service discovery | ~10ms | ~15ms | +5ms (CoreDNS isolation) |
| HPA scale event | ~15s | ~20s | +5s (Syncer latency) |

> Задержка добавляется на каждый API-запрос к vCluster. Для latency-critical приложений (HFT, gaming) это критично.

### Факторы производительности

| Фактор | Влияние | Оптимизация |
| :--- | :--- | :--- |
| **Число объектов** | Чем больше объектов, тем медленнее API Server и Syncer | Очистка неиспользуемых CRD, limit на количество подов |
| **Syncer interval** | Меньше интервал = быстрее реакция, больше нагрузка | `--sync-interval=5s` для production, `1s` для CI |
| **Backing Store** | SQLite быстрее etcd для малых объёмов, etcd для больших | K3s/SQLite для dev, etcd для production |
| **Ресурсы Control Plane** | CPU/RAM ограничивают throughput API | Увеличить limits при нагрузке |
| **CNI plugin** | Calico/Cilium быстрее flannel | Используйте Calico/Cilium на хосте |
| **Disk I/O** | etcd чувствителен к задержкам диска | NVMe SSD для etcd |

### Настройки Syncer для производительности

```yaml
# vcluster.yaml — оптимизированные настройки
controlPlane:
  distro:
    k8s:
      enabled: true
  apiserver:
    extraArgs:
      # Увеличить размер watch cache (по умолчанию 1000)
      - --watch-cache-size=5000
      # Увеличить maximum-requests-inflight
      - --max-requests-inflight=400
      - --max-mutating-requests-inflight=200

sync:
  toHost:
    pods:
      enabled: true
      # Оптимизация: синхронизировать только нужные поля
      patches:
        - path: metadata.labels
          expression: 'value'
    services:
      enabled: true
    # Отключить синхронизацию ненужных ресурсов
    events:
      enabled: false  # События не критичны для работы
  fromHost:
    storageClasses:
      enabled: true
    nodes:
      enabled: true
    # Отключить если не используются
    priorityClasses:
      enabled: false
    csiNodes:
      enabled: false
    volumeAttachments:
      enabled: false
```

### Масштабирование: количество vCluster на хост

| Конфигурация vCluster | RAM на vCluster | CPU на vCluster | vCluster на 32GB/8CPU хосте |
| :--- | :--- | :--- | :--- |
| K3s, 1 реплика, 50 объектов | 150Mi | 100m | ~80 |
| K8s, 1 реплика, 100 объектов | 430Mi | 300m | ~30 |
| K8s, 3 реплики, 500 объектов | 1.5Gi | 900m | ~8 |
| K8s, 3 реплики, 1000+ объектов | 2Gi+ | 1.2Gi | ~5 |

Формула:

```text
Макс. vCluster = (Доступная RAM - 2GB (system)) / RAM_per_vCluster
Учитывая CPU: Макс. vCluster = (Доступные CPU - 1 (system)) / CPU_per_vCluster
Берём минимум из двух.
```

### Тестирование производительности: бенчмарк API

```bash
#!/usr/bin/env bash
# vcluster-benchmark.sh
set -euo pipefail

VC_NAME="${1:?Usage: benchmark.sh <vcluster-name> <namespace>}"
VC_NS="${2:?Usage: benchmark.sh <vcluster-name> <namespace>}"
RESULTS_FILE="benchmark-${VC_NAME}-$(date +%Y%m%d).json"

# Подключиться
vcluster connect "$VC_NAME" -n "$VC_NS" --update-current

echo "=== vCluster Performance Benchmark ==="
echo "Cluster: $VC_NAME"
echo "Time: $(date)"

# 1. Throughput: количество get-запросов в секунду
echo ""
echo "--- API GET Throughput ---"
start=$(date +%s%N)
for i in $(seq 1 100); do
  kubectl get pods -A > /dev/null 2>&1
done
end=$(date +%s%N)
duration_ms=$(( (end - start) / 1000000 ))
rps=$(echo "scale=2; 100000 / $duration_ms" | bc)
echo "GET pods (100 requests): ${duration_ms}ms total, ${rps} req/s"

# 2. Latency: p50, p95, p99 для create/delete
echo ""
echo "--- Create/Delete Latency ---"
for i in $(seq 1 20); do
  start=$(date +%s%N)
  kubectl create deployment bench-$i --image=nginx --replicas=1 > /dev/null 2>&1
  end=$(date +%s%N)
  echo "Create: $(( (end - start) / 1000000 ))ms"
done

# 3. Синхронизация: время до Ready
echo ""
echo "--- Pod Ready Time ---"
kubectl create deployment bench-ready --image=nginx --replicas=1 > /dev/null 2>&1
start=$(date +%s%N)
kubectl rollout status deployment/bench-ready --timeout=120s > /dev/null 2>&1
end=$(date +%s%N)
echo "Deployment Ready: $(( (end - start) / 1000000 ))ms"

# 4. Cleanup
echo ""
echo "--- Cleanup ---"
kubectl delete deployment --all > /dev/null 2>&1
echo "Deleted all deployments"

echo ""
echo "=== Benchmark Complete ==="
```

### Тестирование производительности: нагрузка на Syncer

```bash
#!/usr/bin/env bash
# syncer-load-test.sh
set -euo pipefail

VC_NAME="${1:?Usage: syncer-load-test.sh <vcluster-name> <namespace>}"
VC_NS="${2:?Usage: syncer-load-test.sh <vcluster-name> <namespace>}"
NUM_OBJECTS="${3:-100}"

vcluster connect "$VC_NAME" -n "$VC_NS" --update-current

echo "Creating $NUM_OBJECTS deployments..."

# Создать много объектов
for i in $(seq 1 $NUM_OBJECTS); do
  kubectl create deployment load-$i --image=nginx --replicas=1 > /dev/null 2>&1
done

echo "Waiting for Syncer to sync..."
sleep 30

# Проверить, что все синхронизированы
SYNCED=$(kubectl -n "$VC_NS" get pods -l vcluster.loft.sh/managed-by --no-headers | wc -l)
echo "Synced pods on host: $SYNCED"

# Проверить ошибки Syncer
ERRORS=$(kubectl -n "$VC_NS" logs -l app=vcluster -c syncer --tail=1000 | grep -c "error" || echo 0)
echo "Syncer errors: $ERRORS"

# Cleanup
kubectl delete deployment --all > /dev/null 2>&1
echo "Cleanup complete"
```

### Оптимизация для разных сценариев

| Сценарий | Рекомендации |
| :--- | :--- |
| **CI/CD (ephemeral)** | K3s distro, 1 реплика, `--sync-interval=1s`, baseline PSA, 100m CPU |
| **Development** | K3s distro, 1 реплика, `--sync-interval=2s`, sleep mode, 200m CPU |
| **Staging** | K8s distro, 1-3 реплики, `--sync-interval=5s`, restricted PSA, 500m CPU |
| **Production** | K8s distro, 3 реплики, external etcd, `--sync-interval=5s`, HA, 1Gi+ CPU |
| **High-frequency trading** | Standalone mode (без Syncer), direct CNI, bare-metal |
| **Edge/IoT** | K3s distro, 1 реплика, SQLite, minimal resources |

### Оптимизация количества CRD

Большое число CRD (>100) замедляет старт API Server:

```bash
# Посчитать CRD в vCluster
kubectl get crd --no-headers | wc -l

# Посчитать CRD на хосте
kubectl get crd --no-headers | wc -l

# Оптимизация: удалить неиспользуемые CRD
kubectl get crd -o name | grep -v "core" | head -20  # Посмотреть
kubectl delete crd <unused-crd>  # Удалить
```

### Диагностика проблем производительности

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `kubectl get pods` медленный (>2s) | Большинство объектов, маленький watch cache | Увеличить `--watch-cache-size` |
| Syncer падает с OOM | Слишком много объектов, мало RAM | Увеличить memory limit, уменьшить объекты |
| API Server 503 | Перегрузка CPU | Увеличить CPU limit, добавить узлы |
| etcd slow fsync | Медленный диск | Перейти на NVMe SSD |
| HPA не масштабируется | Syncer задержка >30s | Уменьшить `--sync-interval`, оптимизировать Syncer |
| Поды не готовы | ImagePullBackOff или readiness probe fail | Проверить registry, увеличить timeout |

### Лучшие практики

- **Мониторинг через baseline:** Запомните нормальные метрики и алертируйте на отклонение.
- **Разные настройки для разных окружений:** CI/dev/prod должны иметь разные `--sync-interval` и ресурсы.
- **Очистка неиспользуемых CRD:** Регулярно проверяйте `kubectl get crd` и удаляйте ненужные.
- **Ограничение количества объектов:** Используйте `ResourceQuota` для ограничения числа подов/секретов.
- **Регулярные бенчмарки:** Запускайте benchmark перед обновлением vCluster для оценки влияния.
- **Экономия ресурсов:** Для dev/CI используйте K3s с минимальными ресурсами.

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — мониторинг и observability](./vcluster_monitoring.md)
- [vCluster — высокая доступность](./vcluster_high_availability.md)

### См. также

- [Prometheus — метрики производительности](../../Prometheus/)
- [Grafana — дашборды производительности](../../Grafana/)

### Внешние ссылки

- [vCluster Performance Documentation](https://www.vcluster.com/docs/other-topics/performance)
- [Kubernetes API Performance](https://kubernetes.io/docs/reference/using-api/api-concepts/#api-priority-and-fairness)
