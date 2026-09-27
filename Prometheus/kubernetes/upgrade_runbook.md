# Runbook: Обновление Prometheus Operator и компонентов в Kubernetes

## Определения

**Upgrade Runbook** — пошаговая процедура обновления стека мониторинга (Prometheus Operator, Prometheus, Alertmanager, Grafana, kube-state-metrics) в Kubernetes. Включает предварительную подготовку, валидацию, поэтапное обновление и откат при ошибке.

**CRD Migration** — процесс обновления Custom Resource Definitions при переходе на новую версию Operator. CRD могут содержать новые поля или измененные схемы, требующие ручного вмешательства.

> **См. также:** [Концепции Operator](./operator/concepts.md), [GitOps Integration](./operator/gitops_integration.md), [Troubleshooting](./operator/troubleshooting.md).

---

## Основные концепции

### Порядок обновления компонентов

**Критически важно:** CRD обновляются ДО Operator, а не одновременно с ним.

```text
1. CRD (monitoring.coreos.com)
2. Prometheus Operator
3. kube-state-metrics
4. Prometheus Server (StatefulSet)
5. Alertmanager (StatefulSet)
6. Grafana (Deployment)
7. PrometheusRule / ServiceMonitor / PodMonitor (при необходимости)
```

### Когда обновлять

- **Безопасно:** Патч-версии (0.85.x → 0.86.x) — обычно обратно совместимы.
- **Осторожно:** Минорные версии (0.85.x → 0.90.x) — могут содержать Breaking Changes.
- **Опасно:** Мажорные версии (0.x → 1.0) — требуют тщательного тестирования.

### Риски обновления

| Риск | Вероятность | Влияние | Митигация |
|:---|:---|:---|:---|
| CRD mismatch (unknown field) | Высокая | Operator не применяет CRD | Обновлять CRD первыми |
| Потеря данных TSDB | Низкая | Потеря метрик за retention | PDB + volumeSnapshot |
| Разрыв алертинга | Средняя | Не отправляются уведомления | Canary update через partition |
| Несовместимость PromQL | Низкая | Падение recording rules | Тестирование в staging |

---

## Практические сценарии

### Сценарий 1: Обновление CRD (ручное)

```bash
# 1. Скачать новые CRD
helm pull prometheus-community/kube-prometheus-stack --version <NEW_VERSION> --untar
cd kube-prometheus-stack/crds/

# 2. Просмотреть изменения
diff <(kubectl get crd prometheuses.monitoring.coreos.com -o yaml) monitoring.coreos.com_prometheuses.yaml

# 3. Применить новые CRD
kubectl apply -f .

# 4. Проверка CRD
kubectl get crd | grep monitoring.coreos.com
kubectl get crd prometheuses.monitoring.coreos.com -o jsonpath='{.spec.versions[*].name}'
```

### Сценарий 2: Обновление Operator через Helm

```bash
# 1. Бэкап текущих значений
helm get values monitoring -n monitoring > backup-values.yaml
kubectl get prometheus,alertmanager,prometheusrule,servicemonitor,podmonitor -A -o yaml > backup-cr.yaml

# 2. Просмотр изменений
helm diff upgrade monitoring prometheus-community/kube-prometheus-stack \
  --version <NEW_VERSION> \
  -f values.yaml \
  -f backup-values.yaml

# 3. Обновление с флагами безопасности
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --version <NEW_VERSION> \
  -f values.yaml \
  --namespace monitoring \
  --atomic \
  --timeout 10m \
  --wait

# 4. Проверка после обновления
kubectl get pods -n monitoring
kubectl rollout status deployment/prometheus-operator -n monitoring --timeout=5m
kubectl logs -n monitoring deploy/prometheus-operator --tail=50 | grep -i error
```

### Сценарий 3: Канареечное обновление Prometheus

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 3
  version: "3.0.0"
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 2  # Обновлять только реплики с ordinal >= 2
```

**Шаги:**

```bash
# 1. Обновить partition до 1 (обновить 2 из 3 реплик)
kubectl patch prometheus main -n monitoring --type merge -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":1}}}}'

# 2. Дождаться готовности
kubectl rollout status statefulset/prometheus-main -n monitoring --timeout=10m

# 3. Проверить метрики
kubectl exec -n monitoring prometheus-main-1 -c prometheus -- wget -qO- 'http://localhost:9090/api/v1/query?query=up' | jq '.data.result[0].value[1]'

# 4. Обновить partition до 0 (обновить все реплики)
kubectl patch prometheus main -n monitoring --type merge -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":0}}}}'

# 5. Финальная проверка
kubectl rollout status statefulset/prometheus-main -n monitoring --timeout=10m
```

### Сценарий 4: Обновление Alertmanager

```bash
# 1. Проверить кворум ДО обновления
kubectl exec -n monitoring alertmanager-main-0 -c alertmanager -- \
  amtool cluster members

# 2. Обновить partition (аналогично Prometheus)
kubectl patch alertmanager main -n monitoring --type merge -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":2}}}}'

# 3. Дождаться готовности
kubectl rollout status statefulset/alertmanager-main -n monitoring --timeout=5m

# 4. Проверить кворум ПОСЛЕ каждого пода
kubectl exec -n monitoring alertmanager-main-0 -c alertmanager -- \
  amtool cluster members

# 5. Обновить partition до 0
kubectl patch alertmanager main -n monitoring --type merge -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":0}}}}'
```

### Сценарий 5: Обновление Grafana

```bash
# 1. Бэкап дашбордов
kubectl get cm -n monitoring -l grafana_dashboard=1 -o yaml > grafana-dashboards-backup.yaml

# 2. Обновление через Helm
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --version <NEW_VERSION> \
  -f values.yaml \
  --set grafana.image.tag=<NEW_GRAFANA_VERSION> \
  --namespace monitoring \
  --atomic

# 3. Проверка доступности
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80
# → http://localhost:3000

# 4. Проверка дашбордов
kubectl get cm -n monitoring -l grafana_dashboard=1 | wc -l
```

---

## Диагностика и устранение неисправностей

### Проблема: CRD mismatch после обновления Operator

**Симптом:** `kubectl apply` возвращает `unknown field`, Operator игнорирует новые поля.

**Решение:**

```bash
# 1. Проверить версию CRD и Operator
kubectl get crd prometheuses.monitoring.coreos.com -o jsonpath='{.spec.versions[*].name}'
kubectl get deployment prometheus-operator -n monitoring -o jsonpath='{.spec.template.spec.containers[0].image}'

# 2. Применить CRD заново
kubectl apply -f <path-to-new-crds>/

# 3. Перезапустить Operator
kubectl rollout restart deployment prometheus-operator -n monitoring
```

### Проблема: Prometheus не обновляется при изменении version

**Симптом:** `spec.version` изменен, но поды не пересоздаются.

**Решение:**

```bash
# 1. Проверить partition
kubectl get prometheus main -n monitoring -o jsonpath='{.spec.updateStrategy}'

# 2. Установить partition: 0
kubectl patch prometheus main -n monitoring --type merge -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":0}}}}'

# 3. Если не помогает — перезапустить StatefulSet
kubectl rollout restart statefulset/prometheus-main -n monitoring
```

### Проблема: Operator не применяет ServiceMonitor после обновления

**Симптом:** Цели отсутствуют в Prometheus, ServiceMonitor в статусе `Accepted`, но `reconcile_errors > 0`.

**Решение:**

```bash
# 1. Проверить логи Operator
kubectl logs -n monitoring deploy/prometheus-operator --tail=100 | grep -i "error\|fail"

# 2. Проверить селекторы
kubectl get prometheus main -n monitoring -o jsonpath='{.spec.serviceMonitorSelector}'
kubectl get servicemonitor -n monitoring --show-labels

# 3. Проверить версию CRD
kubectl get crd servicemonitors.monitoring.coreos.com -o jsonpath='{.spec.versions[*].name}'

# 4. Применить CRD заново и перезапустить Operator
kubectl apply -f <path-to-crds>/servicemonitors.monitoring.coreos.com.yaml
kubectl rollout restart deployment prometheus-operator -n monitoring
```

### Проблема: Алерты не отправляются после обновления Alertmanager

**Симптом:** Alertmanager работает, но уведомления не доходят.

**Решение:**

```bash
# 1. Проверить кворум
kubectl exec -n monitoring alertmanager-main-0 -c alertmanager -- \
  amtool cluster members

# 2. Проверить конфигурацию
kubectl exec -n monitoring alertmanager-main-0 -c alertmanager -- \
  amtool config show | head -50

# 3. Проверить NetworkPolicy
kubectl get networkpolicy -n monitoring -o yaml | grep -A10 "9094"

# 4. Проверить receiver
kubectl exec -n monitoring alertmanager-main-0 -c alertmanager -- \
  amtool receiver verify
```

### Частые ошибки на собеседованиях

1. **"Helm обновляет CRD автоматически"** — Нет. Helm НЕ обновляет CRD при `helm upgrade`. CRD должны обновляться вручную или через отдельный Job.

2. **"При обновлении Operator все CRD пересоздаются"** — Нет. Operator обновляет только те CRD, которые он управляет (StatefulSet, Service, ConfigMap). CRD (ServiceMonitor, PrometheusRule) не пересоздаются.

3. **"Канареечное обновление через partition требует 2 кластера"** — Нет. Partition обновляет только поды с ordinal >= partition. Реплики с ordinal < partition остаются на старой версии.

---

## Дополнительная информация

- [Концепции Operator](./operator/concepts.md) — архитектура и жизненный цикл.
- [GitOps Integration](./operator/gitops_integration.md) — ArgoCD для управления обновлениями.
- [Troubleshooting](./operator/troubleshooting.md) — полный алгоритм диагностики.
- [Self-Monitoring](./operator/self_monitoring.md) — мониторинг самого стека.
- [kube-prometheus-stack — Overview](./Kube_Prometheus_Stack_Helm/overview.md) — архитектура Helm-чарта.
