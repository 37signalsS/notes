# Именованные шаблоны и хелперы

---

## Определения

**Именованные шаблоны** — переиспользуемые блоки кода, определяемые через `{{ define }}` и вызываемые через `{{ include }}`.

**Хелперы** — именованные шаблоны в файле `templates/_helpers.tpl` для генерации имён, меток и других повторяющихся конструкций.

---

## Основные концепции

### Почему файл начинается с подчёркивания

Helm не рендерит файлы с префиксом `_` как Kubernetes-манифесты. Файл `_helpers.tpl` обрабатывается только как источник именованных шаблонов, но не создаёт ресурсов при `helm install`.

### Передача области видимости (scope)

При вызове `{{ include "template" . }}` передаётся текущий контекст через точку (`.`):

| Объект контекста | Описание |
|------------------|----------|
| `.Chart` | Метаданные чарта (Name, Version, AppVersion) |
| `.Release` | Информация о релизе (Name, Namespace, Service, IsUpgrade, IsInstall) |
| `.Values` | Значения из `values.yaml` и `--set` |
| `.Capabilities` | Возможности кластера (KubeVersion, APIVersions) |

### Именование хелперов

Стандартная конвенция: `<chart-name>.<purpose>`. Например, для чарта `myapp`:

- `myapp.name` — краткое имя приложения
- `myapp.fullname` — полное имя с учётом release
- `myapp.chart` — имя и версия чарта
- `myapp.labels` — стандартные метки
- `myapp.selectorLabels` — метки для selector (неизменяемые)
- `myapp.commonLabels` — общие метки для всех ресурсов

### `include` vs `template` vs `tpl`

| Функция | Синтаксис | Передача scope | Контекст |
|---------|-----------|----------------|----------|
| `include` | `{{ include "name" . }}` | Явная через второй аргумент | Возвращает строку (можно пайпить в `nindent`, `quote`) |
| `template` | `{{ template "name" . }}` | Аналогично | Выводит напрямую (нельзя пайпить) |
| `tpl` | `{{ tpl "string" . }}` | Явная | Рендерит строку как шаблон (динамические шаблоны из values) |

**Рекомендация:** использовать `include` в большинстве случаев, `tpl` — только для динамических шаблонов из `values.yaml`.

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

{{/*
Создаёт имя чарта с версией.
*/}}
{{- define "myapp.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Метки для spec.selector (неизменяемые после создания Deployment).
*/}}
{{- define "myapp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "myapp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
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

## Дополнительная информация

### Best practices

- **Не меняйте `selectorLabels`** после создания Deployment — Kubernetes не позволяет изменять `spec.selector.matchLabels`.
- **Используйте `include` вместо `template`** — `include` возвращает строку, которую можно пайпить в `nindent`, `quote`, `b64enc`.
- **Ограничивайте длину имён** через `trunc 63 | trimSuffix "-"` — Kubernetes лимит на имена ресурсов = 63 символа.
- **Выносите общие метки** в отдельный хелпер (`commonLabels`) для единообразия across всех ресурсов.
- **Избегайте хардкода** — используйте `.Chart.Name`, `.Release.Name` вместо жёстких значений.

### Troubleshooting

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `wrong type for value` | Передан неверный scope в `include` | Проверяйте, что второй аргумент — `.` или `$` |
| `nil pointer evaluating` | Отсутствует значение в `values.yaml` | Добавьте default через `{{- default "value" .Values.key -}}` |
| Имя ресурса > 63 символа | Нет `trunc` в хелпере | Добавьте `| trunc 63 | trimSuffix "-"` |
| Файл `_helpers.tpl` рендерится как манифест | Файл не начинается с `_` | Переименуйте в `_helpers.tpl` |

[Функции](./functions.md) · [Сценарии: NetworkPolicy](./scenarios/networkpolicy.md) · [Обзор шаблонизации](../helm_templating.md)
