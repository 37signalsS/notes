# Именованные шаблоны и хелперы

---

## Определения

**Именованные шаблоны (Named Templates)** — фрагменты кода Go templates, которые определяются один раз (обычно в файлах `_helpers.tpl`) и могут многократно использоваться в различных частях Helm-чарта. Они обеспечивают соблюдение принципа **DRY** (Don't Repeat Yourself), позволяя централизованно управлять повторяющимися блоками YAML.

**Хелперы (Helpers)** — общепринятое название для файлов (например, `_helpers.tpl`) и содержащихся в них именованных шаблонов, предназначенных для вспомогательных вычислений: генерации имён ресурсов, меток (labels) или стандартных блоков конфигурации.

---

## Основные концепции

### Файлы с префиксом подчеркивания

Файлы, имена которых начинаются с нижнего подчеркивания (например, `_helpers.tpl`, `_templates.tpl`), обрабатываются Helm по особым правилам:
- **Не рендерятся как ресурсы:** Содержимое этих файлов не преобразуется в манифесты Kubernetes и не отправляется в API сервер.
- **Глобальная доступность:** Все определения `define`, объявленные в таких файлах, доступны для вызова из любого другого шаблона внутри текущего чарта и всех его зависимостей (субчартов).
- **Чистота вывода:** Рекомендуется использовать whitespace control (`{{-` и `-}}`) внутри определений, чтобы сами файлы хелперов не добавляли пустые строки в итоговый YAML.
- **Порядок загрузки:** Helm загружает файлы в алфавитном порядке. Файлы с префиксом `_` загружаются первыми, поэтому их определения могут быть переопределены позже загруженными файлами без подчеркивания. В пределах одного чарта последнее загруженное определение побеждает.

### Директивы define, include и template

| Конструкция | Описание | Поддержка пайплайнов |
|-------------|----------|-----------------------|
| `{{ define "name" }}` | Создаёт именованный блок кода с именем `"name"`. | Нет |
| `{{ include "name" . }}` | **Рекомендуемый способ.** Вызывает шаблон и возвращает результат как строку. | **Да** (через `|`) |
| `{{ template "name" . }}` | Стандартная директива Go. Выводит результат рендеринга напрямую в поток. | Нет |

**Почему `include` лучше `template`?**
Директива `template` является встроенной в Go, и её результат нельзя передать в пайплайн (например, в функцию `nindent`). Функция `include` была добавлена в Helm специально для того, чтобы рендерить шаблон в строку, которую затем можно обработать (сместить отступы, закавычить и т.д.).

### Передача контекста (Scope)

Именованные шаблоны не имеют автоматического доступа к данным. При вызове необходимо явно передать контекст (обычно это точка `.`).
- Если вызвать `{{ include "my.tpl" . }}`, внутри шаблона точка будет ссылаться на тот же объект, что и снаружи.
- Если контекст не передан (или передан неверно), обращение к `.Values` или `.Release` внутри шаблона вызовет ошибку `nil pointer evaluating`.
- Для передачи корневого контекста внутрь цикла используется паттерн: `{{- $root := . -}}` перед циклом и `{{ include "my.tpl" $root }}` внутри.

### Ограничения имен ресурсов и меток

Kubernetes накладывает строгие ограничения на имена ресурсов и меток:
- **DNS-1123 label:** строка длиной не более 63 символов, начинающаяся и заканчивающаяся буквой или цифрой, содержащая только строчные буквы, цифры, `-` и `.`.
- **Метки селектора (selector labels)** должны быть **иммутабельны** после создания ресурса. Динамические данные (время деплоя, хэш коммита) не должны попадать в селекторы, иначе при обновлении чарта Deployment потеряет связь с Pod.
- **Генерация имен:** комбинация `namespace-release-chart-name` часто превышает лимит. Для контроля используется `nameOverride` или `fullnameOverride`.

### Конфликты имен в Subcharts

При использовании субчартов все шаблоны всех зависимостей загружаются в единое глобальное пространство имен Helm.
- Если родительский чарт и субчарт определяют шаблон с одинаковым именем (например, `mychart.labels`), победит определение родительского чарта, так как он загружается последним.
- Для избежания конфликтов используйте префикс библиотеки или имени чарта: `common.labels`, `myapp.selectorLabels`.

---

## Практические сценарии

### Стандартный набор меток (Labels)

Разделение на общие метки (для метаданных) и селекторы (для связи ресурсов). **Селекторы должны быть неизменными** после создания ресурса.

```go
{{/* Общие метки для всех ресурсов чарта */}}
{{- define "mychart.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "mychart.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/* Метки селектора (используются в Deployment.spec.selector) */}}
{{- define "mychart.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mychart.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
```

### Генерация уникальных имен ресурсов

Использование логики `fullnameOverride` и `nameOverride` для гибкой настройки имен.

```go
{{- define "mychart.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}
```

### Передача нескольких аргументов через dict

Если шаблону нужны данные из разных областей (например, глобальный объект `.Values` и специфичный элемент из цикла), используется функция `dict`.

**Вызов в шаблоне:**
```yaml
{{- range .Values.services }}
---
apiVersion: v1
kind: Service
metadata:
  labels:
    {{- include "mychart.serviceLabels" (dict "root" $ "service" .) | nindent 4 }}
{{- end }}
```

**Определение в _helpers.tpl:**
```go
{{- define "mychart.serviceLabels" -}}
{{- $root := index . "root" -}}
{{- $service := index . "service" -}}
app.kubernetes.io/instance: {{ $root.Release.Name }}
service-type: {{ $service.type }}
{{- end -}}
```

### Валидация обязательных значений

Использование функций `required` и `fail` для предотвращения запуска чарта с невалидной конфигурацией. В Production-средах отсутствие обязательного значения (например, image.repository) может привести к незаметному падению пода. `required` прерывает рендеринг с понятным сообщением, `fail` позволяет реализовать сложную валидационную логику.

```go
{{- define "mychart.image" -}}
image: {{ required "image.repository должен быть задан" .Values.image.repository | quote }}
imagePullPolicy: {{ .Values.image.pullPolicy | default "IfNotPresent" }}
{{- if .Values.image.tag }}
imageTag: {{ required "image.tag должен быть задан" .Values.image.tag | quote }}
{{- else if .Values.image.digest }}
imageDigest: {{ required "image.digest должен быть задан" .Values.image.digest | quote }}
{{- else }}
{{- fail "Требуется image.tag или image.digest" }}
{{- end }}
{{- end -}}
```

### Паттерн enabled

Условное включение ресурсов через флаг `enabled`. Шаблон возвращает либо полный манифест, либо пустую строку. Родительский шаблон оборачивает вызов в `{{- include "..." . | nindent 2 }}`, что позволяет безопасно игнорировать пустой результат.

```go
{{- define "mychart.ingress" -}}
{{- if .Values.ingress.enabled -}}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "mychart.fullname" . }}
  labels: {{ include "mychart.labels" . | nindent 4 }}
  {{- with .Values.ingress.annotations }}
  annotations: {{ toYaml . | nindent 4 }}
  {{- end }}
spec:
  {{- if .Values.ingress.className }}
  ingressClassName: {{ .Values.ingress.className }}
  {{- end }}
  {{- if .Values.ingress.tls }}
  tls: {{ toYaml .Values.ingress.tls | nindent 4 }}
  {{- end }}
  rules:
    {{- range .Values.ingress.hosts }}
    - host: {{ .host | quote }}
      http:
        paths:
          {{- range .paths }}
          - path: {{ .path }}
            pathType: {{ .pathType }}
            backend:
              service:
                name: {{ include "mychart.fullname" $ }}
                port:
                  number: {{ $.Values.service.port }}
          {{- end }}
    {{- end }}
{{- end }}
{{- end -}}
```

### ServiceAccount

```go
{{- define "mychart.serviceAccount" -}}
{{- if .Values.serviceAccount.create -}}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "mychart.fullname" . }}
  labels: {{ include "mychart.labels" . | nindent 4 }}
  {{- if .Values.serviceAccount.annotations }}
  annotations: {{ toYaml .Values.serviceAccount.annotations | nindent 4 }}
  {{- end }}
automountServiceAccountToken: {{ .Values.serviceAccount.automount | default true }}
{{- end }}
{{- end -}}
```

### RBAC: Role и RoleBinding

```go
{{- define "mychart.role" -}}
{{- if .Values.rbac.create -}}
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ include "mychart.fullname" . }}
  labels: {{ include "mychart.labels" . | nindent 4 }}
rules:
  {{- range .Values.rbac.rules }}
  - apiGroups: {{ toYaml .apiGroups | nindent 4 }}
    resources: {{ toYaml .resources | nindent 4 }}
    verbs: {{ toYaml .verbs | nindent 4 }}
    {{- if .resourceNames }}
    resourceNames: {{ toYaml .resourceNames | nindent 4 }}
    {{- end }}
  {{- end }}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ include "mychart.fullname" . }}
  labels: {{ include "mychart.labels" . | nindent 4 }}
subjects:
  - kind: ServiceAccount
    name: {{ include "mychart.serviceAccountName" . }}
    namespace: {{ .Release.Namespace }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {{ include "mychart.fullname" . }}
{{- end }}
{{- end -}}
```

### Service с портами

```go
{{- define "mychart.service" -}}
{{- if .Values.service.enabled -}}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "mychart.fullname" . }}
  labels: {{ include "mychart.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type | default "ClusterIP" }}
  ports:
    {{- range .Values.service.ports }}
    - port: {{ .port }}
      targetPort: {{ .targetPort | default .port }}
      protocol: {{ .protocol | default "TCP" }}
      name: {{ .name | default (printf "port-%d" .port) }}
      {{- if eq $.Values.service.type "NodePort" }}
      nodePort: {{ .nodePort | default (30000 | add1) }}
      {{- end }}
    {{- end }}
  selector: {{ include "mychart.selectorLabels" . | nindent 4 }}
{{- end }}
{{- end -}}
```

### Secret с TLS-сертификатом

```go
{{- define "mychart.tlsSecret" -}}
{{- if and .Values.tls.enabled .Values.tls.cert .Values.tls.key -}}
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "mychart.fullname" . }}-tls
  labels: {{ include "mychart.labels" . | nindent 4 }}
type: kubernetes.io/tls
data:
  tls.crt: {{ .Values.tls.cert | b64enc | quote }}
  tls.key: {{ .Values.tls.key | b64enc | quote }}
{{- end }}
{{- end -}}
```

### HPA (HorizontalPodAutoscaler)

```go
{{- define "mychart.hpa" -}}
{{- if and .Values.autoscaling.enabled .Values.deployment.enabled -}}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "mychart.fullname" . }}
  labels: {{ include "mychart.labels" . | nindent 4 }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "mychart.fullname" . }}
  minReplicas: {{ .Values.autoscaling.minReplicas | default 1 }}
  maxReplicas: {{ .Values.autoscaling.maxReplicas | default 10 }}
  metrics:
    {{- range .Values.autoscaling.metrics }}
    - type: {{ .type }}
      {{- if eq .type "Resource" }}
      resource:
        name: {{ .resource.name }}
        target:
          type: {{ .resource.target.type }}
          averageUtilization: {{ .resource.target.averageUtilization }}
      {{- else if eq .type "External" }}
      external:
        metric:
          name: {{ .external.metric.name }}
        target:
          type: {{ .external.target.type }}
          value: {{ .external.target.value }}
      {{- end }}
    {{- end }}
{{- end }}
{{- end -}}
```

### Проверка существования ресурсов (lookup)

Функция `lookup` выполняет запрос к API серверу кластера и возвращает существующий объект. В хелперах это позволяет реализовать условную логику: например, не пересоздавать Secret, если он уже существует.

```go
{{- define "mychart.existingSecret" -}}
{{- $secret := lookup "v1" "Secret" .Release.Namespace (include "mychart.fullname" .) -}}
{{- if $secret }}
{{- range $key, $value := $secret.data }}
{{ $key }}: {{ $value }}
{{- end }}
{{- end }}
{{- end -}}
```

**Важно:** `lookup` работает только при установке чарта в кластер (не в режиме `helm template` или `helm lint`). Для совместимости с рендерингом без кластера используйте проверку:

```go
{{- define "mychart.secretData" -}}
{{- if .Values.existingSecret -}}
{{- $secret := lookup "v1" "Secret" .Release.Namespace .Values.existingSecret -}}
data: {{ toYaml $secret.data | default (dict) | nindent 2 }}
{{- else -}}
data:
  {{- range $key, $value := .Values.secret.data }}
  {{ $key }}: {{ $value | b64enc | quote }}
  {{- end }}
{{- end }}
{{- end -}}
```

### Динамическая оценка строк (tpl) в хелперах

Функция `tpl` рендерит строку из `values.yaml` как Helm-шаблон. Это позволяет передавать в чарт динамические фрагменты конфигурации, которые интерпретируются в момент рендеринга.

```yaml
# values.yaml
annotations: |
  prometheus.io/scrape: "{{ .Values.monitoring.enabled }}"
  checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
```

```go
{{- define "mychart.annotations" -}}
{{- if .Values.annotations }}
annotations:
  {{- tpl .Values.annotations . | nindent 2 }}
{{- end }}
{{- end -}}
```

### Слияние карт (merge)

Функция `merge` (Sprig) объединяет несколько карт. В хелперах это используется для построения итогового набора меток или аннотаций из нескольких источников (дефолтные, пользовательские, инъектированные плагинами).

```go
{{- define "mychart.allAnnotations" -}}
{{- $default := dict "app.kubernetes.io/managed-by" .Release.Service -}}
{{- $user := .Values.podAnnotations -}}
{{- $injected := .Values.additionalAnnotations -}}
{{- merge $default $user $injected | toYaml }}
{{- end -}}
```

### Диагностика хелперов

Для отладки именованных шаблонов используйте следующие команды:

```bash
# Рендеринг чарта с выводом итогового YAML (без установки)
helm template myapp ./mychart -f values-prod.yaml

# Рендеринг с отладочной информацией (показывает точки входа, используемые значения)
helm template myapp ./mychart -f values-prod.yaml --debug

# Линтинг шаблонов (проверка синтаксиса без кластера)
helm lint ./mychart -f values-prod.yaml

# Проверка, что хелпер вызывается корректно, через dry-run
helm install myapp ./mychart -f values-prod.yaml --dry-run --namespace default
```

Для глубокой отладки конкретного хелпера выносите его результат во временный тестовый манифест:

```yaml
# templates/_test_helper.yaml (удаляется после отладки)
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "mychart.fullname" . }}-debug
data:
  output: |
{{ include "mychart.someHelper" . | indent 4 }}
```

После `helm template` проверьте вывод и удалите временный файл.

---

## Дополнительная информация

### Взаимодействие с Library Charts

Чарты типа `library` (указывается в `Chart.yaml`) используются исключительно для хранения и предоставления именованных шаблонов. Родительские чарты подключают их как зависимости.
- Шаблоны из библиотечного чарта доступны по их именам.
- Рекомендуется использовать префикс библиотеки в именах (например, `common.deployment`).
- При обновлении библиотечного чарта все потребители автоматически получают новые определения шаблонов после обновления зависимостей (`helm dependency update`).

### Линтинг и валидация

- **helm lint:** проверяет синтаксис шаблонов и типы значений. В контексте хелперов `helm lint` выявляет обращение к несуществующим ключам `.Values` и ошибки типов.
- **helm template:** выполняет полный рендеринг без кластера. Используется для проверки корректности `include` и `nindent` на реальных значениях.
- **Unit-тесты:** для сложной логики в хелперах используйте `unittest` плагин (`helm unittest`). Он позволяет написать тесты на Go, которые проверяют выход хелперов при различных входных данных без установки в кластер.
- **Согласованность имен:** проверяйте, что все вызовы `include` ссылаются на существующие `define`. Отсутствующие шаблоны приводят к ошибке на этапе рендеринга.

### Отладка (Debug)

- **--debug:** флаг `helm template --debug` показывает полный список значений, которые были использованы, и точные ошибки в позиции шаблона (с указанием строки в `_helpers.tpl`).
- **Временные манифесты:** как описано в практических сценариях, создавайте временные ConfigMap/Debug для инспекции результата хелпера.
- **Валидация YAML:** после рендеринга pipe'ьте вывод в `yamllint` для проверки структуры, особенно если хелпер возвращает сложные вложенные блоки.

### Ограничения и производительность

- **Рекурсия:** Helm не поддерживает рекурсивные вызовы `include`. Циклическая зависимость между хелперами приведёт к панике рендерера.
- **Глубина пайплайна:** максимальная глубина вложенности пайплайнов ограничена. При построении сложных конструкций разбивайте их на несколько именованных шаблонов.
- **Размер шаблона:** очень большие хелперы (тысячи строк) замедляют рендеринг. Разбивайте логику на отдельные файлы по доменам: `_labels.tpl`, `_names.tpl`, `_resources.tpl`.
- **Безопасность:** никогда не передавайте в хелперы секреты (пароли, токены) в открытом виде. Используйте `existingSecret` и `lookup` для поиска уже существующих секретов в namespace.

### Лучшие практики

- **Префиксы имен:** Всегда начинайте имя шаблона с имени чарта (`mychart.labels`), так как все шаблоны (включая зависимости) попадают в единое глобальное пространство имен Helm. Дублирование имен приведет к тому, что Helm выберет последнее загруженное определение.
- **nindent вместо indent:** При вставке блоков YAML всегда используйте `include "..." . | nindent 4`. Функция `nindent` автоматически добавляет символ новой строки перед отступом, что предотвращает ошибки структуры YAML.
- **Документирование:** Используйте комментарии Go templates `{{/* ... */}}` перед `define` для описания ожидаемого контекста и возвращаемого формата.
- **Изоляция селекторов:** Никогда не добавляйте динамические метки (вроде даты деплоя или версии) в хелперы селекторов.
- **Единый стиль отступов:** в рамках чарта используйте один уровень отступа для `nindent` (обычно 2 или 4 пробела). Не смешивайте стили в разных хелперах.
- **Валидация на входе:** используйте `required` для критичных значений (image.repository, service.type), чтобы предотвратить установку невалидного чарта.
- **Избегайте side effects:** хелперы должны быть чистыми функциями — они не должны изменять глобальное состояние или зависеть от внешних факторов, кроме переданного контекста.

### Устранение неисправностей

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `nil pointer evaluating...` | Контекст (`.`) не передан в `include` | Добавьте точку: `{{ include "name" . }}` |
| `wrong type for value; expected map...` | Ошибка при использовании `dict` или `index` | Проверьте ключи в `dict` и соответствие типов при извлечении через `index` |
| Пустые строки в YAML | Отсутствие дефисов `{{-` в `define` | Добавьте whitespace control в начало и конец определения |
| Неверный отступ (YAML parse error) | Использование `indent` вместо `nindent` или неверное число пробелов | Перейдите на `nindent` и проверьте уровень вложенности в целевом YAML |
| `invalid template name` | Дублирование имени `define` или попытка вызвать несуществующий шаблон | Убедитесь, что шаблон объявлен и имя не конфликтует с другими определениями |
| `error converting YAML to JSON` | Хелпер возвращает невалидный YAML (лишние отступы, не закрытые кавычки) | Проверьте вывод через `helm template --debug` и pipe в `yamllint` |
| `execution error at <...>: unknown function` | Ошибка в вызове функции внутри `include` (неправильный регистр, опечатка) | Проверьте написание функции (например, `nindent`, а не `niindent`) |
| `rendered manifests contain a resource that already exists` | Конфликт имён при установке в Namespace с существующими ресурсами | Проверьте `fullnameOverride` или используйте уникальный `--name-template` |
| `release name exceeds 53 chars` | Длинное имя из комбинации namespace + chart + name | Используйте `nameOverride` или `fullnameOverride` в `values.yaml` |
| Рендеринг зависает на `include` | Циклическая зависимость в `_helpers.tpl` или очень большая структура `.Values` | Проверьте helpers на рекурсию. Ограничьте глубину `range` и размер `dict` |
| Пустой манифест после `include` | Шаблон возвращает пустую строку из-за невыполненного условия `if` | Проверьте, что условия в `define` совпадают с фактическими значениями в `values.yaml` |
| `helm lint` падает на хелпере | Недоступный объект (например, `.Release` при `helm template`) | Убедитесь, что код хелпера безопасно работает в режиме рендеринга без кластера, или используйте `{{- if .Release.IsInstall }}` для изоляции |

### Рекомендации по порядку устранения

1. **Синтаксис:** `helm lint ./mychart` — выявляет опечатки и несуществующие функции.
2. **Структура:** `helm template myapp ./mychart | yamllint` — выявляет невалидный YAML.
3. **Значения:** `helm template myapp ./mychart --debug` — показывает фактические значения и трассу ошибки.
4. **Кластер:** `helm install myapp ./mychart --dry-run` — проверяет взаимодействие с API (включая `lookup`).

### См. также
- [Обзор шаблонизации Helm](../helm_templating.md) — основы и архитектура.
- [Встроенные объекты Helm](./objects.md) — справочник по `.Values`, `.Release`, `.Chart`.
- [Функции Helm-шаблонов](./functions.md) — подробный список функций Sprig и Helm.
- [Синтаксис Helm-шаблонов](./syntax.md) — основы Go Templates и управляющие конструкции.
