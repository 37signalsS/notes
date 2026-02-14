# Шаблонизация манифестов в Helm

## Определения

**Шаблонизация в Helm** — это процесс генерации манифестов Kubernetes с использованием **Go template engine**. Helm обрабатывает файлы в директории `templates/`, подставляя в них динамические значения, что позволяет создавать гибкие и переиспользуемые [чарты](./helm_chart_structure.md). Рендеринг выполняется с использованием функций из библиотеки [Sprig](http://masterminds.github.io/sprig/), что позволяет описывать конфигурацию декларативно, но с элементами логики.

Внутри шаблонов доступны встроенные объекты для доступа к данным:

*   `.Values`: Наиболее часто используемый объект. Предоставляет доступ к значениям из файла `values.yaml` и параметрам, переданным через флаги `--set` или `-f`.
*   `.Release`: Содержит метаданные о самом релизе, такие как `.Release.Name` (имя релиза), `.Release.Namespace` (пространство имен) и `.Release.Service` (служебное имя Helm).
*   `.Chart`: Содержит метаданные из файла `Chart.yaml`, например `.Chart.Name` (имя чарта) и `.Chart.Version`.
*   `.Files`: Предоставляет доступ к файлам внутри чарта (не шаблонам). Позволяет, например, вставлять содержимое конфигурационных файлов.
*   `.Capabilities`: Содержит информацию о возможностях целевого кластера Kubernetes (например, `.Capabilities.KubeVersion.Version` или доступные версии API `.Capabilities.APIVersions.Has "batch/v1/CronJob"`).

## Основные концепции

### Синтаксис и значения

Базовый синтаксис для вставки значения — `{{ .Values.ключ }}`.

**Пример `templates/configmap.yaml`:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}
data:
  app.env: {{ .Values.env | default "prod" | quote }}
  {{- range $k, $v := .Values.config }}
  {{ $k }}: {{ $v | quote }}
  {{- end }}
```

**Соответствующий `values.yaml`:**

```yaml
env: staging
config:
  LOG_LEVEL: info
  TIMEOUT: "30s"
```

### Управляющие конструкции и функции

Go-шаблоны поддерживают условные блоки, циклы и функции для работы с данными.

#### Условные блоки `if/else`

Позволяют включать или исключать блоки YAML в зависимости от наличия или значения переменных.

```yaml
{{- if .Values.metrics.enabled }}
ports:
  - name: metrics
    containerPort: 9090
{{- end }}
```

#### Блок `with`

`with` позволяет "погрузиться" в дочерний объект, изменяя текущий контекст (`.`) для сокращения кода.

```yaml
{{- with .Values.resources }}
resources:
  limits:
    cpu: {{ .cpu }}
    memory: {{ .memory }}
{{- end }}
```

#### Итерация по спискам и словарям `range`

Используется для генерации повторяющихся блоков.

```yaml
env:
{{- range $name, $val := .Values.envVars }}
  - name: {{ $name }}
    value: {{ $val | quote }}
{{- end }}
```

#### Ключевые функции

*   `quote`: Заключает значение в двойные кавычки.
*   `toYaml`: Сериализует объект (map, list) в YAML-блок. Незаменима для вставки целых блоков конфигурации (например, `nodeSelector` или `tolerations`).
*   `nindent`: Добавляет отступы к каждой строке сгенерированного блока. Критически важна для соблюдения иерархии в YAML.
*   `default`: Задает значение по умолчанию, если переменная не определена.
*   `required`: Прерывает выполнение с ошибкой, если обязательный параметр отсутствует.
*   `tpl`: Обрабатывает строку как шаблон внутри другого шаблона. Полезно для динамических аннотаций или конфигураций.

#### Управление пробелами

Дефисы `{{-` и `-}}` используются для удаления пробельных символов (включая переносы строк) до или после тега, делая итоговые манифесты чище.

## Практические сценарии

### Переиспользуемые блоки: `_helpers.tpl` и именованные шаблоны

Для соблюдения принципа DRY (Don't Repeat Yourself) используется файл `templates/_helpers.tpl`, где определяются **именованные шаблоны (named templates)**.

*   **`define`**: Ключевое слово для определения именованного шаблона.
*   **`include`**: Функция для вставки именованного шаблона.

**1. Определение шаблонов в `templates/_helpers.tpl`:**

```go
{{/*
Шаблон для генерации имени приложения.
*/}}
{{- define "myapp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Шаблон для генерации полного имени ресурса.
*/}}
{{- define "myapp.fullname" -}}
{{- printf "%s-%s" (include "myapp.name" .) .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
```

**2. Использование шаблонов в `templates/deployment.yaml`:**

```yaml
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    app.kubernetes.io/name: {{ include "myapp.name" . }}
```

### Вставка сложных блоков

Комбинация `if`, `toYaml` и `nindent` позволяет гибко управлять блоками.

```yaml
spec:
  {{- if .Values.affinity }}
  affinity:
    {{- toYaml .Values.affinity | nindent 4 }}
  {{- end }}
  {{- if .Values.tolerations }}
  tolerations:
    {{- toYaml .Values.tolerations | nindent 4 }}
  {{- end }}
```

### Комбинирование функций

Пример ниже демонстрирует совместную работу нескольких функций для повышения надежности чарта.

```go
{{- $image := required "Values.image.repository обязателен" .Values.image.repository -}}
image: "{{ $image }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
envFrom:
{{ toYaml .Values.envFrom | nindent 2 }}
```
В этом примере:
1. `required` прервет установку, если `Values.image.repository` не определен.
2. `default` использует `Chart.AppVersion` как тег образа, если `Values.image.tag` не указан.
3. `toYaml` и `nindent` безопасно вставляют и форматируют целый YAML-блок из `Values.envFrom`.


## Дополнительная информация

### Локальная отладка шаблонов

Команда `helm template` — основной инструмент для отладки, рендерящий чарт локально без отправки в кластер.

```bash
# Рендер чарта в текущей директории
helm template my-release-name .

# Рендер с файлом значений
helm template my-release-name . -f my-values.yaml
```

Для проверки с выводом контекста и заметок используются флаги `--dry-run` и `--debug`.

```bash
helm install demo ./mychart --dry-run --debug -f values.yaml
```

### Сводка встроенных объектов

| Объект | Назначение |
| :--- | :--- |
| `.Values` | Пользовательские параметры чарта |
| `.Chart` | Метаданные из `Chart.yaml` |
| `.Release` | Имя релиза, namespace, сервисные поля |
| `.Capabilities` | Доступные API и версии Kubernetes |
| `.Files` | Чтение встроенных в чарт файлов |

### Создание стартового чарта

Команда `helm create` генерирует шаблонный чарт со стандартной структурой, `_helpers.tpl` и примерами, что является отличной отправной точкой.

```bash
helm create my-new-chart
```
