# Синтаксис Helm-шаблонов

---

## Определения

**Go templates** — движок шаблонизации, используемый Helm для генерации YAML-манифестов на основе параметров и логики. Основан на стандартной библиотеке Go [`text/template`](https://pkg.go.dev/text/template).

**Sprig** — библиотека из более чем 100 функций (строковых, математических, коллекционных), которая интегрирована в Helm и расширяет стандартный синтаксис Go templates.

**Контекст (Scope)** — область видимости данных внутри шаблона. Текущий контекст обозначается точкой (`.`). При входе в циклы или блоки `with` контекст смещается.

**Рендеринг (Rendering)** — процесс трансформации шаблонов из `templates/` и значений из `values.yaml` в итоговые YAML-манифесты Kubernetes, готовые к отправке в API-сервер.

**Многодокументный YAML (Multi-document YAML)** — один файл шаблона может генерировать несколько ресурсов Kubernetes, разделенных через `---`. Helm объединяет все документы в единый поток перед отправкой.

**Именованный шаблон (Named Template)** — фрагмент кода, определенный через `define` в `_helpers.tpl` и вызываемый через `include`. Подробности — в разделе [Именованные шаблоны и хелперы](./_helpers.md).

**Immutable Release** — концепция, при которой шаблоны не содержат хардкода окружных значений (имена, неймспейсы, образы). Все параметры должны приходить из `values.yaml` или встроенных объектов (`.Release`, `.Chart`).

---

## Основные концепции

### Вставка значений и пайплайны

Базовый синтаксис — двойные фигурные скобки `{{ }}`. Результат выражения можно передавать по конвейеру (pipeline) через символ `|`.

```yaml
# Простая вставка
name: {{ .Values.appName }}

# Конвейер функций (выполняются слева направо)
name: {{ .Values.name | default "myapp" | lower | quote }}
```

### Управление пробелами (Whitespace control)

Дефис (`-`) внутри тегов удаляет пробелы и переносы строк вокруг блока. Это критично для сохранения валидности YAML-структуры.

| Синтаксис | Описание |
|-----------|----------|
| `{{ value }}` | Сохраняет все окружающие пробелы и переносы строк |
| `{{- value }}` | Удаляет пробелы и переносы слева |
| `{{ value -}}` | Удаляет пробелы и переносы справа |
| `{{- value -}}` | Удаляет пробелы и переносы с обеих сторон |

### Комментарии

Комментарии в шаблонах полностью вырезаются при рендеринге и не попадают в итоговый манифест Kubernetes.

```go
{{/* Это многострочный 
   комментарий Helm */}}
{{- /* Комментарий с удалением пробелов для чистоты YAML */ -}}
```

### Переменные

Переменные объявляются с префиксом `$` и оператором `:=`. Они сохраняют значение в рамках текущего файла шаблона.

```go
{{- $relName := .Release.Name -}}
release: {{ $relName }}
```

### Глобальный контекст ($)

Подробное описание глобального контекста и разницы между `.Values` и `$.Values` см. в разделе **[Встроенные объекты: Глобальный контекст ($)](./objects.md#глобальный-контекст-\$)**.

### Работа с типами данных

YAML чувствителен к типам. Helm предоставляет функции для явного приведения типов, чтобы избежать ошибок парсинга (например, когда порт 8080 интерпретируется как число, а не строка).

*   `quote`: Оборачивает значение в двойные кавычки.
*   `squote`: Оборачивает в одинарные кавычки.
*   `toString`: Принудительно преобразует в строку.
*   `mustToYaml`: Сериализует объект в YAML (полезно для вставки целых блоков конфигурации).
*   `int` / `int64` / `float64`: Приведение чисел. Важно при сравнениях (например, `0` как false vs `"0"` как строка).
*   `kindIs` / `typeIs`: Проверка типа значения во время рендеринга (полезно для защиты от `nil pointer evaluating`).

### Функция must

Префикс `must` (например, `must .Values.replicas`) вызывает панику (panic) при `nil` или пустом значении. Используется для критичных параметров, где значение по умолчанию недопустимо. Это строгий аналог `required`, который выбрасывает нештатную ошибку вместо стандартного сообщения.

```go
replicas: {{ must .Values.replicas }}
# Эквивалентно:
replicas: {{ required "replicas is required" .Values.replicas }}
```

### Конвейеры с побочными эффектами

Функция `$_ :=` (или просто `:=` внутри пайплайна) используется для вызова функций с побочными эффектами (например, `mergeOverwrite`, `set`, `deepCopy`), которые изменяют переменную, но не возвращают значимого значения для дальнейшей передачи по пайплайну.

```go
{{- $cfg := deepCopy .Values.defaults -}}
{{- $_ := mergeOverwrite $cfg .Values.overrides -}}
data: {{ $cfg | toYaml | nindent 2 }}
```

---

## Управляющие конструкции

### Условные переходы (if / else)

Блок выполняется, если условие возвращает `true`.

**Логика истинности (Truthiness):**
В Helm значение считается **ложным**, если это:
*   Булево `false`
*   Числовой `0`
*   Пустая строка `""`
*   `nil` (null)
*   Пустая коллекция (список или словарь)

```yaml
{{- if .Values.ingress.enabled }}
# Генерация ресурсов Ingress
{{- else if .Values.ingress.legacy }}
# Режим совместимости
{{- else }}
# Ingress отключен
{{- end }}
```

**Важно:** Число `0` считается ложным. Для проверки на нулевое значение используйте `{{ if ne (int .Values.port) 0 }}`.

**Логические операторы:** `and`, `or`, `not`, `eq`, `ne`, `lt`, `le`, `gt`, `ge`.

### Изменение контекста (with)

Блок `with` временно устанавливает контекст (`.`) на указанный объект. Если объект пустой, блок игнорируется.

```yaml
{{- with .Values.resources }}
resources:
  limits:
    cpu: {{ .limits.cpu }} # Доступ напрямую без .Values.resources
{{- end }}
```

### Циклы (range)

Используется для перебора списков и словарей.

```yaml
# Итерация по словарю
env:
{{- range $name, $value := .Values.envVars }}
  - name: {{ $name }}
    value: {{ $value | quote }}
{{- end }}

# Итерация по числам (генерация диапазона)
ports:
{{- range until 5 }}
  - port: {{ add 8000 . }}
{{- end }}
```

**Важно о порядке:** При итерации по словарю (`map`) через `range` порядок ключей **не гарантирован** и может отличаться между запусками. Если порядок критичен (например, для `initContainers`), используйте список (`list`) или предварительно отсортируйте данные в `values.yaml`.

### Оценка строк как шаблонов (tpl)

Функция `tpl` позволяет рендерить строку как Helm-шаблон. Это полезно, когда значения в `values.yaml` сами содержат шаблонизацию.

```yaml
# values.yaml:
# mytext: "Hello {{ .Release.Name }}"

# template.yaml:
data:
  message: {{ tpl .Values.mytext . | quote }}
```

**Ограничения:** `tpl` не поддерживает рекурсию без ограничений. Слишком глубокая или циклическая вложенность приведет к ошибке `template: ...: recursive template parsing aborted`.

### Динамический доступ к данным (index)

Функция `index` используется для извлечения значений из словарей или списков по динамическому ключу или индексу.

```go
# Доступ к ключу, содержащему точки или дефисы
{{ index .Values.data "config.yaml" }}

# Доступ к элементу списка по индексу
{{ index .Values.myList 0 }}
```

### Краткие условия (ternary)

Функция `ternary` работает как тернарный оператор: возвращает первый аргумент, если условие истинно, и второй — если ложно.

```go
{{ .Values.enabled | ternary "on" "off" }}
```

### Прерывание выполнения (fail)

Функция `fail` позволяет остановить рендеринг и вернуть ошибку. Используется для валидации критических параметров.

```go
{{- if not .Values.global.clusterId }}
  {{- fail "clusterId is mandatory in global values!" -}}
{{- end }}
```

### Итерация по `range` с вложенным `with`

При вложении `range` внутрь `with` (или наоборот) контекст смещается дважды. Для доступа к `.Release` внутри вложенного блока используйте `$.Release` (глобальный якорь) или сохраните контекст в переменную:

```go
{{- $release := .Release -}}
{{- with .Values.services }}
{{- range . }}
  name: {{ .name }}-{{ $release.Name }}
{{- end }}
{{- end }}
```

---

## Практические сценарии

### Динамические метки и аннотации

Использование переменных и циклов для формирования стандартных метаданных.

```yaml
{{- $labels := .Values.commonLabels -}}
metadata:
  labels:
    {{- range $k, $v := $labels }}
    {{ $k }}: {{ $v | quote }}
    {{- end }}
    app.kubernetes.io/managed-by: {{ .Release.Service }}
```

### Комбинирование include и пайплайнов

Вызов именованных шаблонов (хелперов) с обработкой результата.

```yaml
metadata:
  name: {{ include "mychart.fullname" . | trunc 63 | trimSuffix "-" }}
```
*Примечание: Используется `include` вместо `template`, так как `include` возвращает строку, которую можно передать дальше в пайплайн.*

### Условные ресурсы (Conditional Resources)

Генерация ресурсов только для определенных окружений. Например, HPA только для production:

```yaml
{{- if and .Values.hpa.enabled (eq .Values.global.env "production") }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "mychart.fullname" . }}
spec:
  minReplicas: {{ .Values.hpa.min | int }}
  maxReplicas: {{ .Values.hpa.max | int }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ .Values.hpa.cpuTarget | int }}
{{- end }}
```

### Динамические тома и PersistentVolumeClaim

Условное создание PVC на основе типа хранилища:

```yaml
volumes:
  {{- if eq .Values.storage.class "custom" }}
  - name: data
    persistentVolumeClaim:
      claimName: {{ include "mychart.fullname" . }}-custom-pvc
  {{- else }}
  - name: data
    emptyDir: {}
  {{- end }}
```

### Аффинность и tolerated nodes

Темплейтинг правил размещения подов на основе тегов узлов:

```yaml
{{- with .Values.affinity }}
affinity:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
```

### Сетевая политика (NetworkPolicy)

Динамический селектор неймспейсов для избирательного разрешения трафика:

```yaml
{{- range .Values.networkPolicy.allowedNamespaces }}
- from:
  - namespaceSelector:
      matchLabels:
        kubernetes.io/metadata.name: {{ . }}
{{- end }}
```

### RBAC: условные правила

Добавление правил только при включенном флаге:

```yaml
{{- if .Values.rbac.create }}
rules:
  {{- range .Values.rbac.rules }}
  - apiGroups: [{{ .apiGroups | quote }}]
    resources: [{{ .resources | quote }}]
    verbs: [{{ .verbs | quote }}]
  {{- end }}
{{- end }}
```

### ConfigMap и Secret из внешних файлов

Использование `.Files.Glob` для массового импорта конфигураций:

```yaml
# templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "mychart.fullname" . }}-config
data:
  {{- range $path, $_ := .Files.Glob "configs/**.yaml" }}
  {{ base $path }}: |-
    {{ $.Files.Get $path | nindent 4 }}
  {{- end }}
```

### Инициализационные контейнеры (initContainers)

Динамическая генерация init-контейнеров для миграций или预热:

```yaml
initContainers:
  {{- range .Values.initContainers }}
  - name: {{ .name }}
    image: "{{ .image }}:{{ .tag | default .Chart.AppVersion }}"
    {{- with .command }}
    command: {{ toJson . | nindent 6 }}
    {{- end }}
  {{- end }}
```

### ReplicaCount и стратегия обновления

Управление количеством реплик и стратегией деплоя:

```yaml
replicas: {{ .Values.replicaCount | int }}
strategy:
  type: {{ .Values.updateStrategy.type | default "RollingUpdate" }}
  rollingUpdate:
    maxUnavailable: {{ .Values.updateStrategy.maxUnavailable | default "25%" | quote }}
    maxSurge: {{ .Values.updateStrategy.maxSurge | default "25%" | quote }}
```

### Node selector, affinity и tolerations в одном блоке

Комплексный пример управления размещением:

```yaml
{{- if or .Values.nodeSelector .Values.affinity .Values.tolerations }}
nodeSelector:
  {{- range $k, $v := .Values.nodeSelector }}
  {{ $k }}: {{ $v | quote }}
  {{- end }}
{{- end }}
{{- with .Values.affinity }}
affinity:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
```

---

## Антипаттерны

### Глубокая вложенность условий

Вложенность `if/else` или `with` более чем на 3 уровня снижает читаемость и увеличивает риск ошибок. Выносите сложную логику в именованные шаблоны (`define`) в файл `_helpers.tpl`.

**Плохо:**
```yaml
{{- if .Values.a }}
  {{- if .Values.b }}
    {{- if .Values.c }}
      # ...
    {{- end }}
  {{- end }}
{{- end }}
```

**Хорошо:**
```go
{{- define "mychart.checks" -}}
{{- if and .Values.a .Values.b .Values.c -}}
# ...
{{- end -}}
{{- end -}}
```

### Использование `template` вместо `include`

Директива `template` не возвращает строку и не может использоваться в пайплайнах. Используйте `include` для всех случаев, где результат нужен внутри `|` или в качестве аргумента функции.

```yaml
# Плохо
name: {{ template "mychart.fullname" . | trunc 63 }}

# Хорошо
name: {{ include "mychart.fullname" . | trunc 63 }}
```

### Хардкод окружных значений

Строки вида `namespace: production` или `image: nginx:1.25` в шаблонах делают чарт непеереносимым. Все окружно-зависимые значения должны поступать через `values.yaml`.

### Отсутствие кавычек у внешних строк

Значения из `values.yaml`, особенно введенные пользователем, могут содержать пробелы или символы, ломающие YAML-структуру. Используйте `| quote` для всех строковых полей:

```yaml
# Плохо
name: {{ .Values.name }}

# Хорошо
name: {{ .Values.name | quote }}
```

### Прямой доступ без проверки nil

Обращение к `.Values.a.b.c` без проверки существования родителя вызывает панику рендеринга. Используйте `if` или `with`:

```yaml
# Плохо
cpuset: {{ .Values.resources.limits.cpuset }}

# Хорошо
{{- with .Values.resources.limits }}
cpuset: {{ .cpuset }}
{{- end }}
```

### Ожидание сортировки в `range` по словарю

Go не гарантирует порядок ключей в map. Если порядок элементов важен (например, для `initContainers` или списка правил), используйте список (`list`) в `values.yaml`.

### Использование `indent` вместо `nindent`

Функция `indent` не добавляет перенос строки перед отступом, что часто приводит к слиянию строк и битому YAML. Всегда предпочитайте `nindent`.

---

## Дополнительная информация

### Лучшие практики

*   **Используйте nindent**: Вместо `indent` всегда предпочитайте `nindent <число>`, так как она автоматически добавляет новую строку, что упрощает управление пробелами.
*   **Всегда кавычьте строки**: Используйте `| quote` для всех строковых значений, приходящих извне, чтобы избежать проблем с именами вроде `true` или `12345`.
*   **Проверка вложенности**: Если вы обращаетесь к `.Values.a.b.c`, сначала проверьте `if .Values.a`, чтобы избежать ошибки `nil pointer evaluating`.
*   **Используйте `must` для критичных параметров**: Для необъявляемых через `required` критических данных используйте `must`, чтобы получить детализированную ошибку.
*   **deepCopy перед merge**: Функции `merge` и `mergeOverwrite` мутируют первый аргумент. Всегда копируйте `.Values` перед слиянием.
*   **Объединяйте логику в `_helpers.tpl`**: Если фрагмент шаблона используется более двух раз или сложен для чтения — выносите его в именованный шаблон.

### Устранение неисправностей

| Ошибка | Вероятная причина | Решение |
|--------|-------------------|---------|
| `nil pointer evaluating...` | Обращение к полю объекта, который равен `nil` | Проверьте существование родительского объекта через `if` или `with` |
| `can't evaluate field... in type string` | Попытка доступа к глобальным данным (`.Values`) внутри `range` | Используйте `$.Values` для обращения к корню |
| `wrong number of args` | Ошибка в синтаксисе функции или пайплайна | Проверьте количество аргументов (например, `eq $a $b`, а не `eq $a == $b`) |
| Нарушение отступов YAML | Лишние пробелы в шаблоне | Используйте `{{-` и `nindent` для контроля отступов |
| `template: ...: unexpected "}" in command` | Незакрытая скобка или кавычка в выражении | Проверьте баланс `{{ }}` и кавычек внутри пайплайна |
| `invalid value; expecting map` | Передача списка вместо словаря (или наоборот) в `toYaml` или `with` | Проверьте тип данных в `values.yaml` |
| `executing ... at <.Values...>: invalid value` | Некорректный тип значения (строка вместо числа) | Используйте `int`, `float64` или исправьте `values.yaml` |
| `template parsing aborted: recursive` | Циклическая зависимость через `tpl` или `include` | Уберите рекурсию или упростить цепочку вызовов |
| `range over map: недетерминированный порядок` | Итерация по словарю, где важен порядок | Замените `map` на `list` в `values.yaml` или сортируйте данные до рендеринга |
| `lookup` возвращает пустоту в dry-run | Ограничение режима `helm template` / `--dry-run` | Добавьте fallback: `{{- if $secret }}...{{- else }}default{{- end }}` |
| Значение `0` игнорируется в `if` | Логика истинности Helm (0 = false) | Используйте `{{ if ne (int .Values.val) 0 }}` или проверку на nil |
| Ошибка при рендеринге multi-doc YAML | Отсутствие `---` между документами или лишние пробелы | Убедитесь, что каждый ресурс начинается с `---` и имеет корректные отступы |
| `values.schema.json` validation failed | Несоответствие типа или отсутствие обязательного поля | Проверьте схему и значения в `values.yaml` |

### См. также

* [Обзор шаблонизации Helm](../helm_templating.md) — основы и архитектура.
* [Функции Helm-шаблонов](./functions.md) — подробный список функций Sprig и Go.
