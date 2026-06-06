# Условная логика в Helm

---

## Определения

**Условные конструкции** — директивы `if/else/with/end` для динамического создания ресурсов и добавления полей в зависимости от значений. Синтаксис и базовые примеры — в [Синтаксис Helm-шаблонов](../syntax.md).

---

## Основные концепции

Условная логика применяется в трёх типовых случаях:

1. **Условное добавление полей** — поле добавляется в манифест только при определённых значениях (например, `nodePort` для Service типа `NodePort`).
2. **Условное создание ресурсов** — весь файл шаблона оборачивается в `if`, при ложном условии рендерится пустота, ресурс не создаётся.
3. **Условное добавление аннотаций/меток** — блок `annotations` или `labels` добавляется только при включённом флаге.

Ключевые функции для составных условий:

| Функция | Описание | Пример |
|---------|----------|--------|
| `and` | Логическое И | `and .Values.a .Values.b` |
| `eq` | Равенство | `eq .Values.service.type "NodePort"` |
| `not` | Отрицание | `not .Values.disabled` |

---

## Практические сценарии

### Динамический `nodePort` в Service

Поле `nodePort` добавляется только при типе `NodePort` и заданном значении:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: http
      protocol: TCP
      name: http
    {{- if and (eq .Values.service.type "NodePort") .Values.service.nodePort }}
      nodePort: {{ .Values.service.nodePort }}
    {{- end }}
  selector:
    {{- include "myapp.labels" . | nindent 4 }}
```

Логика: `and` проверяет два условия — тип сервиса равен `NodePort` **и** значение `.Values.service.nodePort` не пустое.

### Условное создание HPA (Horizontal Pod Autoscaler) для Deployment

**values.yaml:**

```yaml
kind: Deployment
autoscaling:
  enabled: false
  minReplicas: 1
  maxReplicas: 5
```

**templates/hpa.yaml:**

```yaml
{{- if and .Values.autoscaling.enabled (eq .Values.kind "Deployment") }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "myapp.fullname" . }}
  minReplicas: {{ .Values.autoscaling.minReplicas }}
  maxReplicas: {{ .Values.autoscaling.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 80
{{- end }}
```

При `autoscaling.enabled == false` или `kind != "Deployment"` файл рендерится в пустоту — HPA не создаётся.

### Условное добавление аннотаций для Reloader

**values.yaml:**

```yaml
reloader:
  enabled: true
```

**deployment.yaml:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
  {{- if .Values.reloader.enabled }}
  annotations:
    reloader.stakater.com/auto: "true"
  {{- end }}
spec:
  # ...
```

Аннотация `reloader.stakater.com/auto` появляется только при `reloader.enabled: true`.

---

## Дополнительная информация

Файл посвящён практическим сценариям условной логики. Базовый синтаксис `if/else`, `with`, `range` — в [Синтаксис Helm-шаблонов](../syntax.md). Другие практические сценарии — в [Обзор сценариев](./overview.md).
