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
2. Значения из зависимых чартов
3. Файлы через `--values` (`-f`)
4. Флаги `--set` (наивысший приоритет)

### Область видимости и передача контекста

Объекты доступны через точку (`.`). Внутри `range` и `with` точка переопределяется (меняется текущий scope). Для доступа к корневому контексту используют переменную `$`:

```go
{{- range .Values.servers }}
server: {{ . }}
release: {{ $.Release.Name }}
{{- end }}
```

### Детальное описание объектов

#### .Values

Основной объект для передачи пользовательской конфигурации:

- `.Values.replicaCount` — количество реплик
- `.Values.image.repository` / `.Values.image.tag` — параметры образа контейнера
- `.Values.service.type` / `.Values.service.port` — параметры сервиса
- `.Values.ingress.enabled` — флаг для условного включения ресурсов

#### .Release

Метаданные текущего релиза:

- `.Release.Name` — имя релиза
- `.Release.Namespace` — пространство имён (namespace) релиза
- `.Release.Revision` — номер ревизии (инкремент при каждом обновлении)
- `.Release.Service` — сервис, выполняющий релиз (обычно `Helm`)
- `.Release.IsUpgrade` — `true`, если выполняется обновление (upgrade)
- `.Release.IsInstall` — `true`, если выполняется первичная установка (install)

#### .Chart

Метаданные из файла `Chart.yaml`:

- `.Chart.Name` — имя чарта
- `.Chart.Version` — версия чарта (SemVer)
- `.Chart.AppVersion` — версия самого приложения
- `.Chart.Description` — краткое описание

#### .Capabilities

Информация о возможностях Kubernetes-кластера:

- `.Capabilities.KubeVersion.Version` — полная версия Kubernetes
- `.Capabilities.KubeVersion.Major` / `.Minor` — основные компоненты версии
- `.Capabilities.APIVersions.Has "batch/v1"` — проверка поддержки конкретных API-ресурсов

#### .Files

Инструменты для работы с не-шаблонными файлами внутри чарта:

- `.Files.Get "path"` — чтение содержимого файла как строки
- `.Files.Glob "pattern"` — поиск файлов по маске (возвращает объект `Files`)
- `.Files.Lines "path"` — итерация по строкам файла
- `.Files.AsSecrets` — кодирование содержимого в base64 для использования в `Secret`
- `.Files.AsConfig` — вставка содержимого как данных для `ConfigMap`

#### .Template

Информация о самом файле шаблона:

- `.Template.Name` — относительный путь к текущему файлу шаблона
- `.Template.BasePath` — базовый путь к директории `templates`

---

## Практические сценарии

### Условное создание ресурсов по версии API

Использование `.Capabilities` для обеспечения совместимости с разными версиями кластера:

```go
{{- if .Capabilities.APIVersions.Has "networking.k8s.io/v1/Ingress" }}
apiVersion: networking.k8s.io/v1
{{- else }}
apiVersion: extensions/v1beta1
{{- end }}
kind: Ingress
```

### Разделение логики при установке и обновлении

Пример использования `.Release.IsInstall` для специфичных аннотаций:

```go
{{- if .Release.IsInstall }}
annotations:
  helm.sh/hook: post-install
{{- else if .Release.IsUpgrade }}
annotations:
  helm.sh/hook: post-upgrade
{{- end }}
```

### Динамическое наполнение ConfigMap из файлов

Использование `.Files.Glob` для массовой вставки конфигурационных файлов:

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

### Лучшие практики

- **Версионная совместимость:** всегда проверяйте `.Capabilities.APIVersions` перед использованием новых или удалённых API-групп.
- **Управление хуками:** используйте `.Release.IsInstall` и `.Release.IsUpgrade` для управления поведением жизненного цикла (hooks).
- **Внешние конфигурации:** используйте `.Files.Glob` вместо жёсткого прописывания путей, чтобы позволить пользователям добавлять файлы без изменения логики шаблонов.
- **Корневой контекст:** используйте `$.` для обращения к глобальным объектам (`$.Values`, `$.Release`) внутри циклов `range`.

### Устранение неисправностей

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `nil pointer evaluating .Values.x` | Переменная не определена в `values.yaml` | Используйте функцию `default` или добавьте проверку `if` |
| `.Files.Get` возвращает пустую строку | Неверный путь или файл находится вне директории чарта | Проверьте путь относительно корня чарта. Файлы в `templates/` недоступны через `.Files` |
| `.Capabilities` возвращает пустые значения | Выполняется `helm template` без связи с кластером | Добавьте флаг `--api-versions` или используйте `--dry-run` при `helm install` |

[Синтаксис шаблонов](./syntax.md) · [Функции](./functions.md) · [Именованные шаблоны](./_helpers.md) · [Обзор шаблонизации](../helm_templating.md)
