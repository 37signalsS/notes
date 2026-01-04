# Шаблонизация манифестов в Helm

## Определения

**Шаблонизация в Helm** — это процесс генерации манифестов Kubernetes с использованием **Go template engine**. Helm обрабатывает файлы в директории `templates/`, подставляя в них динамические значения, что позволяет создавать гибкие и переиспользуемые [чарты](./helm_chart_structure.md).

Внутри шаблонов доступны встроенные объекты для доступа к данным:

*   `.Values`: Наиболее часто используемый объект. Предоставляет доступ к значениям из файла `values.yaml` и параметрам, переданным через флаг `--set` или `-f`.
*   `.Release`: Содержит метаданные о самом релизе, такие как `.Release.Name` (имя релиза), `.Release.Namespace` (пространство имен) и `.Release.Service` (служебное имя Helm).
*   `.Chart`: Содержит метаданные из файла `Chart.yaml`, например `.Chart.Name` (имя чарта) и `.Chart.Version`.

## Базовые концепции

### Синтаксис и значения

Базовый синтаксис для вставки значения — `{{ .Values.ключ }}`.

**Пример `templates/deployment.yaml`:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-deployment
spec:
  replicas: {{ .Values.replicaCount }}
  template:
    spec:
      containers:
      - name: {{ .Chart.Name }}
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
```

**Соответствующий `values.yaml`:**
```yaml
replicaCount: 2
image:
  repository: nginx
  tag: stable
```

В этом примере Helm заменит `{{ .Values.replicaCount }}` на `2`, а `{{ .Release.Name }}` — на имя, указанное при установке чарта.

### Управляющие конструкции и функции

Go-шаблоны поддерживают условные блоки, циклы и функции для работы с данными.

#### Условные блоки `if/else`
Позволяют включать или исключать блоки YAML в зависимости от наличия или значения переменных.

```yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
# ...
{{- end }}
```
Этот блок будет сгенерирован, только если `.Values.ingress.enabled` имеет значение `true`.

#### Итерация по спискам `range`
Используется для генерации повторяющихся блоков. Внутри `range` контекст (`.`) меняется на текущий элемент списка.

```yaml
containers:
- name: my-app
  env:
    {{- range .Values.env }}
    - name: {{ .name | quote }}
      value: {{ .value | quote }}
    {{- end }}
```

#### Ключевые функции
*   `quote`: Заключает значение в двойные кавычки, гарантируя, что оно будет обработано как строка.
*   `toYaml`: Сериализует объект (например, `map` или `list` из `values.yaml`) в формат YAML. Незаменима для вставки целых блоков конфигурации.
*   `nindent`: Добавляет отступы к каждой строке сгенерированного блока. Критически важна для соблюдения иерархии в YAML.

#### Управление пробелами
Дефисы `{{-` и `-}}` используются для удаления пробельных символов (включая переносы строк) до или после тега. Это помогает избежать пустых строк в итоговых манифестах и сделать их читаемыми.

## Практические сценарии

Рассмотрим продвинутые примеры на основе следующего `values.yaml`:
```yaml
# values.yaml
resources:
  limits:
    cpu: 100m
    memory: 128Mi
  requests:
    cpu: 100m
    memory: 128Mi

env:
  - name: VAR1
    value: "value1"
  - name: VAR2
    value: "value2"

annotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "80"
```

### 1. Вставка блока аннотаций
Комбинация `if`, `toYaml` и `nindent` позволяет добавлять целый блок `annotations`, если он определен.

```yaml
metadata:
  {{- if .Values.annotations }}
  annotations:
    {{- toYaml .Values.annotations | nindent 4 }}
  {{- end }}
```
*   `{{- if .Values.annotations }}` — проверяет наличие объекта.
*   `{{- toYaml .Values.annotations }}` — преобразует map в YAML.
*   `| nindent 4` — добавляет 4 пробела к каждой строке, обеспечивая правильную вложенность.

### 2. Генерация переменных окружения
Цикл `range` используется для создания списка переменных окружения. Функция `quote` защищает значения.

```yaml
spec:
  containers:
    - name: {{ .Chart.Name }}
      {{- if .Values.env }}
      env:
        {{- range .Values.env }}
        - name: {{ .name | quote }}
          value: {{ .value | quote }}
        {{- end }}
      {{- end }}
```

### 3. Вставка лимитов и запросов для ресурсов
`toYaml` и `nindent` также используются для вставки сложных структур, таких как `resources`.

```yaml
spec:
  containers:
  - name: {{ .Chart.Name }}
    resources:
      {{- toYaml .Values.resources | nindent 6 }}
```

## Дополнительная информация

### Локальная отладка шаблонов

Команда `helm template` — основной инструмент для отладки. Она рендерит чарт локально и выводит результат в `stdout`, не отправляя его в кластер.

```bash
# Рендер чарта в текущей директории
helm template my-release-name .

# Рендер с использованием кастомных values
helm template my-release-name . -f my-values.yaml
```

**Типичные проблемы при отладке:**
*   **Неправильные отступы:** YAML чувствителен к отступам. Ошибки часто приводят к невалидным манифестам. **Решение:** используйте `nindent`.
*   **Лишние пустые строки:** Управляющие конструкции Go могут оставлять пустые строки, делая YAML нечитаемым. **Решение:** используйте дефисы `{-` и `-}` для контроля пробелов.

### Создание стартового чарта

Команда `helm create` генерирует шаблонный чарт со стандартной структурой и примерами (`Deployment`, `Service`, `Ingress`, `HPA`, тесты), что является отличной отправной точкой.

```bash
helm create my-new-chart
```
Это создаст директорию `my-new-chart` со всеми необходимыми файлами.
