# Условная логика и управление контекстом

---

## Определения

**Условные конструкции** — управляющие директивы (`if`, `else if`, `else`), позволяющие динамически включать или исключать фрагменты манифестов на основе логических проверок значений из `values.yaml`, метаданных чарта или состояния кластера.

**Управление контекстом (with)** — механизм временного переключения «точки» (`.`) на вложенный объект или словарь. Это упрощает доступ к глубоко вложенным параметрам, делая код лаконичным, но требует явного использования `$` для доступа к глобальной области видимости.

**Область видимости (Scope)** — набор данных, доступных текущему выражению. В Helm область видимости динамически меняется внутри блоков `range` и `with`, создавая изолированные контексты.

**Feature flag** — параметр в `values.yaml`, управляющий включением или отключением функциональности в шаблонах. В отличие от runtime-feature-toggle, feature flag в Helm действует на этапе рендеринга и определяет, будет ли ресурс присутствовать в итоговом манифесте.

**Feature gate (admission gate)** — паттерн, при котором условные проверки выполняются до создания ресурсов, предотвращая деплой в несоответствующие окружения.

---

## Основные концепции

### Понятие истины (Truthiness)

В Helm (на базе Go Templates) условие считается **ложным** (false) только в следующих случаях:
*   Булево `false`.
*   Числовой `0` (включая типы float).
*   Пустая строка `""`.
*   Пустая коллекция (`list`, `dict`, `slice`).
*   Значение `nil` (null).

**Важно:** Строка, состоящая только из пробелов `" "`, считается **истинной**. Для проверки на реальную пустоту (включая пробелы) используйте функцию `empty` или `trimAll`.

**Особенность парсинга YAML-булевых значений:**
YAML интерпретирует строки `"yes"`, `"no"`, `"true"`, `"false"`, `"on"`, `"off"` как булевы типы. Это приводит к неочевидному поведению:
```yaml
# values.yaml
feature:
  enabled: "false"   # → строка, истинна в if
  enabled2: false     # → булево false, ложно в if
```
Для исключения ошибок используйте кавычки или явное приведение типов:
```go
{{- if eq (.Values.feature.enabled | toString) "true" }}
```

### Логические операторы и сравнение

| Оператор | Синтаксис | Описание |
|----------|-----------|----------|
| **and / or** | `{{ if and .a .b }}` | Логические И/ИЛИ. Принимают переменное число аргументов. |
| **not** | `{{ if not .a }}` | Инверсия значения. |
| **eq / ne** | `{{ if eq .a "v" }}` | Равно / Не равно. |
| **lt / le** | `{{ if lt .a 10 }}` | Меньше / Меньше или равно. |
| **gt / ge** | `{{ if gt .a 10 }}` | Больше / Больше или равно. |
| **default** | `{{ .v | default 80 }}` | Возвращает значение по умолчанию, если `.v` ложно. |

**Нюанс `eq` vs `equal`:** Встроенный `eq` требует совпадения типов. Функция Sprig `equal` более гибка при сравнении различных типов данных (например, строки и числа).

**Короткое замыкание (short-circuit):** В `and` и `or` вычисления прекращаются, как только результат становится определенным. Это позволяет безопасно проверять вложенные поля:
```go
{{- if and .Values.parent (hasKey .Values.parent "child") }}
# .Values.parent.child безопасен
{{- end }}
```

### Наследование и приоритет значений (Values Inheritance)

Условная логика часто зависит от иерархии `values.yaml`. Helm применяет **глубокое слияние (deep merge)** для словарей и **полное замещение** для списков. Это важно для conditionals:

| Сценарий | Результат |
|----------|-----------|
| Родитель задает `service.port: 80`, дочерний чарт не переопределяет | Доступен порт `80` |
| Родитель задает список `env: [A]`, дочерний чарт задает `env: [B]` | Итоговый список `[B]` (полная замена) |
| Родитель задает `replicas: 3`, CLI передает `--set replicaCount=5` | Итоговое значение `5` |

Для безопасного слияния списков используйте `concat` в `values.yaml` родителя или обработку в шаблонах.

### Функции валидации данных

Для предотвращения ошибок рендеринга и обеспечения безопасности типов используйте:
*   **`hasKey`**: Проверка наличия ключа в словаре: `{{ if hasKey .Values "key" }}`. Критично для избежания `nil pointer evaluating`.
*   **`kindIs` / `typeIs`**: Проверка типа данных: `{{ if kindIs "slice" .Values.items }}`.
*   **`empty`**: Возвращает `true`, если значение считается пустым по правилам Go или является строкой из пробелов.

**Важно:** `hasKey` проверяет только первый уровень. Для глубокой проверки используйте цепочку `if` или функцию `merge` с `default`.

### Глобальный контекст ($)

Символ `$` всегда ссылается на корневой объект (Global Scope). Это «якорь», позволяющий выйти из локального контекста `with` или `range`.

**Взаимодействие с named templates:**
При вызове `include` контекст передается явно. Если внутри именованного шаблона требуется доступ к `.Release`, убедитесь, что точка передана:
```go
{{- include "mychart.labels" . -}}
# внутри define:
{{- define "mychart.labels" -}}
app: {{ $.Release.Name }}  # $ доступен, так как . передан
{{- end -}}
```

---

## Практические сценарии

### Валидация параметров через fail

Прерывание деплоя, если конфигурация некорректна. Это предотвращает создание полурабочих ресурсов.

```yaml
{{- if and .Values.ingress.enabled (not .Values.ingress.hosts) -}}
  {{- fail "Ingress is enabled, but .Values.ingress.hosts is empty!" -}}
{{- end }}

{{- if and .Values.hpa.enabled (lt (int .Values.hpa.minReplicas) 1) -}}
  {{- fail "minReplicas must be at least 1 when HPA is enabled" -}}
{{- end }}
```

**DevOps/SRE-контекст:** `fail` — единственный способ гарантировать, что чарт не установится с противоречивой конфигурацией. В CI/CD это первая линия обороны перед `helm lint`.

### Сложное управление контекстом (with)

Использование `with` для работы с ресурсами и переменными окружения.

```yaml
spec:
  template:
    spec:
      containers:
        - name: {{ .Chart.Name }}
          {{- with .Values.resources }}
          resources:
            limits:
              cpu: {{ .limits.cpu | quote }}
              memory: {{ .limits.memory | quote }}
            requests:
              cpu: {{ .requests.cpu | quote }}
              memory: {{ .requests.memory | quote }}
          {{- end }}
          env:
            - name: RELEASE_NAME
              value: {{ $.Release.Name }} # Использование $ внутри with
```

### Условное создание sidecar-контейнеров

Добавление контейнера только для определенных сред или при наличии секретов.

```yaml
{{- if .Values.monitoring.sidecar.enabled }}
- name: log-forwarder
  image: {{ .Values.monitoring.sidecar.image | default "registry.example.com/log-sidecar:1.2.0" | quote }}
  {{- if eq $.Values.global.env "prod" }}
  args: ["--output=elasticsearch", "--host={{ .Values.monitoring.sidecar.endpoint }}"]
  {{- else }}
  args: ["--output=stdout", "--verbose"]
  {{- end }}
{{- end }}
```

**Важно:** Образ должен поступать из `values.yaml`. Хардкод внешних реестров нарушает принцип Immutable Release.

### Обработка необязательных NodePort и внешних IP

Логика, зависящая от типа сервиса.

```yaml
spec:
  type: {{ .Values.service.type }}
  {{- if eq .Values.service.type "LoadBalancer" }}
  loadBalancerIP: {{ .Values.service.loadBalancerIP | default "" }}
  {{- end }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: http
      {{- if and (eq .Values.service.type "NodePort") (hasKey .Values.service "nodePort") }}
      nodePort: {{ .Values.service.nodePort }}
      {{- end }}
```

### Компактные условия через ternary

Выбор значения в зависимости от булева флага в одну строку.

```yaml
# Выбор политики обновления
strategy:
  type: {{ .Values.rollingUpdate.enabled | ternary "RollingUpdate" "Recreate" }}
```

### Контроль ресурсов кластера (ResourceQuota enforcement)

Условное создание ResourceQuota на основе флага окружения. SRE используют это для предотвращения «шумных соседей» (noisy neighbor):

```yaml
{{- if .Values.resourceQuota.enabled }}
apiVersion: v1
kind: ResourceQuota
metadata:
  name: {{ include "mychart.fullname" . }}-quota
spec:
  hard:
    requests.cpu: {{ .Values.resourceQuota.cpu | quote }}
    requests.memory: {{ .Values.resourceQuota.memory | quote }}
    pods: {{ .Values.resourceQuota.maxPods | quote }}
  {{- if .Values.resourceQuota.scopeSelector }}
  scopeSelector:
    {{- toYaml .Values.resourceQuota.scopeSelector | nindent 4 }}
  {{- end }}
{{- end }}
```

### Namespace-ограничения и multi-tenancy

Условная логика для изоляции неймспейсов. Sysadmins используют это для безопасного мультитенантного деплоя:

```yaml
{{- if .Values.networkPolicy.enabled }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "mychart.fullname" . }}-default-deny
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  {{- if .Values.networkPolicy.allowNamespace }}
  ingress:
    - from:
      - namespaceSelector:
          matchLabels:
            {{- range $key, $value := .Values.networkPolicy.allowNamespace }}
            {{ $key }}: {{ $value | quote }}
            {{- end }}
  {{- end }}
{{- end }}
```

### RBAC: условные правила

Добавление правил только при включенном флаге:

```yaml
{{- if .Values.rbac.create }}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "mychart.fullname" . }}
---
{{- if .Values.rbac.createRole }}
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ include "mychart.fullname" . }}
rules:
  {{- range .Values.rbac.rules }}
  - apiGroups: [{{ .apiGroups | quote }}]
    resources: [{{ .resources | quote }}]
    verbs: [{{ .verbs | quote }}]
    {{- if .resourceNames }}
    resourceNames: [{{ range .resourceNames }}{{ . | quote }},{{ end }}]
    {{- end }}
  {{- end }}
{{- end }}
```

### Контроль безопасности (Security Context)

Условная настройка securityContext на основе окружения:

```yaml
{{- if .Values.podSecurityContext.enabled }}
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000
  {{- if eq $.Values.global.env "prod" }}
  seccompProfile:
    type: RuntimeDefault
  {{- end }}
{{- end }}
```

### Checksum-аннотации и перезапуск подов

Условная генерация аннотаций для отслеживания изменений ConfigMap:

```yaml
{{- if .Values.configmap.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "mychart.fullname" . }}-config
  annotations:
    checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    {{- if .Values.configmap.reloadOnChange }}
    reloader.stakater.com/auto: "true"
    {{- end }}
data:
  APP_MODE: {{ .Values.config.appMode | quote }}
{{- end }}
```

### Условные хуки (Hooks)

Выполнение миграций только при повышении версии:

```yaml
{{- if and .Values.migrations.enabled .Release.IsUpgrade }}
apiVersion: batch/v1
kind: Job
metadata:
  name: "{{ include "mychart.fullname" . }}-migrate"
  annotations:
    "helm.sh/hook": pre-upgrade
    "helm.sh/hook-delete-policy": hook-succeeded
spec:
  template:
    spec:
      containers:
        - name: migrate
          image: "{{ .Values.migration.image }}:{{ .Values.migration.tag }}"
          command: ["/bin/sh", "-c", "{{ .Values.migration.command }}"]
      restartPolicy: Never
{{- end }}
```

### Валидация через values.schema.json в CI/CD

Интеграция статической валидации в pipeline:

```bash
#!/bin/bash
set -euo pipefail

CHART_DIR="./my-chart"
VALUES_FILE="values.yaml"

# 1. Линтинг и валидация схемы
helm lint "$CHART_DIR" --strict -f "$VALUES_FILE"

# 2. Рендеринг с проверкой YAML
helm template test-release "$CHART_DIR" -f "$VALUES_FILE" | kubeconform --strict

# 3. Юнит-тесты (если установлен helm-unittest)
if command -v helm-unittest &> /dev/null; then
  helm unittest "$CHART_DIR"
fi

echo "All validation checks passed"
```

### Multi-cluster матрица совместимости

Скрипт для проверки условной логики в разных версиях K8s:

```bash
#!/bin/bash
CHART="./my-chart"
VALUES="values.yaml"

for K8S_VERSION in 1.24.0 1.26.0 1.28.0 1.30.0; do
  echo "=== Testing against K8s $K8S_VERSION ==="
  helm template test-release "$CHART" \
    -f "$VALUES" \
    --kube-version "$K8S_VERSION" \
    --api-versions networking.k8s.io/v1/Ingress \
    --api-versions batch/v1/CronJob \
    --api-versions policy/v1/PodDisruptionBudget \
    --dry-run | grep -E "^(kind|apiVersion):" | sort | uniq -c
done
```

---

## Дополнительная информация

### Лучшие практики

1.  **Защита от Deep Nesting:** Если вложенность `if/else` или `with` превышает 3 уровня, выносите фрагмент в именованный шаблон (`define`) в файл `_helpers.tpl`.
2.  **Контроль отступов:** Всегда используйте `{{-` для управляющих конструкций. Для вставки данных используйте `nindent` (например, `{{ . | nindent 2 }}`), чтобы гарантировать правильный отступ в YAML.
3.  **Явное приведение типов:** Используйте функции `int`, `float64`, `toString` при сравнении значений из `values.yaml`, так как Helm может некорректно интерпретировать типы при автоматическом парсинге.
4.  **Проверка на nil:** Перед обращением к глубоким полям (`.Values.a.b.c`) всегда проверяйте существование родителя: `{{ if .Values.a }}{{ if .Values.a.b }}...`. Или используйте `with`.
5.  **Feature flags через values.yaml:** Группируйте feature flags в отдельном блоке (`features:`) с явными комментариями в `values.yaml`. Это упрощает аудит включенных функций.
6.  **Один флаг — одна ответственность:** Избегайте составных условий вида `if .Values.prod && .Values.monitoring && .Values.enabled`. Разделите на отдельные проверки или вынесите в хелпер.
7.  **Атомарность изменений:** Условные блоки должны быть самодостаточными. Не создавайте ресурсы в одном `if` и модифицируйте их в другом — это приводит к недетерминированным состояниям.

### Устранение неисправностей

| Ошибка | Вероятная причина | Решение |
|--------|-------------------|---------|
| `nil pointer evaluating` | Попытка доступа к полю `nil`-объекта | Используйте `if .Values.parent` или `with .Values.parent` перед доступом к дочерним полям. |
| `can't evaluate field... in type string` | Попытка доступа к `.Values` внутри `with` или `range` через точку | Используйте `$.Values` для обращения к глобальному контексту. |
| Условие срабатывает на 0 | Helm трактует `0` как `false` | Используйте явное сравнение: `{{ if ne (int .Values.val) 0 }}` или проверку на `nil`. |
| Неверный отступ после `if` | Пропущен `nindent` или лишние пробелы в шаблоне | Используйте `{{- if ... }}` и `nindent` для вставки контента. |
| `wrong number of args for eq` | Ошибка в синтаксисе сравнения | `eq` принимает 2+ аргумента через пробел: `{{ if eq .a .b }}` (без знаков `==`). |
| `invalid value; expecting map` | Передача списка вместо словаря в `with` или `toYaml` | Проверьте тип данных в `values.yaml`. Используйте `kindIs` для отладки. |
| Условный ресурс не создается | Ложное значение feature flag или опечатка в пути | Проверьте `values.yaml` и используйте `{{- if .Values.feature.enabled | default false }}` с явным дефолтом. |
| `tpl` вызывает панику при пустом значении | В `values.yaml` передана пустая строка вместо шаблона | Добавьте проверку: `{{- if .Values.template }}{{ tpl .Values.template . }}{{- end }}` |

### См. также
- [Синтаксис Helm-шаблонов](../syntax.md) — базовые конструкции, циклы и переменные.
- [Встроенные объекты Helm](../objects.md) — подробное описание `.Values`, `.Release`, `.Chart`, `.Capabilities`.
- [Именованные шаблоны и хелперы](../_helpers.md) — переиспользование кода и инкапсуляция логики.
