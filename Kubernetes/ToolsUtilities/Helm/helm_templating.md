# Шаблонизация в Helm

Helm использует Go template engine (движок шаблонов Go) в сочетании с библиотекой Sprig для динамической генерации манифестов Kubernetes. Это позволяет параметризовать конфигурации, использовать логику (условия, циклы) и повторно использовать блоки кода.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Go templates** | Движок шаблонизации на языке Go (`text/template`), используемый для рендеринга YAML-файлов |
| **Библиотека Sprig** | Набор из более чем 100 функций (строковые, математические, работа со списками), расширяющий возможности Go templates |
| **Встроенные объекты** | Предопределённые переменные (например, `.Values`, `.Release`), предоставляющие доступ к параметрам и метаданным |
| **Именованные шаблоны** | Переиспользуемые фрагменты кода (partial), определяемые в `_helpers.tpl` через конструкцию `define` |
| **Контекст (Scope)** | Текущая область видимости данных, обозначаемая точкой (`.`) |

---

## Базовые концепции

### Разработка шаблонов и синтаксис Go Templates

Шаблоны в каталоге `templates/` используют мощные возможности языка шаблонов Go:

*   **Встроенные объекты**: Доступ к данным через объекты `.Chart` (метаданные чарта), `.Values` (параметры пользователя) и `.Release` (данные о текущем выпуске: имя, пространство имен).
*   **Ссылки на значения**: Вставка параметров синтаксисом `{{ .Values.key }}`.
*   **Функции и конвейеры (Pipelines)**: Преобразование данных с помощью функций и их цепочек, например: `{{ .Values.key | quote }}` или `{{ .Values.key | default "default-value" }}`.
*   **Управление потоком (Flow Control)**: Использование условий `if/else` для логики включения ресурсов и циклов `range` для итерации по спискам.
*   **Именованные шаблоны (Named Templates)**: Повторно используемые фрагменты кода, реализующие принцип **DRY** (Don't Repeat Yourself).

Подробности синтаксиса см. в разделе **[Синтаксис шаблонов](./templating/syntax.md)**.

### Встроенные объекты

Helm предоставляет доступ к нескольким глобальным объектам:

- **`.Values`**: данные из файла `values.yaml` или переданные через `--set`.
- **`.Release`**: информация о текущем релизе (имя, пространство имен, статус).
- **`.Chart`**: метаданные из файла `Chart.yaml`.
- **`.Capabilities`**: информация о версии Kubernetes и поддерживаемых API.
- **`.Files`**: доступ к не-шаблонным файлам внутри чарта.

Полный список объектов и их свойств доступен в разделе **[Встроенные объекты](./templating/objects.md)**.

### Функции шаблонизации

Функции позволяют модифицировать данные в процессе рендеринга.

1.  **Sprig-функции**: `default`, `quote`, `upper`, `trunc`, `sha256sum`, `b64enc`.
2.  **Helm-функции**:
    - `required`: помечает параметр как обязательный (прерывает установку, если значение пустое).
    - `include`: вставляет именованный шаблон с передачей контекста.
    - `tpl`: рендерит строку как шаблон (полезно для динамических ConfigMap).
    - `lookup`: позволяет запрашивать существующие ресурсы из кластера.

Справочник по функциям представлен в разделе **[Функции Helm](./templating/functions.md)**.

---

## Практические сценарии

### Расширенный пример шаблона (ConfigMap + Deployment)

Этот пример демонстрирует использование встроенных объектов, условной логики, функций пайплайнов и циклов.

**templates/configmap.yaml:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .Release.Name }}-config
  labels:
    app: {{ .Chart.Name }}
data:
  favoriteDrink: {{ .Values.favorite.drink | default "coffee" | quote }}
  greeting: {{ if .Values.greeting }}{{ .Values.greeting | quote }}{{ else }}"Hello World!"{{ end }}
  items: |
{{- range .Values.items }}
    - {{ . | quote }}
{{- end }}
```

**templates/deployment.yaml:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-deployment
spec:
  replicas: {{ .Values.replicas | default 2 }}
  selector:
    matchLabels:
      app: {{ .Chart.Name }}
  template:
    metadata:
      labels:
        app: {{ .Chart.Name }}
    spec:
      containers:
      - name: {{ .Chart.Name }}-container
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default "latest" }}"
        ports:
        - containerPort: {{ .Values.service.port }}
        env:
        - name: CONFIG_GREETING
          valueFrom:
            configMapKeyRef:
              name: {{ .Release.Name }}-config
              key: greeting
```

### Условная логика (if/else)

Используется для включения или исключения ресурсов и параметров на основе значений.

```yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "mychart.fullname" . }}
spec:
  rules:
    - host: {{ .Values.ingress.host | quote }}
{{- end }}
```

### Итерация (range)

Позволяет генерировать списки параметров, например, переменные окружения.

```yaml
env:
{{- range $name, $value := .Values.extraEnv }}
  - name: {{ $name }}
    value: {{ $value | quote }}
{{- end }}
```

### Работа с YAML-блоками (toYaml и nindent)

Функция `toYaml` преобразует структуру данных в YAML, а `nindent` добавляет правильный отступ, что критично для корректности манифестов.

```yaml
{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
```

### Использование именованных шаблонов

Вынесение общих меток (labels) в `_helpers.tpl` для соблюдения принципа DRY (Don't Repeat Yourself).

**В `_helpers.tpl`:**
```go
{{- define "mychart.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
```

**В шаблоне (например, deployment.yaml):**
```yaml
metadata:
  labels:
    {{- include "mychart.labels" . | nindent 4 }}
```

Больше примеров и паттернов см. в разделах **[Именованные шаблоны и хелперы](./templating/_helpers.md)** и **[Обзор сценариев шаблонизации](./templating/scenarios/overview.md)**.

---

## Дополнительная информация

### Отладка шаблонов

Для проверки результата рендеринга без внесения изменений в кластер используются следующие команды:

- `helm template <release-name> <path-to-chart>` — выводит сгенерированные манифесты в stdout.
- `helm install --dry-run --debug <release-name> <path-to-chart>` — имитирует установку и показывает детальную информацию об объектах и ошибках.

### Полезные ссылки

- [Обзор Helm](./helm_overview.md) — основы работы с инструментом.
- [Структура Helm-чарта](./helm_chart_structure.md) — описание директорий и файлов.
- [Шаблонизация в werf](../../../CI-CD/Tools/werf_overview.md#сценарий-3-шаблонизация-манифеста-kubernetes) — особенности использования Go templates в экосистеме werf.
- [Официальная документация Helm](https://helm.sh/docs/chart_template_guide/) (англ.).
