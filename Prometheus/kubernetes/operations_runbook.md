# Операционный Runbook: Prometheus в Kubernetes

## Определения

**Operations Runbook** — пошаговые инструкции для повседневных операционных задач по управлению стеком мониторинга Prometheus в Kubernetes. Охватывает ежедневные, еженедельные и ежемесячные процедуры.

> **См. также:** [Troubleshooting](./operator/troubleshooting.md), [Self-Monitoring](./operator/self_monitoring.md), [Resource Sizing](./operator/resource_sizing.md).

---

## Ежедневные задачи

### Утренняя проверка статуса (5 минут)

```bash
# 1. Статус всех подов
kubectl get pods -n monitoring -o wide

# 2. Проверка потребления ресурсов
kubectl top pods -n monitoring --sort-by=memory

# 3. Проверка ошибок в логах
kubectl logs -n monitoring prometheus-main-0 -c prometheus --since=24h | grep -i "error\|fail" | tail -20
kubectl logs -n monitoring alertmanager-main-0 -c alertmanager --since=24h | grep -i "error\|fail" | tail -20
kubectl logs -n monitoring deploy/prometheus-operator --since=24h | grep -i "error\|fail" | tail -20

# 4. Проверка количества активных серий
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=prometheus_tsdb_head_series' | jq '.data.result[0].value[1]'

# 5. Проверка Remote Write
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=prometheus_remote_write_samples_appended_total' | jq '.data.result[0].value[1]'
```

### Проверка алертов

```bash
# 1. Активные firing алерты
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/rules' | jq '[.data.groups[].rules[] | select(.state=="firing") | {name: .name, severity: .labels.severity}]'

# 2. Pending алерты (могут перейти в firing)
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/rules' | jq '[.data.groups[].rules[] | select(.state=="pending") | {name: .name, duration: .duration}]'

# 3. Silences (подавленные алерты)
kubectl exec -n monitoring alertmanager-main-0 -c alertmanager -- \
  amtool silence query
```

### Проверка целей скрейпинга

```bash
# 1. Все цели в статусе DOWN
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/targets' | jq '[.data.activeTargets[] | select(.health!="up") | {instance: .labels.instance, job: .labels.job, health: .health, lastError: .lastError}]'

# 2. Количество целей по job
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/targets' | jq '[.data.activeTargets[] | .labels.job] | group_by(.) | map({job: .[0], count: length})'

# 3. Скорость скрейпинга (scrape duration)
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=avg(scrape_duration_seconds) by (job)' | jq '.data.result[] | {job: .metric.job, duration: .value[1]}'
```

---

## Еженедельные задачи

### Проверка здоровья TSDB

```bash
# 1. Статус TSDB
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/status/tsdb' | jq '{
    headStats: .data.headStats,
    headMinTime: (.data.headStats.minTime / 1000 | todate),
    headMaxTime: (.data.headStats.maxTime / 1000 | todate),
    numSeries: .data.headStats.numSeries
  }'

# 2. Размер TSDB на диске
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  du -sh /prometheus/

# 3. Количество блоков
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  ls -la /prometheus/ | head -20
```

### Проверка кворума Alertmanager

```bash
# 1. Участники кластера
kubectl exec -n monitoring alertmanager-main-0 -c alertmanager -- \
  amtool cluster members

# 2. Статус кластера
kubectl exec -n monitoring alertmanager-main-0 -c alertmanager -- \
  amtool cluster status

# 3. Проверкаossip-соединений
kubectl exec -n monitoring alertmanager-main-0 -c alertmanager -- \
  amtool cluster peers
```

### Проверка PDB (Pod Disruption Budget)

```bash
# 1. Статус PDB
kubectl get pdb -n monitoring

# 2. Проверка что PDB не блокирует обновления
kubectl describe pdb prometheus-main -n monitoring
kubectl describe pdb alertmanager-main -n monitoring
```

### Очистка старых данных

```bash
# 1. Проверка размера WAL
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  du -sh /prometheus/wal/

# 2. Проверка compaction
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=prometheus_tsdb_compactions_total' | jq '.data.result[0].value[1]'

# 3. Принудительная compaction (если необходимо)
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/admin/tsdb/clean_tombstones' -X POST
```

---

## Ежемесячные задачи

### Аудит RBAC

```bash
# 1. Проверка прав ServiceAccount
kubectl auth can-i --list --as=system:serviceaccount:monitoring:prometheus

# 2. Проверка ClusterRoleBinding
kubectl get clusterrolebinding | grep monitoring

# 3. Проверка RoleBinding по namespace
kubectl get rolebinding -n monitoring

# 4. Рекомендация:最小化 прав
kubectl auth can-i create pods --as=system:serviceaccount:monitoring:prometheus
# → Должно быть "no" если Prometheus не нуждается в создании подов
```

### Проверка версий и обновлений

```bash
# 1. Текущие версии
kubectl get deployment prometheus-operator -n monitoring -o jsonpath='{.spec.template.spec.containers[0].image}'
kubectl get statefulset prometheus-main -n monitoring -o jsonpath='{.spec.template.spec.containers[0].image}'
kubectl get statefulset alertmanager-main -n monitoring -o jsonpath='{.spec.template.spec.containers[0].image}'

# 2. Доступные обновления (Helm)
helm list -n monitoring
helm repo update
helm search repo prometheus-community/kube-prometheus-stack --versions | head -5
```

### Тестирование восстановления (DR Drill)

```bash
# 1. Бэкап CRD
kubectl get prometheus,alertmanager,prometheusrule,servicemonitor,podmonitor -A -o yaml > dr-backup-$(date +%Y%m%d).yaml

# 2. Бэкап Grafana дашбордов
kubectl get cm -n monitoring -l grafana_dashboard=1 -o yaml > grafana-dashboards-$(date +%Y%m%d).yaml

# 3. Проверка Velero бэкапов
velero backup get | grep monitoring
velero backup describe <backup-name> --details
```

---

## Диагностика и устранение неисправностей

### Проблема: Высокое потребление RAM Prometheus

**Симптом:** Pod OOMKilled, `container_memory_working_set_bytes` приближается к limits.

**Диагностика:**

```bash
# 1. Топ метрик по кардинальности
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/label/__name__/values' | jq 'length'

# 2. Топ серий по job
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=count by (job) ({__name__=~".+"})' | jq '.data.result | sort_by(-.value[1]) | .[0:10]'

# 3. Проверка churn rate
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=prometheus_tsdb_head_series_created_total' | jq '.data.result[0].value[1]'
```

**Решение:**

- Увеличить `resources.limits.memory`.
- Добавить `metricRelabelings` для удаления бесполезных метрик.
- Включить шардирование (`spec.shards`).

### Проблема: Отставание Remote Write

**Симптом:** `prometheus_remote_write_samples_dropped_total` растет.

**Диагностика:**

```bash
# 1. Проверка очереди
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=prometheus_remote_write_queue_samples_pending'

# 2. Проверка ошибок
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=prometheus_remote_write_samples_dropped_total'

# 3. Проверка сети до LTS
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=prometheus_remote_write_sent_samples_total'
```

**Решение:**

- Увеличить `queueConfig.maxShards`.
- Увеличить `queueConfig.capacity`.
- Проверить сеть до LTS (Mimir/VM/Thanos).

### Проблема: Медленный скрейпинг

**Симптом:** `scrape_duration_seconds` > 50% от `scrape_interval`.

**Диагностика:**

```bash
# 1. Топ целей по длительности скрейпинга
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=topk(10, scrape_duration_seconds)' | jq '.data.result[] | {instance: .metric.instance, duration: .value[1]}'

# 2. Проверка сети
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=scrape_duration_seconds{job="prometheus"}'
```

**Решение:**

- Увеличить `scrape_interval` для медленных целей.
- Оптимизировать количество `relabel_configs`.
- Использовать `scrape_class` с оптимальными настройками.

### Частые ошибки на собеседованиях

1. **"prometheus_tsdb_head_series — это количество метрик"** — Нет. Это количество активных временных рядов (time series), каждая из которых — уникальная комбинация имени метрики и лейблов.

2. **"scrape_interval должен быть 15s для всех целей"** — Нет. Для инфраструктурных целей (node-exporter) подходит 30s, для приложений — 15s, для критичных сервисов — 5s.

3. **"config-reloader перезапускает под при изменении конфига"** — Нет. Config-reloader отправляет HTTP-запрос `/-/reload`, который вызывает hot-reload конфигурации без перезапуска пода.

---

## Дополнительная информация

- [Troubleshooting](./operator/troubleshooting.md) — полный алгоритм диагностики.
- [Self-Monitoring](./operator/self_monitoring.md) — мониторинг самого стека.
- [Resource Sizing](./operator/resource_sizing.md) — формулы расчета ресурсов.
- [Cost Optimization](./operator/cost_optimization.md) — оптимизация TCO.
- [Production Checklist](./production_checklist.md) — чеклист готовности к продакшену.
