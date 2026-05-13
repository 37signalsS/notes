# Функции Helm-шаблонов

---

## Определения

**Функции Sprig** — библиотека из 100+ функций для работы со строками, коллекциями, математикой, датами и криптографией. Интегрирована в Helm.

**Helm-функции** — встроенные функции, специфичные для Helm (`required`, `fail`, `lookup`, `tpl`), не входящие в Sprig.

---

## Основные концепции

### Pipeline

Функции комбинируются через пайплайн (`|`) — результат одной передаётся в следующую. Подробнее о синтаксисе пайплайна и whitespace control — [syntax.md](./syntax.md).

### Scope (контекст)

Точка (`.`) — текущий контекст. Внутри `range` точка меняется на текущий элемент. Для доступа к корневому контексту используют `$`:

```go
{{- range .Values.servers }}
server: {{ . }}
release: {{ $.Release.Name }}
{{- end }}
```

### Sprig в Helm

Sprig подключён автоматически — не требует импорта. Документация: [sprig-docs](https://masterminds.github.io/sprig/).

---

## Ключевые функции

### Строковые

| Функция | Назначение | Пример |
|---------|------------|--------|
| `quote` | Заключение в двойные кавычки | `{{ .Values.name \| quote }}` |
| `default` | Значение по умолчанию | `{{ .Values.tag \| default "latest" }}` |
| `trunc` | Обрезка строки до указанной длины | `{{ .Release.Name \| trunc 63 \| trimSuffix "-" }}` |
| `trimSuffix` | Удаление суффикса из строки | `{{ "release-1" \| trimSuffix "-1" }}` |
| `replace` | Замена подстроки | `{{ "v1+beta" \| replace "+" "_" }}` |
| `lower` / `upper` | Приведение к нижнему/верхнему регистру | `{{ .Values.name \| lower }}` |
| `printf` | Форматированная строка | `{{ printf "%s-%s" .Chart.Name .Release.Name }}` |
| `ternary` | Условное выражение (ternary operator) | `{{ .Values.debug \| ternary "debug" "info" }}` |

### Коллекции и YAML

| Функция | Назначение | Пример |
|---------|------------|--------|
| `toYaml` | Сериализация объекта в YAML | `{{ toYaml .Values.nodeSelector }}` |
| `nindent` | Отступ для YAML-блока с переносом строки | `{{ toYaml .Values.tolerations \| nindent 8 }}` |
| `indent` | Только отступ (без переноса первой строки) | `{{ .Values.config \| indent 4 }}` |
| `toJson` / `fromJson` | Сериализация/парсинг JSON | `{{ .Values.data \| toJson }}` |
| `toToml` | Сериализация в TOML | `{{ .Values.config \| toToml }}` |
| `merge` | Слияние словарей | `{{ merge $base $override }}` |
| `mergeOverwrite` | Слияние с перезаписью существующих ключей | `{{ mergeOverwrite $base $override }}` |
| `omit` | Удаление ключей из словаря | `{{ omit $dict "key1" "key2" }}` |
| `dict` | Создание словаря | `{{ dict "key" "value" }}` |
| `hasKey` | Проверка наличия ключа | `{{ if hasKey .Values "config" }}` |
| `set` | Установка значения в словаре | `{{ $_ := set $dict "key" "val" }}` |

### Helm-специфичные

| Функция | Назначение | Пример |
|---------|------------|--------|
| `required` | Обязательный параметр (ошибка, если пусто) | `{{ required "Image required" .Values.image }}` |
| `fail` | Прерывание рендера с ошибкой | `{{ if .Values.bad }}{{ fail "Bad config" }}{{ end }}` |
| `tpl` | Рендер строки как шаблона | `{{ tpl .Values.config . }}` |
| `include` | Вставка именованного шаблона | `{{ include "chart.fullname" . }}` |
| `lookup` | Чтение ресурсов из кластера | `{{ lookup "v1" "Secret" .Release.Namespace "my-secret" }}` |

### Криптографические

| Функция | Назначение | Пример |
|---------|------------|--------|
| `sha256sum` | Вычисление SHA256-хеша | `{{ .Values.data \| sha256sum }}` |
| `b64enc` | Base64 кодирование | `{{ .Values.data \| b64enc }}` |
| `b64dec` | Base64 декодирование | `{{ .Values.data \| b64dec }}` |

### Версионирование

| Функция | Назначение | Пример |
|---------|------------|--------|
| `semverCompare` | Сравнение semver-версий | `{{ if semverCompare ">=1.23-0" .Capabilities.KubeVersion.Version }}` |

---

## Примеры использования

### toYaml и nindent

```yaml
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
```

### Комбинирование функций

```yaml
image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
```

### required — обязательные параметры

```yaml
{{- $image := required "Values.image.repository обязателен" .Values.image.repository }}
image: "{{ $image }}"
```

### tpl — рендер строки как шаблона

Позволяет динамически генерировать конфигурацию:

```yaml
{{- $context := . }}
{{- range .Values.configFiles }}
{{ .name }}: |
  {{ tpl .content $context | nindent 2 }}
{{- end }}
```

---

## Функции Sprig по категориям

Полный список — [sprig-docs](https://masterminds.github.io/sprig/). Ниже — основные группы с примерами.

### Строки

`lower`, `upper`, `title`, `quote`, `squote`, `trim`, `trimSuffix`, `trimPrefix`, `replace`, `repeat`, `substr`:

```go
{{ "hello" | upper }}              → "HELLO"
{{ "my-app-v1" | trimPrefix "my-" }} → "app-v1"
{{ "text" | repeat 3 }}            → "texttexttext"
```

### Коллекции

`first`, `last`, `rest`, `append`, `prepend`, `reverse`, `uniq`, `without`, `concat`:

```go
{{ list "a" "b" "c" | first }}     → "a"
{{ list "a" "b" | append "c" }}    → [a b c]
{{ list "a" "a" "b" | uniq }}      → [a b]
```

### Математика

`add`, `sub`, `mul`, `div`, `mod`, `max`, `min`, `ceil`, `floor`:

```go
{{ add 2 3 }}                      → 5
{{ div 10 3 }}                     → 3
{{ mul 1024 1024 }}                → 1048576
```

### Даты

`now`, `date`, `dateModify`, `htmlDate`:

```go
{{ now | date "2006-01-02" }}      → "2026-04-03"
{{ now | dateModify "+24h" }}      → время через 24 часа
```

### Криптография

`sha256sum`, `sha512sum`, `b64enc`, `b64dec`, `derivePassword`:

```go
{{ "secret" | sha256sum }}         → 256-битный хеш
{{ "secret" | b64enc }}            → "c2VjcmV0"
```

---

## Дополнительная информация

### Best practices

- **`nindent` вместо `indent`** — `nindent` добавляет перенос строки перед отступом, что корректно для YAML-блоков.
- **`include` вместо `template`** — `include` возвращает строку, которую можно пайпить в другие функции.
- **`trunc 63 | trimSuffix "-"`** — стандартная комбинация для имён ресурсов (лимит Kubernetes).
- **`required` для критичных значений** — предотвращает деплой без обязательных параметров.
- **`lookup` требует `--dry-run=false`** — не работает при обычном `helm template`.

### Troubleshooting

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `wrong type for value` | Неверный тип в пайплайне | Проверяйте тип: `toYaml` требует объект, не строку |
| `nil pointer evaluating` | Отсутствующее значение | Используйте `default` или проверку `if hasKey` |
| `fail` при рендере | Сработал `required` или `fail` | Убедитесь, что все обязательные значения переданы |
| `lookup` возвращает nil | Ресурс не найден или `--dry-run` | Проверяйте `{{ if $result }}` перед использованием |

[Синтаксис шаблонов](./syntax.md) · [Встроенные объекты](./objects.md) · [Именованные шаблоны](./_helpers.md) · [Обзор шаблонизации](../helm_templating.md)
