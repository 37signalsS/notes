# Шаблонизация в Helm

Helm использует Go template engine с библиотекой Sprig для генерации манифестов Kubernetes на основе параметров и логики.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Go templates** | Движок шаблонизации, используемый Helm для рендеринга YAML |
| **Встроенные объекты** | Предопределённые переменные: `.Values`, `.Release`, `.Chart`, `.Capabilities`, `.Files`, `.Template` |
| **Именованные шаблоны** | Переиспользуемые блоки, определяемые через `{{ define }}` и вызываемые через `{{ include }}` |
| **Функции Sprig** | Расширенная библиотека функций для работы со строками, коллекциями, математикой, датами |
| **Хелперы** | Вспомогательные шаблоны в файле `_helpers.tpl` |

---

## Основные концепции

### Встроенные объекты

| Объект | Назначение | Примеры доступа |
|--------|------------|-----------------|
| `.Values` | Значения из `values.yaml` и флагов `--set` | `.Values.replicaCount`, `.Values.image.repository` |
| `.Release` | Метаданные релиза | `.Release.Name`, `.Release.Namespace`, `.Release.Revision` |
| `.Chart` | Метаданные чарта из `Chart.yaml` | `.Chart.Name`, `.Chart.Version`, `.Chart.AppVersion` |
| `.Capabilities` | Возможности кластера | `.Capabilities.KubeVersion.Version`, `.Capabilities.APIVersions.Has "batch/v1"` |
| `.Files` | Доступ к файлам чарта | `.Files.Get "config.json"`, `.Files.Glob "configs/*.json"` |
| `.Template` | Информация о текущем шаблоне | `.Template.Name`, `.Template.BasePath` |

### Базовый синтаксис

**Вставка значения:**

```yaml
metadata:
  name: {{ .Values.appName }}
```

**Конвейер функций:**

```yaml
name: {{ .Values.name | default "myapp" | lower | trunc 63 | trimSuffix "-" }}
```

**Управление пробелами (Whitespace Control):**

Дефис `(-)` используется для удаления пробелов и символов новой строки, примыкающих к тегам шаблона. Это позволяет избежать пустых строк в итоговом YAML.
- `{{-` — удаляет пробелы и переносы строк **до** тега (слева).
- `-}}` — удаляет пробелы и переносы строк **после** тега (справа).

```yaml
# ШАБЛОН:
env:
{{- range $k, $v := .Values.env }}
  - name: {{ $k }}
    value: {{ $v | quote }}
{{- end }}

# РЕЗУЛЬТАТ (без пустых строк):
env:
  - name: KEY1
    value: "VALUE1"
  - name: KEY2
    value: "VALUE2"
```

### Управляющие конструкции

**Условные блоки `if/else`:**

```yaml
{{- if .Values.metrics.enabled }}
ports:
  - name: metrics
    containerPort: 9090
{{- else }}
# Метрики отключены
{{- end }}
```

**Блок `with` (изменение контекста):**

```yaml
{{- with .Values.resources }}
resources:
  limits:
    cpu: {{ .limits.cpu }}
    memory: {{ .limits.memory }}
{{- end }}
```

**Итерация `range`:**

```yaml
env:
{{- range $name, $value := .Values.envVars }}
  - name: {{ $name }}
    value: {{ $value | quote }}
{{- end }}

# Итерация по списку
{{- range .Values.volumes }}
- name: {{ .name }}
  mountPath: {{ .mountPath }}
{{- end }}
```

### Ключевые функции

| Функция | Назначение | Пример |
|---------|------------|--------|
| `quote` | Заключение в двойные кавычки | `{{ .Values.name \| quote }}` |
| `default` | Значение по умолчанию | `{{ .Values.tag \| default "latest" }}` |
| `required` | Обязательный параметр | `{{ required "Image required" .Values.image }}` |
| `toYaml` | Сериализация в YAML | `{{ toYaml .Values.nodeSelector }}` |
| `nindent` | Отступ для YAML-блока | `{{ toYaml .Values.tolerations \| nindent 8 }}` |
| `tpl` | Рендер строки как шаблона | `{{ tpl .Values.config . }}` |
| `include` | Вставка именованного шаблона | `{{ include "chart.fullname" . }}` |
| `trunc` | Обрезка строки до указанной длины | `{{ .Release.Name | trunc 10 }}` |
| `trimSuffix`| Удаление суффикса из строки | `{{ "my-release-1" | trimSuffix "-1" }}` |

---

## Практические сценарии

### Создание именованных шаблонов (_helpers.tpl)

**Определение в `templates/_helpers.tpl`:**

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

### Вставка сложных блоков с toYaml и nindent

```yaml
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      {{- if .Values.affinity }}
      affinity:
        {{- toYaml .Values.affinity | nindent 8 }}
      {{- end }}
      {{- if .Values.tolerations }}
      tolerations:
        {{- toYaml .Values.tolerations | nindent 8 }}
      {{- end }}
      {{- if .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml .Values.nodeSelector | nindent 8 }}
      {{- end }}
```

### Комбинирование функций для надёжности

```yaml
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
      - name: {{ .Chart.Name }}
        {{- $image := required "Values.image.repository обязателен" .Values.image.repository }}
        image: "{{ $image }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
        imagePullPolicy: {{ .Values.image.pullPolicy | default "IfNotPresent" }}
        envFrom:
          {{- toYaml .Values.envFrom | nindent 10 }}
        resources:
          {{- toYaml .Values.resources | nindent 10 }}
```

### Работа с ConfigMap и файлами

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
data:
  # Вставка значения из values
  app.conf: |
    {{ .Values.configContent | nindent 4 }}
  
  # Чтение внешнего файла
  config.json: |
    {{ .Files.Get "files/config.json" | nindent 4 }}
```

### Проверка API версий кластера

```yaml
{{- if .Capabilities.APIVersions.Has "networking.k8s.io/v1/Ingress" }}
apiVersion: networking.k8s.io/v1
{{- else if .Capabilities.APIVersions.Has "networking.k8s.io/v1beta1/Ingress" }}
apiVersion: networking.k8s.io/v1beta1
{{- else }}
apiVersion: extensions/v1beta1
{{- end }}
kind: Ingress
```

### Глобальные values и scoped values

```yaml
# Глобальные значения (доступны из зависимостей)
{{- .Values.global.storageClass -}}

# Scoped значения в зависимостях
{{- .Values.postgresql.enabled -}}
```

### Условная логика в `service.yaml`

Шаблоны позволяют создавать гибкие манифесты. Например, можно динамически добавлять поле `nodePort` в сервис, только если тип сервиса `NodePort` и порт задан в `values.yaml`.

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
Здесь функция `and` проверяет два условия:
1. `eq .Values.service.type "NodePort"`: тип сервиса равен `NodePort`.
2. `.Values.service.nodePort`: значение `nodePort` не пустое.

### Условное добавление аннотаций

Блоки `if` позволяют добавлять метаданные, например, аннотации, только при выполнении определённого условия. Это полезно для интеграции с инструментами, которые могут быть не во всех кластерах.

Пример для `stakater/reloader`, который перезагружает Deployment при изменении ConfigMap:

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
Аннотация будет добавлена в манифест только если `.Values.reloader.enabled` установлено в `true`.

### Использование `NOTES.txt` для инструкций

Файл `templates/NOTES.txt` — это специальный шаблон, содержимое которого выводится в консоль после успешного выполнения `helm install` или `helm upgrade`. Его главная задача — предоставить пользователю краткую инструкцию о том, как получить доступ к установленному приложению.

Этот файл может содержать такую же логику, как и обычные шаблоны. Стандартный `NOTES.txt`, генерируемый `helm create`, содержит полезные проверки:

- Если в чарте включен **Ingress**, он выводит команду для получения URL.
- Если Ingress отключен, он проверяет тип **Service**:
    - Для `LoadBalancer` показывает, как получить внешний IP.
    - Для `NodePort` показывает команду для формирования URL с NodePort.
    - Для `ClusterIP` предлагает использовать `kubectl port-forward`.

Это значительно улучшает пользовательский опыт, предоставляя готовые команды для первого доступа к приложению.

---

## Дополнительная информация

- [Обзор Helm](./helm_overview.md) — общие концепции, жизненный цикл релиза
- [Структура Helm-чарта](./helm_chart_structure.md) — расположение шаблонов, _helpers.tpl, values.yaml
- [Управление версиями релизов](./helm_release_versioning.md) — ревизии релизов, откаты

**Полезные ресурсы:**

- Документация Go templates: <https://golang.org/pkg/text/template/>
- Библиотека Sprig: <http://masterminds.github.io/sprig/>
- Локальная отладка: `helm template myrelease .` и `helm install --dry-run --debug myrelease .`
