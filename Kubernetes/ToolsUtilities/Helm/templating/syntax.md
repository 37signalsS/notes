# Синтаксис Helm-шаблонов

---

## Определения

**Go templates** — движок шаблонизации, используемый Helm для генерации YAML-манифестов на основе значений и логики. Основан на [`text/template`](https://pkg.go.dev/text/template) из стандартной библиотеки Go.

---

## Основные концепции

### Вставка значений

Базовый синтаксис — двойные фигурные скобки `{{ }}`:

```yaml
metadata:
  name: {{ .Values.appName }}
```

### Конвейер (pipeline)

Результат одного выражения передаётся в следующее через `|`:

```yaml
name: {{ .Values.name | default "myapp" | lower | trunc 63 | trimSuffix "-" }}
```

Порядок: слева направо. Подробнее о функциях — [functions.md](./functions.md).

### Whitespace control

Дефис (`-`) внутри тегов удаляет пробелы и переносы строк:

| Синтаксис | Поведение |
|-----------|-----------|
| `{{ value }}` | Сохраняет все пробелы |
| `{{- value }}` | Удаляет пробелы слева |
| `{{ value -}}` | Удаляет пробелы справа |
| `{{- value -}}` | Удаляет с обеих сторон |

```yaml
# ШАБЛОН:
env:
{{- range $k, $v := .Values.env }}
  - name: {{ $k }}
    value: {{ $v | quote }}
{{- end }}

# РЕЗУЛЬТАТ:
env:
  - name: KEY1
    value: "VALUE1"
  - name: KEY2
    value: "VALUE2"
```

---

## Управляющие конструкции

### if / else

Условные блоки с поддержкой `else` и `else if`:

```yaml
{{- if .Values.metrics.enabled }}
ports:
  - name: metrics
    containerPort: 9090
{{- else }}
# Метрики отключены
{{- end }}
```

**Логические операторы:** `and`, `or`, `not`, `eq`:

```yaml
{{- if and .Values.ingress.enabled .Values.ingress.tls }}
tls:
  - hosts:
      - {{ .Values.ingress.host }}
{{- end }}
```

### with

Изменение контекста (`.`) для работы с вложенными объектами. Блок не рендерится, если значение пустое:

```yaml
{{- with .Values.resources }}
resources:
  limits:
    cpu: {{ .limits.cpu }}
    memory: {{ .limits.memory }}
{{- end }}
```

**`with` + `else`** (альтернатива при пустом значении):

```yaml
{{- with .Values.resources }}
resources:
  {{- toYaml . | nindent 2 }}
{{- else }}
resources: {}
{{- end }}
```

### range

Итерация по словарю или списку:

```yaml
# Итерация по словарю (ключ + значение)
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

# range с индексом
{{- range $i, $svc := .Values.services }}
---
{{- end }}
```

---

## Практические сценарии

### Динамическое создание аргументов контейнера

```yaml
args:
{{- range .Values.extraArgs }}
  - {{ . | quote }}
{{- end }}
```

### Условное подключение томов

```yaml
{{- if .Values.tls.enabled }}
volumes:
  - name: tls-cert
    secret:
      secretName: {{ .Values.tls.secretName }}
{{- end }}
```

### Переопределение контекста с fallback

```yaml
{{- with .Values.service }}
type: {{ .type | default "ClusterIP" }}
port: {{ .port | default 80 }}
{{- end }}
```

---

## Дополнительная информация

### Best practices

- **Всегда используйте `{{-` перед `range`/`if`** — предотвращает пустые строки в YAML.
- **`with` вместо повторения `.Values.section`** — сокращает дублирование вложенных путей.
- **Проверяйте пустые значения** — `with` скрывает блок при `nil`/`false`/`""`, `if` рендерит `else`.
- **`quote` для строк в YAML** — предотвращает парсинг чисел/булевых значений как типов Go.

### Troubleshooting

| Ошибка | Причина | Решение |
|--------|---------|---------|
| Лишние пустые строки в YAML | Нет `{{-` / `-}}` | Добавьте whitespace control |
| `nil pointer` внутри `with` | Значение пустое — блок пропущен | Добавьте `{{- else }}` |
| `range` по несуществующему списку | Ключ отсутствует в values | Используйте `default list` или проверку `if` |
| YAML невалиден после рендера | Отступы в шаблоне | Проверяйте `nindent` и базовые отступы |

[Встроенные объекты](./objects.md) · [Функции](./functions.md) · [Именованные шаблоны](_helpers.md) · [Обзор шаблонизации](../helm_templating.md)
