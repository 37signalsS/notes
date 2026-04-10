# Управление правилами vmalert в Kubernetes

## 1. Определения

**vmalert** — компонент [VictoriaMetrics](./overview.md) для выполнения правил алертинга и recording rules. Существует два основных подхода к управлению правилами:

1. **Через ConfigMap** — классический подход с монтированием файлов правил в под
2. **Через VMRule CRD** — современный подход с использованием VictoriaMetrics Operator (рекомендуется)

## 2. Базовые концепции

### Сравнение подходов

| Подход | Преимущества | Недостатки | Когда использовать |
| :--- | :--- | :--- | :--- |
| **ConfigMap** | Работает без Operator, полный контроль | Требует перезапуска при изменении путей | Legacy, простые инсталляции |
| **VMRule CRD** | Hot reload, декларативность, GitOps | Требует VictoriaMetrics Operator | Production, новые инсталляции |

## 3. Практические сценарии

### Сценарий 1: Управление через VMRule CRD (рекомендуется)

VictoriaMetrics Operator предоставляет кастомный ресурс **VMRule** для декларативного управления правилами.

#### Пример VMRule для алертинга

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMRule
metadata:
  name: cpu-alerts
  namespace: monitoring
spec:
  groups:
    - name: cpu-alerts
      interval: 30s
      rules:
        - alert: HighCpuUsage
          expr: 100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "High CPU usage on {{ $labels.instance }}"
            description: "CPU usage is above 85% for more than 5 minutes. Value: {{ $value }}%"
```

#### Пример VMRule для recording rules

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMRule
metadata:
  name: recording-rules
  namespace: monitoring
spec:
  groups:
    - name: recording-rules
      interval: 1m
      rules:
        - record: cluster:node_cpu:avg_rate5m
          expr: avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))
```

#### Применение и управление

```bash
# Применение правил
kubectl apply -f vmrule-cpu.yaml
kubectl apply -f vmrule-memory.yaml

# Проверка статуса
kubectl get vmrule
kubectl describe vmrule cpu-alerts

# Удаление
kubectl delete vmrule cpu-alerts
```

**Важно:** VMRule автоматически связывается с VMAlert через селекторы меток. В ресурсе VMAlert укажите:

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMAlert
metadata:
  name: vmalert
  namespace: monitoring
spec:
  ruleSelector:
    matchLabels:
      app: monitoring
  ruleNamespaceSelector:
    matchLabels:
      monitoring: enabled
```

#### Преимущества VMRule

- **Hot reload** — изменения применяются без перезапуска vmalert
- **Декларативность** — правила как Kubernetes-ресурсы
- **GitOps** — идеально для ArgoCD/Flux
- **Валидация** — Operator проверяет корректность правил
- **Мультитенантность** — поддержка tenant в enterprise-версии

### Сценарий 2: Управление через ConfigMap (legacy)

> **Примечание:** Этот подход рекомендуется только для инсталляций без VictoriaMetrics Operator.

#### Проблема управления через Helm

При использовании vmalert через Helm-чарт все правила определяются в `values.yaml`, что создаёт трудности при управлении большим количеством правил.

#### Решение: отдельные ConfigMap для каждой группы правил

**Пример: `alert-rules-cpu.yaml`**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: vmalert-rules-cpu
  namespace: monitoring
data:
  alert-rules-cpu.yaml: |
    groups:
      - name: cpu-alerts
        rules:
          - alert: HighCpuUsage
            expr: 100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100) > 85
            for: 5m
            labels:
              severity: warning
            annotations:
              summary: "High CPU usage on node {{ $labels.instance }}"
              description: "CPU usage is above 85% for more than 5 minutes."
```

#### Модификация Deployment vmalert

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vmalert
  namespace: monitoring
spec:
  template:
    spec:
      containers:
        - name: vmalert
          args:
            - -datasource.url=http://victoria-metrics.monitoring.svc:8428/
            - -notifier.url=http://alertmanager.monitoring.svc:9093/
            - -rule=/config/rules/cpu/alert-rules-cpu.yaml
            - -rule=/config/rules/memory/alert-rules-memory.yaml
          volumeMounts:
            - name: alert-config-cpu
              mountPath: /config/rules/cpu/alert-rules-cpu.yaml
              subPath: alert-rules-cpu.yaml
            - name: alert-config-memory
              mountPath: /config/rules/memory/alert-rules-memory.yaml
              subPath: alert-rules-memory.yaml
      volumes:
        - name: alert-config-cpu
          configMap:
            name: vmalert-rules-cpu
        - name: alert-config-memory
          configMap:
            name: vmalert-rules-memory
```

#### Развертывание через ArgoCD

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: vmalert
spec:
  source:
    repoURL: 'https://github.com/my-org/my-k8s-configs.git'
    path: 'monitoring/vmalert'
    targetRevision: main
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: monitoring
```

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Правила не применяются | VMRule не связан с VMAlert | Проверить `ruleSelector` в VMAlert |
| Ошибка валидации | Синтаксическая ошибка в выражении | Проверить логи Operator: `kubectl logs -l app=victoria-metrics-operator` |
| ConfigMap не монтируется | Ошибка в имени или namespace | Проверить `kubectl describe deployment vmalert` |
| Правила не видны в UI | vmalert не перезагружен | Для ConfigMap: перезапустить под, для VMRule: проверить статус |

## 4. Дополнительная информация

Полезные команды: `kubectl get vmrule --all-namespaces` (все VMRule), `kubectl describe vmrule <name> -n <namespace>` (статус), `kubectl logs -l app=vmalert -n monitoring` (логи), `kubectl rollout restart deployment vmalert -n monitoring` (перезапуск для ConfigMap).

Документация: [VMRule CRD](https://docs.victoriametrics.com/operator/resources/vmrule/), [VMAlert](https://docs.victoriametrics.com/vmalert/), [VictoriaMetrics Operator](https://docs.victoriametrics.com/operator/). Связанный файл: [vmalert](./vmalert_overview.md).
