# Встроенные объекты Helm

---

## Определения

**Встроенные объекты** — предопределённые переменные, доступные во всех шаблонах Helm для доступа к значениям, метаданным и возможностям кластера.

---

## Основные концепции

### Обзор объектов

| Объект | Назначение |
|--------|------------|
| `.Values` | Значения из `values.yaml` и флагов `--set` |
| `.Release` | Метаданные релиза |
| `.Chart` | Метаданные чарта из `Chart.yaml` |
| `.Capabilities` | Возможности кластера |
| `.Files` | Доступ к файлам чарта |
| `.Template` | Информация о текущем шаблоне |

### Приоритет значений

`.Values` формируется из нескольких источников с приоритетом (по возрастанию):

1. Значения по умолчанию в `values.yaml`
2. Значения из зависимых чартов (`requirements.yaml`)
3. Файлы через `--values` (`-f`)
4. Флаги `--set` (наивысший приоритет)

### Scope и передача контекста

Объекты доступны через точку (`.`). Внутри `range` и `with` точка переопределяется. Для доступа к корневому контексту используют `$`:

```go
{{- range .Values.servers }}
server: {{ . }}
release: {{ $.Release.Name }}
{{- end }}
```

---

## Детальное описание

### .Values

Основной объект для передачи конфигурации чарта:

- `.Values.replicaCount` — количество реплик
- `.Values.image.repository` / `.Values.image.tag` — образ контейнера
- `.Values.service.type` / `.Values.service.port` — параметры сервиса
- `.Values.ingress.enabled` — условное включение ресурсов

**Приоритет источников:** `values.yaml` → `--values <file>` → `--set key=val`

### .Release

Метаданные релиза:

- `.Release.Name` — имя релиза
- `.Release.Namespace` — namespace релиза
- `.Release.Revision` — номер ревизии (инкремент при каждом upgrade)
- `.Release.Service` — сервис, выполняющий релиз (обычно `Helm`)
- `.Release.IsUpgrade` — `true`, если текущая операция upgrade
- `.Release.IsInstall` — `true`, если текущая операция install

### .Chart

Метаданные из `Chart.yaml`:

- `.Chart.Name` — имя чарта
- `.Chart.Version` — версия чарта
- `.Chart.AppVersion` — версия приложения
- `.Chart.Description` — описание чарта

### .Capabilities

Информация о возможностях кластера:

- `.Capabilities.KubeVersion.Version` — версия Kubernetes
- `.Capabilities.KubeVersion.Major` / `.Minor` — мажорная/минорная версия
- `.Capabilities.APIVersions.Has "batch/v1"` — проверка доступности API-ресурсов

### .Files

Доступ к файлам внутри чарта:

- `.Files.Get "path/to/file"` — чтение содержимого файла (строка)
- `.Files.Glob "patterns/*"` — поиск файлов по шаблону (возвращает `Files`)
- `.Files.Lines "path"` — чтение файла построчно
- `.Files.AsSecrets` — содержимое файлов как base64 (для Secret)
- `.Files.AsConfig` — содержимое файлов как YAML-значения (для ConfigMap)

### .Template

Информация о текущем шаблоне:

- `.Template.Name` — имя текущего файла шаблона
- `.Template.BasePath` — базовый путь к директории `templates`

---

## Практические сценарии

### Условное создание ресурсов по версии API

```go
{{- if .Capabilities.APIVersions.Has "networking.k8s.io/v1/Ingress" }}
apiVersion: networking.k8s.io/v1
{{- else }}
apiVersion: extensions/v1beta1
{{- end }}
kind: Ingress
```

### Разные значения при install и upgrade

```go
{{- if .Release.IsInstall }}
annotations:
  helm.sh/hook: post-install
{{- else if .Release.IsUpgrade }}
annotations:
  helm.sh/hook: post-upgrade
{{- end }}
```

### Чтение конфигурации из файлов чарта

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .Release.Name }}-config
data:
  {{- $files := .Files.Glob "configs/*.conf" }}
  {{- range $path, $content := $files }}
  {{ base $path }}: |
    {{ $content | indent 4 }}
  {{- end }}
```

---

## Дополнительная информация

### Best practices

- **Проверяйте `.Capabilities.APIVersions`** перед использованием новых API — обеспечивает совместимость с разными версия Kubernetes.
- **Используйте `.Release.IsInstall`/`.IsUpgrade`** для hooks и аннотаций, специфичных для операции.
- **`.Files.Glob` вместо хардкода** — позволяет динамически подключать файлы без изменения шаблонов.
- **`$.Release` внутри `range`** — сохраняет доступ к корневому контексту при переопределении точки.

### Troubleshooting

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `nil pointer evaluating .Values.x` | Значение не определено | Добавьте `default` или проверьте `values.yaml` |
| Файл через `.Files.Get` пуст | Путь неверный или файл вне чарта | Проверяйте путь относительно корня чарта |
| `.Capabilities` возвращает nil при `helm template` | Нет подключения к кластеру | Используйте `--dry-run` или проверяйте значения |

[Синтаксис шаблонов](./syntax.md) · [Функции](./functions.md) · [Именованные шаблоны](_helpers.md) · [Обзор шаблонизации](../helm_templating.md)
