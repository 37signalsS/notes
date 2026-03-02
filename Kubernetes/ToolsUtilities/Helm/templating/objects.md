# Встроенные объекты Helm

---

## Обзор объектов

| Объект | Назначение | Примеры доступа |
|--------|------------|-----------------|
| `.Values` | Значения из `values.yaml` и флагов `--set` | `.Values.replicaCount`, `.Values.image.repository` |
| `.Release` | Метаданные релиза | `.Release.Name`, `.Release.Namespace`, `.Release.Revision` |
| `.Chart` | Метаданные чарта из `Chart.yaml` | `.Chart.Name`, `.Chart.Version`, `.Chart.AppVersion` |
| `.Capabilities` | Возможности кластера | `.Capabilities.KubeVersion.Version`, `.Capabilities.APIVersions.Has "batch/v1"` |
| `.Files` | Доступ к файлам чарта | `.Files.Get "config.json"`, `.Files.Glob "configs/*.json"` |
| `.Template` | Информация о текущем шаблоне | `.Template.Name`, `.Template.BasePath` |

---

## Детальное описание

### .Release

Метаданные релиза:
- `.Release.Name` — имя релиза
- `.Release.Namespace` — namespace релиза
- `.Release.Revision` — номер ревизии
- `.Release.Service` — сервис, выполняющий релиз (обычно `Helm`)

### .Chart

Метаданные из `Chart.yaml`:
- `.Chart.Name` — имя чарта
- `.Chart.Version` — версия чарта
- `.Chart.AppVersion` — версия приложения

### .Capabilities

Информация о возможностях кластера:
- `.Capabilities.KubeVersion.Version` — версия Kubernetes
- `.Capabilities.APIVersions.Has "resource/version"` — проверка доступности API

### .Files

Доступ к файлам внутри чарта:
- `.Files.Get "path/to/file"` — чтение содержимого файла
- `.Files.Glob "patterns/*"` — поиск файлов по шаблону
- `.Files.AsSecrets` — доступ как к секретам
- `.Files.AsConfig` — доступ как к конфигу

### .Template

Информация о текущем шаблоне:
- `.Template.Name` — имя текущего файла шаблона
- `.Template.BasePath` — базовый путь к директории templates

---

## Дополнительные ссылки

- [Синтаксис шаблонов](./syntax.md) — базовый синтаксис и управляющие конструкции
- [Функции](./functions.md) — ключевые функции для работы с шаблонами
- [ helm_templating](../helm_templating.md) — обзорная страница
