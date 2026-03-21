# Синтаксис Helm-шаблонов

---

## Определения

**Go templates** — движок шаблонизации, используемый Helm для генерации YAML-манифестов на основе значений и логики.

---

## Базовый синтаксис

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

---

## Управляющие конструкции

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

**Блок `with` (текста):**

изменение кон```yaml
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

---

## Дополнительные ссылки

- [Встроенные объекты](./objects.md) — .Values, .Release, .Chart и другие
- [Функции](./functions.md) — ключевые функции для работы с шаблонами
- [Именованные шаблоны](./_helpers.md) — создание переиспользуемых блоков
- [Практические сценарии](./scenarios/overview.md) — примеры использования
- [helm_templating](../helm_templating.md) — обзорная страница
