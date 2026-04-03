# ConfigMap and File Management

---

## Definitions

**.Files** — встроенный объект Helm для чтения файлов из директории чарта (не из `templates/`). Определение и полный список методов — в [Встроенные объекты Helm](../objects.md).

**Экранирование шаблонизатора** — приём с обратными кавычками (`` ` ``) для предотвращения интерпретации пользовательских `{{ }}` в конфигурационных файлах.

---

## Basic Concepts

Файл охватывает два практических сценария при работе с ConfigMap:

1. **Вставка файлов в ConfigMap** — чтение содержимого из директории `files/` через `.Files.Get` и `.Files.Glob`.
2. **Экранирование `{{ }}`** — конфигурационные файлы (Postfix, Prometheus и др.) могут содержать синтаксис, конфликтующий с Helm-шаблонизатором.

Оба сценария не дублируют определение `.Files`, а показывают практическое применение. Методы объекта:

| Метод | Назначение |
|-------|------------|
| `.Files.Get "path"` | Чтение содержимого файла |
| `.Files.Glob "pattern"` | Поиск файлов по шаблону |
| `.Files.AsSecrets` | Кодирование как base64 для Secret |
| `.Files.AsConfig` | Вставка как данные ConfigMap |

Структура чарта для работы с файлами:

```
chart/
├── files/
│   └── config.json
└── templates/
    └── configmap.yaml
```

Файлы из `templates/` **недоступны** через `.Files` — они обрабатываются шаблонизатором. Файлы из `files/` — доступны как raw-данные.

---

## Practical Scenarios

### Вставка отдельного файла

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
data:
  config.json: |
    {{ .Files.Get "files/config.json" | nindent 4 }}
```

### Массовая вставка всех файлов из директории

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
data:
  {{- $files := .Files }}
  {{- range $path, $bytes := .Files.Glob "files/**" }}
  {{ $path | replace "files/" "" }}: |
    {{ $files.Get $path | nindent 4 }}
  {{- end }}
```

Каждый файл из `files/` становится отдельным ключом в `data` ConfigMap с именем, равным относительному пути.

### Экранирование `{{ }}` в конфигурационных файлах

Файлы вроде Postfix или Prometheus могут содержать `{{ .Value }}`, что Helm интерпретирует как шаблон.

**Неправильно (ошибка рендеринга):**

```yaml
data:
  config.file: |
    value = {{ .POSTFIX_VALUE }}
```

**Правильно (обратные кавычки):**

```yaml
data:
  config.file: |
    value = `{{` .POSTFIX_VALUE `}}`
```

В итоговом манифесте останется литерал `{{ .POSTFIX_VALUE }}` — Helm не будет его интерпретировать.

---

## Additional Information

Определение `.Files` и все методы — в [Встроенные объекты Helm](../objects.md). Работа с функциями (`nindent`, `sha256sum`) — в [Функции Helm](../functions.md). Автоматический перезапуск при изменении ConfigMap — в [Restart on Change](./restart_on_change.md).
