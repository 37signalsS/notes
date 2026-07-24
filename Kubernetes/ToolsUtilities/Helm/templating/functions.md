# Функции Helm-шаблонов

---

## Определения

**Go Templates Functions** — встроенные функции движка шаблонов Go (например, `and`, `or`, `not`, `index`, `print`).

**Функции Sprig** — библиотека из 100+ функций для работы со строками, коллекциями, математикой, датами и криптографией. Интегрирована в Helm для расширения стандартных возможностей Go Templates.

**Helm-функции** — встроенные функции, специфичные для Helm (`required`, `fail`, `lookup`, `tpl`, `include`), предназначенные для взаимодействия с инфраструктурой Kubernetes и управления процессом рендеринга.

---

## Базовые концепции

### Пайплайны (Pipelines)

Функции комбинируются через символ пайпа (`|`) — результат одной передаётся в следующую в качестве последнего аргумента. Подробнее о синтаксисе — [syntax.md](./syntax.md).

### Область видимости (Scope)

Точка (`.`) — текущий контекст. Внутри циклов (`range`) точка меняется на текущий элемент. Для доступа к корневому контексту (глобальным объектам) используют `$`:

```go
{{- range .Values.servers }}
server: {{ . }}
release: {{ $.Release.Name }}
{{- end }}
```

### Библиотека Sprig в Helm

Sprig подключён автоматически — не требует импорта. Она предоставляет функции для манипуляции данными, которые отсутствуют в стандартной поставке Go. Документация: [sprig-docs](https://masterminds.github.io/sprig/).

---

## Ключевые функции

### Строковые

| Функция | Назначение | Пример |
|---------|------------|--------|
| `quote` / `squote` | Заключение в двойные/одинарные кавычки | `{{ .Values.name | quote }}` |
| `default` | Значение по умолчанию | `{{ .Values.tag | default "latest" }}` |
| `cat` | Объединение строк через пробел | `{{ cat "v" .Chart.AppVersion }}` |
| `trunc` | Обрезка строки до указанной длины | `{{ .Release.Name | trunc 63 | trimSuffix "-" }}` |
| `trimSuffix` / `trimPrefix` | Удаление суффикса/префикса из строки | `{{ "v1-app" | trimPrefix "v1-" }}` |
| `replace` | Замена подстроки | `{{ "v1+beta" | replace "+" "_" }}` |
| `lower` / `upper` | Приведение к нижнему/верхнему регистру | `{{ .Values.name | lower }}` |
| `printf` | Форматированная строка | `{{ printf "%s-%s" .Chart.Name .Release.Name }}` |
| `ternary` | Условное выражение (ternary operator) | `{{ .Values.debug | ternary "debug" "info" }}` |
| `coalesce` | Возвращает первый не пустой аргумент | `{{ coalesce .val1 .val2 "fallback" }}` |

### Коллекции и YAML / JSON

| Функция | Назначение | Пример |
|---------|------------|--------|
| `toYaml` | Сериализация объекта в YAML | `{{ toYaml .Values.nodeSelector }}` |
| `fromYaml` | Парсинг YAML-строки в объект | `{{ $data := fromYaml .Values.raw }}` |
| `nindent` | Отступ для YAML-блока с переносом строки | `{{ toYaml .Values.tolerations | nindent 8 }}` |
| `indent` | Только отступ (без переноса первой строки) | `{{ .Values.config | indent 4 }}` |
| `toJson` / `fromJson` | Сериализация/парсинг JSON | `{{ .Values.data | toJson }}` |
| `toToml` | Сериализация в TOML | `{{ .Values.config | toToml }}` |
| `merge` | Слияние словарей (изменяет первый словарь) | `{{ merge $dest $src }}` |
| `mergeOverwrite` | Слияние с перезаписью существующих ключей | `{{ mergeOverwrite $dest $src }}` |
| `deepCopy` | Создание полной копии объекта (важно перед merge) | `{{ $copy := deepCopy .Values.orig }}` |
| `omit` | Удаление ключей из словаря | `{{ omit $dict "key1" "key2" }}` |
| `dict` | Создание словаря | `{{ dict "key" "value" }}` |
| `hasKey` | Проверка наличия ключа | `{{ if hasKey .Values "config" }}` |
| `set` / `unset` | Установка/удаление значения в словаре | `{{ set $dict "key" "val" }}` |
| `compact` | Удаление пустых элементов из списка | `{{ list "a" "" "b" | compact }}` |

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
| `sha256sum` | Вычисление SHA256 хеша | `{{ .Values.data | sha256sum }}` |
| `sha512sum` | Вычисление SHA512 хеша | `{{ .Values.data | sha512sum }}` |
| `b64enc` | Base64 кодирование | `{{ .Values.data | b64enc }}` |
| `b64dec` | Base64 декодирование | `{{ .Values.data | b64dec }}` |

### Регулярные выражения

| Функция | Назначение | Пример |
|---------|------------|--------|
| `regexMatch` | Проверка соответствия шаблону | `{{ if regexMatch "^v[0-9]" .val }}` |
| `regexReplaceAll` | Замена всех совпадений | `{{ .val | regexReplaceAll "\\." "-" }}` |
| `regexFind` | Поиск подстроки | `{{ regexFind "[0-9]+" .val }}` |

### Версионирование

| Функция | Назначение | Пример |
|---------|------------|--------|
| `semverCompare` | Сравнение Semantic Versioning версий | `{{ if semverCompare ">=1.23-0" .Capabilities.KubeVersion.Version }}` |

---

## Практические сценарии

### Использование toYaml и nindent

`nindent` является предпочтительным для YAML, так как он гарантирует перенос на новую строку перед вставкой блока.

```yaml
spec:
  template:
    spec:
      {{- if .Values.affinity }}
      affinity:
        {{- toYaml .Values.affinity | nindent 8 }}
      {{- end }}
```

### Глубокое копирование и безопасное слияние

Функции `merge` и `mergeOverwrite` модифицируют первый переданный аргумент. Чтобы избежать нежелательного изменения `.Values` или других объектов, используйте `deepCopy`.

```go
{{- $config := deepCopy .Values.defaultConfig -}}
{{- $overrides := .Values.overrides -}}
{{- mergeOverwrite $config $overrides -}}
config:
  {{- toYaml $config | nindent 2 }}
```

### Безопасное использование lookup

`lookup` возвращает `nil` при выполнении `helm template` или `helm install --dry-run`. Всегда проверяйте результат перед обращением к данным.

```yaml
{{- $secret := (lookup "v1" "Secret" .Release.Namespace "my-secret") -}}
{{- if $secret }}
data:
  password: {{ index $secret.data "password" }}
{{- else }}
data:
  password: {{ "default-pass" | b64enc }}
{{- end }}
```

### Динамический рендер через tpl

Позволяет активировать логику шаблонов внутри строк, хранящихся в `values.yaml`.

```yaml
{{- $context := . }}
{{- range .Values.configFiles }}
{{ .name }}: |
  {{ tpl .content $context | nindent 2 }}
{{- end }}
```

### Циклы до определенного числа (until)

Создание итераций без привязки к существующей коллекции.

```yaml
{{- range $i := until 5 }}
- name: replica-{{ $i }}
{{- end }}
```

---

## Функции Sprig по категориям

### Строки

`lower`, `upper`, `title`, `quote`, `squote`, `trim`, `trimSuffix`, `trimPrefix`, `replace`, `repeat`, `substr`, `plural`:

```go
{{ "hello" | upper }}              # → "HELLO"
{{ "my-app-v1" | trimPrefix "my-" }} # → "app-v1"
{{ "text" | repeat 3 }}            # → "texttexttext"
{{ "apple" | plural "apples" 2 }}  # → "apples"
```

### Коллекции

`first`, `last`, `rest`, `append`, `prepend`, `reverse`, `uniq`, `without`, `concat`, `has`:

```go
{{ list "a" "b" "c" | first }}     # → "a"
{{ list "a" "b" | append "c" }}    # → [a b c]
{{ list "a" "a" "b" | uniq }}      # → [a b]
{{ list "a" "b" | has "a" }}       # → true
```

### Математика

`add`, `sub`, `mul`, `div`, `mod`, `max`, `min`, `ceil`, `floor`, `round`:

```go
{{ add 2 3 }}                      # → 5
{{ div 10 3 }}                     # → 3
{{ mul 1024 1024 }}                # → 1048576
{{ max 1 5 10 }}                   # → 10
```

### Даты

`now`, `date`, `dateModify`, `htmlDate`, `unixEpoch`:

```go
{{ now | date "2006-01-02" }}      # → "2026-07-23"
{{ now | dateModify "+24h" | date "2006-01-02" }} # → дата завтрашнего дня
{{ unixEpoch now }}                # → 1784764800 (пример)
```

---

## Дополнительная информация

### Лучшие практики

- **`nindent` вместо `indent`** — `nindent` добавляет перенос строки перед отступом, что критично для корректного YAML.
- **`include` вместо `template`** — `include` возвращает строку, что позволяет использовать её в пайплайнах (например, `include "tpl" . | nindent 4`).
- **`trunc 63 | trimSuffix "-"`** — стандарт для имен ресурсов в Kubernetes для соблюдения лимитов DNS.
- **`required` для критичных значений** — прерывает деплой, если обязательные данные не переданы (например, пароли БД).
- **Использование deepCopy** — защищает глобальный контекст от непреднамеренных изменений при использовании функций `merge`.

### Устранение неисправностей

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `wrong type for value` | Несоответствие типа в пайплайне | Убедитесь, что функция получает ожидаемый тип (например, `toYaml` ожидает `map` или `slice`) |
| `nil pointer evaluating` | Обращение к несуществующему полю | Используйте `default` или проверку существования через `if` / `hasKey` |
| `fail` при рендере | Сработала проверка `required` или явный вызов `fail` | Проверьте переданные значения в `values.yaml` или через `--set` |
| `lookup` возвращает nil | Работа в режиме `--dry-run` или ресурс отсутствует | Предусматривайте fallback-логику для режима тестирования |

[Синтаксис шаблонов](./syntax.md) · [Встроенные объекты](./objects.md) · [Обзор шаблонизации](../helm_templating.md)
