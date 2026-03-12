# Именованные шаблоны и хелперы

---

## Определения

**Именованные шаблоны** — переиспользуемые блоки кода, определяемые через `{{ define }}` и вызываемые через `{{ include }}`.

**Хелперы** — именованные шаблоны в файле `templates/_helpers.tpl` для генерации имён, меток и других повторяющихся конструкций.

---

## Создание именованных шаблонов

Определяются в файле `templates/_helpers.tpl`:

```go
{{/*
Создаёт полное имя ресурса с учётом переопределения и ограничения длины.
*/}}
{{- define "myapp.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "%s-%s" $name .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/*
Создаёт имя приложения.
*/}}
{{- define "myapp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Генерирует метки Kubernetes.
*/}}
{{- define "myapp.labels" -}}
app.kubernetes.io/name: {{ include "myapp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
```

**Использование в шаблонах:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}
```

---

## Организация меток для компонентов

При усложнении чарта с несколькими компонентами (основной app и вспомогательный mail-relay), определяем отдельные шаблоны:

**В `templates/_helpers.tpl`:**

```go
{{/*
Определение стандартных меток для mail-relay
*/}}
{{- define "myapp.mail-relay.labels" -}}
app.kubernetes.io/name: {{ include "myapp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: mail-relay
{{- end -}}

{{/*
Определение меток селектора для mail-relay.
Эти метки используются в `spec.selector` и должны быть неизменными.
*/}}
{{- define "myapp.mail-relay.selectorLabels" -}}
app.kubernetes.io/name: {{ include "myapp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: mail-relay
{{- end -}}
```

**Использование в `templates/mail-relay-deployment.yaml`:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}-mail-relay
  labels:
    {{- include "myapp.mail-relay.labels" . | nindent 4 }}
spec:
  selector:
    matchLabels:
      {{- include "myapp.mail-relay.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "myapp.mail-relay.selectorLabels" . | nindent 8 }}
```

---

## Шаблонизация NetworkPolicy

Использование именованных шаблонов для меток в сетевых политиках:

**templates/mail-relay-netpol.yaml:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "myapp.fullname" . }}-mail-relay
spec:
  # Применяем политику к подам mail-relay
  podSelector:
    matchLabels:
      {{- include "myapp.mail-relay.selectorLabels" . | nindent 6 }}
  policyTypes:
    - Ingress
  ingress:
    # Разрешаем трафик от подов основного приложения
    - from:
      - podSelector:
          matchLabels:
            {{- include "myapp.labels" . | nindent 12 }}
      ports:
        - protocol: TCP
          port: 25
```

---

## Дополнительные ссылки

- [Функции](./functions.md) — ключевые функции для работы с шаблонами
- [Сценарии: NetworkPolicy](./scenarios/networkpolicy.md) — подробнее о сетевых политиках
- [helm_templating](../Helm/helm_templating.md) — обзорная страница
