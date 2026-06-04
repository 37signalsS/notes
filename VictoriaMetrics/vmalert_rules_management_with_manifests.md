# Управление правилами vmalert в Kubernetes

## 1. Определения

**vmalert** — компонент [VictoriaMetrics](./overview.md) для выполнения правил алертинга и правил записи (recording rules). В среде Kubernetes существует два основных подхода к управлению конфигурациями правил:

1. **Через ConfigMap** — традиционный метод с монтированием файлов конфигурации в файловую систему пода.
2. **Через VMRule CRD** — современный декларативный подход с использованием VictoriaMetrics Operator (рекомендуемый метод).

## 2. Базовые концепции

### Сравнение методов управления

| Метод | Преимущества | Недостатки | Область применения |
| :--- | :--- | :--- | :--- |
| **ConfigMap** | Работает без оператора, полный контроль над путями | Требует перезапуска или sidecar для обновления | Простые инсталляции, Legacy-системы |
| **VMRule CRD** | Поддержка Hot reload, декларативность, GitOps-ready | Зависимость от VictoriaMetrics Operator | Продуктивные среды, новые проекты |

## 3. Практические сценарии

### Сценарий 1: Управление через VMRule CRD

VictoriaMetrics Operator предоставляет кастомный ресурс (Custom Resource) **VMRule** для декларативного описания правил. Это позволяет управлять алертами так же, как и любыми другими ресурсами Kubernetes.

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

#### Пример VMRule для правил записи (recording rules)

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

#### Применение и мониторинг

```bash
# Применение манифестов
kubectl apply -f vmrule-cpu.yaml
kubectl apply -f vmrule-memory.yaml

# Просмотр списка правил
kubectl get vmrule

# Детальная информация
kubectl describe vmrule cpu-alerts
```

**Связывание ресурсов:** VMRule автоматически обнаруживается компонентом VMAlert с помощью селекторов меток (label selectors). В манифесте VMAlert необходимо настроить `ruleSelector`:

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

#### Преимущества использования CRD

- **Горячая перезагрузка (Hot reload)** — изменения применяются мгновенно без прерывания работы.
- **Интеграция с GitOps** — полная совместимость с ArgoCD и Flux.
- **Валидация** — оператор проверяет синтаксис правил перед применением.
- **Масштабируемость** — упрощенное управление сотнями правил в разных пространствах имен.

### Сценарий 2: Управление через ConfigMap (традиционный подход)

Данный подход рекомендуется только для систем, где установка VictoriaMetrics Operator по каким-либо причинам невозможна.

#### Использование отдельных ConfigMap

Для удобства управления рекомендуется разделять группы правил на отдельные файлы ConfigMap вместо использования одного гигантского манифеста.

**Пример манифеста `alert-rules-cpu.yaml`:**

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

#### Конфигурация Deployment для vmalert

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
      volumes:
        - name: alert-config-cpu
          configMap:
            name: vmalert-rules-cpu
```

### Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Правила не применяются | VMRule не соответствует `ruleSelector` | Проверить метки в VMRule и селектор в VMAlert |
| Ошибка валидации | Синтаксическая ошибка в PromQL | Проверить логи оператора: `kubectl logs -l app=victoria-metrics-operator` |
| ConfigMap не монтируется | Ошибка в имени ресурса или пути | Проверить описание пода: `kubectl describe pod <vmalert-pod>` |
| Изменения не видны в UI | Отсутствие автоматической перезагрузки | Для ConfigMap: выполнить перезапуск пода (rollout restart) |

## 4. Дополнительная информация

**Полезные команды:**

- `kubectl get vmrule --all-namespaces` — список всех правил в кластере.
- `kubectl describe vmrule <name>` — детальный статус ресурса.
- `kubectl rollout restart deployment vmalert` — принудительное обновление конфигурации для ConfigMap.

**Ссылки:**

- [VMRule CRD Documentation](https://docs.victoriametrics.com/operator/resources/vmrule/)
- [VictoriaMetrics Operator Guide](https://docs.victoriametrics.com/operator/)
- [Обзор vmalert](./vmalert_overview.md)
