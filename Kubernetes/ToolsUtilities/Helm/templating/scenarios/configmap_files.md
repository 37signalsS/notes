# Работа с ConfigMap и файлами

---

## Определения

**Объект .Files** — встроенный объект Helm для чтения файлов из чарта (не из templates/).

---

## Вставка данных в ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
data:
  app.conf: |
    {{ .Values.configContent | nindent 4 }}
  
  config.json: |
    {{ .Files.Get "files/config.json" | nindent 4 }}
```

---

## Чтение файлов из чарта

- `.Files.Get "path"` — чтение содержимого файла
- `.Files.Glob "patterns/*"` — поиск по шаблону
- `.Files.AsSecrets` — доступ как к секретам
- `.Files.AsConfig` — доступ как к ConfigMap

**Пример структуры чарта:**
```
chart/
├── files/
│   └── config.json
└── templates/
    └── configmap.yaml
```

**templates/configmap.yaml:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
data:
  {{- $files := .Files }}
  {{- range $path, $bytes := .Files.Glob "files/**" }}
  {{ $path | replace "files/" "" }}: |
    {{ $files.Get $path | nindent 2 }}
  {{- end }}
```

---

## Экранирование символов шаблонизатора

Конфигурационные файлы могут содержать синтаксис `{{ .Value }}` (Postfix, Prometheus и др.), что конфликтует с Helm.

**Неправильно (ошибка):**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-config
data:
  config.file: |
    value = {{ .POSTFIX_VALUE }}
```

**Правильно (экранирование):**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-config
data:
  config.file: |
    value = `{{` .POSTFIX_VALUE `}}`
```

Используются обратные одинарные кавычки (`` ` ``). В итоговом манифесте останется `{{ .POSTFIX_VALUE }}`.

---

## Дополнительные ссылки

- [Функции](../functions.md) — toYaml, nindent и другие
- [Именованные шаблоны](../templates/_helpers.md) — переиспользуемые блоки
- [ helm_templating](../helm_templating.md) — обзорная страница
