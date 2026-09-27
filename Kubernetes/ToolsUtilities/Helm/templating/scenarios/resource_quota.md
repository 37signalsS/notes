# Шаблонизация ResourceQuota и LimitRange в Helm

---

## Определения

**ResourceQuota** — ресурс уровня Namespace, ограничивающий суммарное потребление ресурсов (CPU, RAM, количество объектов) всеми подами в namespace.

**LimitRange** — ресурс уровня Namespace, устанавливающий минимальные и максимальные значения requests/limits для контейнеров, а также дефолтные значения, если разработчик не указал их явно.

**Requests** — гарантированные ресурсы, которые под получает при планировании. Используются scheduler'ом для выбора узла.

**Limits** — максимальные ресурсы, которые под может потребить. При превышении Memory — OOMKill; при CPU — throttling.

**QoS (Quality of Service)** — классы подов по соотношению requests/limits: `Guaranteed` (requests == limits), `Burstable` (requests < limits), `BestEffort` (без requests/limits).

---

## Базовые концепции

### ResourceQuota — что ограничивает

| Ресурс | Пример | Описание |
|--------|--------|----------|
| `requests.cpu` | "10" | Суммарные CPU requests |
| `limits.cpu` | "20" | Суммарные CPU limits |
| `requests.memory` | "40Gi" | Суммарные Memory requests |
| `limits.memory` | "80Gi" | Суммарные Memory limits |
| `pods` | "50" | Максимум подов |
| `services` | "10" | Максимум сервисов |
| `configmaps` | "20" | Максимум ConfigMap |
| `secrets` | "20" | Максимум Secret |
| `persistentvolumeclaims` | "10" | Максимум PVC |

### LimitRange — что задаёт

| Поле | Описание |
|------|----------|
| `min.requested.cpu` | Минимальный CPU request |
| `max.limits.cpu` | Максимальный CPU limit |
| `default.requested.cpu` | Дефолтный CPU request |
| `default.limits.cpu` | Дефолтный CPU limit |
| `maxRequestLimitRatio.cpu` | Отношение limit/request |

### Взаимодействие с HPA

- ResourceQuota блокирует scale-up, если квота исчерпана
- LimitRange ограничивает максимум requests для контейнеров
- При масштабировании: `ResourceQuota >= maxReplicas × requests.cpu`

---

## Практические сценарии

### Базовый ResourceQuota

```yaml
# values.yaml
resourceQuota:
  enabled: true
  hard:
    requests.cpu: "10"
    limits.cpu: "20"
    requests.memory: "40Gi"
    limits.memory: "80Gi"
    pods: "50"
    services: "10"
    persistentvolumeclaims: "10"
```

```yaml
# templates/resourcequota.yaml
{{- if .Values.resourceQuota.enabled }}
apiVersion: v1
kind: ResourceQuota
metadata:
  name: {{ include "myapp.fullname" . }}-quota
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  hard:
    requests.cpu: {{ .Values.resourceQuota.hard.requests.cpu | quote }}
    limits.cpu: {{ .Values.resourceQuota.hard.limits.cpu | quote }}
    requests.memory: {{ .Values.resourceQuota.hard.requests.memory | quote }}
    limits.memory: {{ .Values.resourceQuota.hard.limits.memory | quote }}
    pods: {{ .Values.resourceQuota.hard.pods | quote }}
    services: {{ .Values.resourceQuota.hard.services | quote }}
    persistentvolumeclaims: {{ .Values.resourceQuota.hard.persistentvolumeclaims | quote }}
{{- end }}
```

### LimitRange для дефолтных значений

```yaml
# values.yaml
limitRange:
  enabled: true
  default:
    cpu:
      request: "100m"
      limit: "500m"
    memory:
      request: "128Mi"
      limit: "512Mi"
  min:
    cpu: "50m"
    memory: "64Mi"
  max:
    cpu: "4"
    memory: "8Gi"
  maxRequestLimitRatio:
    cpu: "10"
    memory: "4"
```

```yaml
# templates/limitrange.yaml
{{- if .Values.limitRange.enabled }}
apiVersion: v1
kind: LimitRange
metadata:
  name: {{ include "myapp.fullname" . }}-limits
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  limits:
    - type: Container
      default:
        cpu: {{ .Values.limitRange.default.cpu.limit | quote }}
        memory: {{ .Values.limitRange.default.memory.limit | quote }}
      defaultRequest:
        cpu: {{ .Values.limitRange.default.cpu.request | quote }}
        memory: {{ .Values.limitRange.default.memory.request | quote }}
      min:
        cpu: {{ .Values.limitRange.min.cpu | quote }}
        memory: {{ .Values.limitRange.min.memory | quote }}
      max:
        cpu: {{ .Values.limitRange.max.cpu | quote }}
        memory: {{ .Values.limitRange.max.memory | quote }}
      maxLimitRequestRatio:
        cpu: {{ .Values.limitRange.maxRequestLimitRatio.cpu | quote }}
        memory: {{ .Values.limitRange.maxRequestLimitRatio.memory | quote }}
{{- end }}
```

### ResourceQuota с scopeSelector

```yaml
# values.yaml
resourceQuota:
  enabled: true
  hard:
    pods: "100"
  scopeSelector:
    matchExpressions:
      - scopeName: PriorityClass
        operator: In
        values:
          - high
          - medium
```

```yaml
# templates/resourcequota.yaml
{{- if .Values.resourceQuota.enabled }}
apiVersion: v1
kind: ResourceQuota
metadata:
  name: {{ include "myapp.fullname" . }}-quota
spec:
  hard:
    pods: {{ .Values.resourceQuota.hard.pods | quote }}
  {{- if .Values.resourceQuota.scopeSelector }}
  scopeSelector:
    {{- toYaml .Values.resourceQuota.scopeSelector | nindent 4 }}
  {{- end }}
{{- end }}
```

### ResourceQuota для compute и object count

```yaml
# values.yaml
resourceQuota:
  enabled: true
  compute:
    requests.cpu: "20"
    limits.cpu: "40"
    requests.memory: "80Gi"
    limits.memory: "160Gi"
  objectCount:
    pods: "100"
    services: "20"
    configmaps: "50"
    secrets: "50"
    persistentvolumeclaims: "20"
    services.loadbalancers: "5"
    services.nodeports: "10"
```

```yaml
# templates/resourcequota.yaml
{{- if .Values.resourceQuota.enabled }}
apiVersion: v1
kind: ResourceQuota
metadata:
  name: {{ include "myapp.fullname" . }}-quota
spec:
  hard:
    {{- range $key, $value := .Values.resourceQuota.compute }}
    {{ $key }}: {{ $value | quote }}
    {{- end }}
    {{- range $key, $value := .Values.resourceQuota.objectCount }}
    {{ $key }}: {{ $value | quote }}
    {{- end }}
{{- end }}
```

### Валидация через values.schema.json

```json
{
  "properties": {
    "resourceQuota": {
      "type": "object",
      "properties": {
        "enabled": { "type": "boolean" },
        "hard": {
          "type": "object",
          "properties": {
            "requests.cpu": { "type": "string", "pattern": "^[0-9]+m?$" },
            "limits.cpu": { "type": "string", "pattern": "^[0-9]+m?$" },
            "requests.memory": { "type": "string", "pattern": "^[0-9]+(Gi|Mi|Ki)$" },
            "limits.memory": { "type": "string", "pattern": "^[0-9]+(Gi|Mi|Ki)$" },
            "pods": { "type": "string", "pattern": "^[0-9]+$" }
          }
        }
      }
    },
    "limitRange": {
      "type": "object",
      "properties": {
        "enabled": { "type": "boolean" },
        "default": {
          "type": "object",
          "properties": {
            "cpu": {
              "type": "object",
              "properties": {
                "request": { "type": "string" },
                "limit": { "type": "string" }
              }
            }
          }
        }
      }
    }
  }
}
```

---

## Дополнительная информация

### Лучшие практики

1. **Всегда создавайте:** ResourceQuota и LimitRange для каждого production namespace.
2. **С учётом HPA:** `ResourceQuota.requests.cpu >= maxReplicas × requests.cpu × 1.2`.
3. **BestEffort запрещён:** LimitRange с `default` не позволяет BestEffort-поды.
4. **Мониторинг:** Алерты на `ResourceQuotaAlmostExhausted` (kube-state-metrics).
5. **Тестирование:** Проверяйте, что `helm upgrade` не блокируется ResourceQuota.

### Устранение неисправностей

| Ошибка | Вероятная причина | Решение |
|--------|-------------------|---------|
| `exceeded quota` | ResourceQuota исчерпана | Увеличьте квоту или оптимизируйте requests |
| `Forbidden: exceeds limit` | LimitRange.max превышен | Уменьшите requests/limits в Deployment |
| Pod в Pending без квоты | LimitRange.min превышает capacity | Проверьте `kubectl describe quota` |

### См. также

- [QoS, Limit и Requests](../../../../Scheduling/qos_limit_and_requests.md) — теория ресурсов.
- [ResourceQuota](../../../../Base/namespace.md) — управление namespace.
- [HPA: продвинутые теми](../../../../Autoscaling/HPA/hpa_advanced.md) — взаимодействие с ResourceQuota.
