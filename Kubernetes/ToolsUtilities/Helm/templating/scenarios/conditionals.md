# Условная логика в Helm

---

## Определения

**Условные конструкции** — директивы `if/else/with/end` для динамического создания ресурсов и добавления полей в зависимости от значений.

---

## Условная логика в Service

Динамическое добавление поля `nodePort`:

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

Функция `and` проверяет два условия:

1. `eq .Values.service.type "NodePort"` — тип сервиса равен `NodePort`
2. `.Values.service.nodePort` — значение `nodePort` не пустое

---

## Условное создание ресурсов

Создание `HorizontalPodAutoscaler` только для Deployment:

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

Логика:

- `autoscaling.enabled == true` — HPA включён
- `kind == Deployment"` — тип ресурса Deployment
- При нарушении условий — пустой вывод, ресурс не создаётся

---

## Условное добавление аннотаций

Добавление аннотаций только при включённом флаге:

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
  ...
```

---

## Дополнительные ссылки

- [Синтаксис шаблонов](../syntax.md) — базовый синтаксис и управляющие конструкции
- [Функции](../functions.md) — ключевые функции
- [helm_templating](../../helm_templating.md) — обзорная страница
