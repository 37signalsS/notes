# Чеклист готовности Prometheus в Kubernetes к Production

## Определения

**Production Readiness Checklist** — структурированный список требований, которые должны быть выполнены перед запуском стека мониторинга Prometheus в Kubernetes в продакшен-среде. Охватывает безопасность, отказоустойчивость, производительность и операционную готовность.

> **См. также:** [High Availability](./operator/high_availability.md), [Security](./operator/Security/index.md), [Cost Optimization](./operator/cost_optimization.md), [Resource Sizing](./operator/resource_sizing.md).

---

## Безопасность

### Кластерный доступ

- [ ] Namespace `monitoring` изолирован от прикладных namespace через NetworkPolicy
- [ ] Egress ограничен: только DNS (53), API Server (6443), objetivo хранилище (443/9000)
- [ ] Ingress ограничен: только Prometheus UI (9090), Alertmanager UI (9093), Grafana (3000)
- [ ] Pod Security Admission: `restricted` для namespace `monitoring`
- [ ] `securityContext.runAsNonRoot: true` для всех подов
- [ ] `readOnlyRootFilesystem: true` где возможно
- [ ] `allowPrivilegeEscalation: false` для всех контейнеров

### RBAC

- [ ] ServiceAccount для Prometheus с минимальными правами (только `get`, `list`, `watch`)
- [ ] ServiceAccount для Operator с правами на CRUD для CRD
- [ ] ServiceAccount для kube-state-metrics с правами только на чтение объектов API
- [ ] ClusterRoleBinding привязан к конкретным namespace через RoleBinding где возможно
- [ ] Ежеквартальный аудит прав через `kubectl auth can-i --list`

### Секреты

- [ ] Basic Auth, OAuth2 токены хранятся в Kubernetes Secrets (не в ConfigMap)
- [ ] Secrets зашифрованы через EncryptionConfiguration или External Secrets Operator
- [ ] `thanos-objstore-config` Secret содержит только credentials, не логику
- [ ] TLS-сертификаты управляются через cert-manager
- [ ] Секреты ротируются автоматически (ESO + Vault или cert-manager)

### Аудит

- [ ] Kubernetes Audit Policy включает операции с `monitoring.coreos.com` ресурсами
- [ ] Audit logs хранятся >= 90 дней
- [ ] Алерты на изменение CRD и секретов в namespace `monitoring`

---

## Отказоустойчивость

### Prometheus

- [ ] `replicas: 2` (минимум) для HA-режима
- [ ] `retention: 15d` (рекомендуется) с SSD-хранилищем
- [ ] `persistentVolumeClaimRetentionPolicy: Retain` для PVC
- [ ] PDB: `minAvailable: 1` для StatefulSet Prometheus
- [ ] `externalLabels` содержат `cluster` и `replica`
- [ ] Remote Write настроен в LTS (Thanos/Mimir/VM) для долгосрочного хранения

### Alertmanager

- [ ] `replicas: 3` (минимум) для кворума Gossip
- [ ] PDB: `minAvailable: 2`
- [ ] NetworkPolicy разрешает порт 9094 (TCP/UDP) между репликами
- [ ] Стандартные receivers: Slack, PagerDuty, Email (минимум 2 канала)
- [ ] Routing rules настроены по severity (critical, warning, info)
- [ ] Inhibition rules настроены (warning подавляется при critical)

### Operator

- [ ] `replicas: 2` для Operator (при > 500 целей)
- [ ] PDB: `minAvailable: 1`
- [ ] Rolling Update Strategy с `maxSurge: 1`, `maxUnavailable: 0`

---

## Производительность

### Sizing

- [ ] CPU/Memory requests/limits рассчитаны по формуле из [Resource Sizing](./operator/resource_sizing.md)
- [ ] Disk: >= 50 GiB для TSDB на 15 дней (SSD)
- [ ] WAL размещается на быстром диске (NVMe SSD)
- [ ] `scrape_interval: 15s` (рекомендуется для большинства целей)
- [ ] `evaluation_interval: 15s` (для recording rules)

### Кардинальность

- [ ] Мониторинг кардинальности: `count(count by (__name__) ({__name__=~".+"}))` < 500k
- [ ] Лимиты в ScrapeConfig: `sampleLimit: 5000`, `seriesLimit: 10000`
- [ ] `metricRelabelings` для удаления бесполезных метрик (go_*, process_*)
- [ ] Alert на взрыв кардинальности: `sum(count by (job) (count by (__name__, job) (prometheus_tsdb_head_series))) > 10000`

### Шардирование

- [ ] При > 1M активных серий: `spec.shards: 3`
- [ ] При > 5M активных серий: `spec.shards: 5+`
- [ ] Шарды не пересекаются по целям (консистентное хэширование)

---

## Алертинг

### Инфраструктурные алерты

- [ ] `PrometheusTargetDown` — цель недоступна > 5 минут
- [ ] `PrometheusHighMemoryUsage` — RAM > 80%
- [ ] `PrometheusTSDBCorruption` — повреждение TSDB
- [ ] `PrometheusRemoteWriteBehind` — отставание Remote Write > 10 минут
- [ ] `AlertmanagerClusterNotHealthy` — кластер Alertmanager не готов
- [ ] `KubePodCrashLooping` — Pod перезапускается
- [ ] `KubeNodeNotReady` — узел не готов
- [ ] `KubeAPIServerLatency` — латентность API > 1s

### Прикладные алерты (базовый набор)

- [ ] `HighErrorRate` — доля ошибок > 5%
- [ ] `HighLatency` — P99 латентность > 1s
- [ ] `HighMemoryUsage` — потребление RAM > 80%
- [ ] `HighCPUUsage` — потребление CPU > 80%

### Recording Rules

- [ ] Базовые recording rules для SLO: `http_request_duration_seconds:histogram_quantile_99`
- [ ] Recording rules для HPA: `http_requests_per_second:rate5m`
- [ ] Recording rules для дашбордов: `cluster:cpu:usage:ratio`

---

## Backup и DR

- [ ] etcd backup: CronJob каждые 6 часов → S3
- [ ] Prometheus TSDB backup: Velero с `includeNamespaces: monitoring`
- [ ] CRD backup: `kubectl get crd -o yaml > backup.yaml` ежедневно
- [ ] Secrets backup: зашифрованные бэкапы в S3
- [ ] Восстановление протестировано (ежеквартально)
- [ ] RPO <= 1 час, RTO <= 15 минут для критичных компонентов

---

## GitOps

- [ ] Все ServiceMonitor/PodMonitor/PrometheusRule хранятся в Git
- [ ] ArgoCD/Flux управляет релизом kube-prometheus-stack
- [ ] CRD обновляются вручную ДО обновления Operator
- [ ] `values.yaml` версионирован и аудируется
- [ ] Изменения проходят Code Review перед применением

---

## Мониторинг мониторинга (Self-Monitoring)

- [ ] kube-state-metrics развернут и собирает метрики объектов K8s
- [ ] Node Exporter развернут на всех узлах
- [ ] Self-scraping Prometheus включен (job `prometheus`)
- [ ] Alert на отсутствие данных: `absent(up{job="prometheus"})`
- [ ] Grafana-дашборд для состояния стека мониторинга

---

## Валидация

### Перед запуском

```bash
# 1. Валидация Helm-чарта
helm lint prometheus-community/kube-prometheus-stack -f values.yaml
helm template monitoring prometheus-community/kube-prometheus-stack -f values.yaml | kubectl apply --dry-run=client -f -

# 2. Проверка CRD
kubectl get crd | grep monitoring.coreos.com

# 3. Проверка подов
kubectl get pods -n monitoring
kubectl top pods -n monitoring

# 4. Проверка целей
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090
# → http://localhost:9090/targets

# 5. Проверка алертов
kubectl port-forward -n monitoring svc/alertmanager-operated 9093:9093
# → http://localhost:9093/#/alerts

# 6. Проверка Grafana
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80
# → http://localhost:3000 (admin / prom-operator)
```

### После запуска

```bash
# 1. Проверка сбора метрик
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=up' | jq '.data.result | length'

# 2. Проверка алертов
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/rules' | jq '.data.groups[].rules[] | select(.state=="firing")'

# 3. Проверка Alertmanager
kubectl exec -n monitoring alertmanager-main-0 -c alertmanager -- \
  amtool cluster members

# 4. Проверка Remote Write
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=prometheus_remote_write_samples_total'
```

---

## Частые ошибки на собеседованиях

1. **"2 реплики Alertmanager — достаточно"** — Нет. Alertmanager использует кворум для Gossip. При 2 репликах потеря одной делает кластер неконсистентным. Минимум — 3 реплики.

2. **"emptyDir подходит для TSDB в продакшене"** — Нет. Данные будут потеряны при перезапуске пода. Используйте PersistentVolumeClaim с `Retain` policy.

3. **"NetworkPolicy не нужна для мониторинга"** — Нет. Мониторинг должен иметь最小ные привилегии. Ограничьте egress только DNS, API Server и LTS.

---

## Дополнительная информация

- [Resource Sizing](./operator/resource_sizing.md) — формулы расчета ресурсов.
- [Cost Optimization](./operator/cost_optimization.md) — оптимизация TCO.
- [Security](./operator/Security/index.md) — полный гайд по безопасности.
- [Troubleshooting](./operator/troubleshooting.md) — диагностика проблем.
