# Встроенные объекты Helm

---

## Определения

**Встроенные объекты** — предопределённые переменные, доступные во всех шаблонах Helm. Они предоставляют доступ к конфигурационным данным пользователя, метаданным релиза, характеристикам чарта, а также к информации о целевом кластере Kubernetes.

**Контекст (Scope)** — область видимости данных, доступная через символ точки (`.`). При использовании управляющих конструкций (циклов, `with`, `include`) контекст может изменяться, смещая «точку» на вложенные элементы.

**Глубокое слияние (Deep Merge)** — механизм объединения словарей (maps) в Helm, при котором вложенные ключи сливаются рекурсивно. В отличие от словарей, списки (lists) замещаются целиком.

**Immutable Release** — концепция, при которой шаблоны не содержат хардкода окружных значений (имена, неймспейсы, образы). Все параметры должны приходить из `values.yaml` или встроенных объектов (`.Release`, `.Chart`).

**Изоляция субчартов (Subchart Isolation)** — принцип, согласно которому дочерний чарт по умолчанию не видит `.Values` родителя, если значения не переданы явно через `global`, вложенную секцию или `import-values`.

---

## Основные концепции

### Обзор доступных объектов

| Объект | Краткое описание |
|--------|------------------|
| `.Values` | Объединённые значения из `values.yaml`, файлов `-f` и CLI-флагов `--set` / `--set-string` / `--set-file` / `--set-json`. |
| `.Release` | Информация о текущем релизе (имя, пространство имён, ревизия, статус операции). |
| `.Chart` | Метаданные чарта из `Chart.yaml` (версия, имя, тип, зависимости, поддерживающие организации). |
| `.Capabilities` | Характеристики кластера Kubernetes и версия клиента Helm. Используется для адаптивных шаблонов. |
| `.Files` | Доступ к статическим файлам в директории чарта (конфиги, скрипты, сертификаты, бинарные данные). |
| `.Template` | Информация о текущем обрабатываемом файле шаблона (имя, базовый путь). |
| `.Subcharts` | Доступ к значениям и данным вложенных чартов (зависимостей). |

### Механизм слияния .Values

Объект `.Values` формируется путём объединения данных из нескольких источников. Helm выполняет **глубокое слияние (deep merge)** для словарей, но **замещает** списки целиком. Более высокий приоритет перезаписывает значения:

1.  **Default values (субчарты):** `values.yaml` внутри зависимостей.
2.  **Default values (родитель):** `values.yaml` корневого чарта.
3.  **User files:** Файлы, переданные через `-f` или `--values`.
4.  **CLI sets:** Параметры, переданные через `--set`, `--set-string`, `--set-file` или `--set-json` (наивысший приоритет).

**Удаление ключей:** Чтобы полностью удалить ключ, определённый на уровне по умолчанию, в файле с более высоким приоритетом присвойте ему значение `null`.

**Валидация:** Начиная с Helm 3, поддерживается файл `values.schema.json` (JSON Schema). Он проверяет типы и обязательность полей **до** начала рендеринга шаблонов, предотвращая ошибки типа "nil pointer evaluating field" на этапе установки.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "properties": {
    "image": {
      "type": "object",
      "required": ["repository"],
      "properties": {
        "tag": { "type": "string", "pattern": "^[a-zA-Z0-9._-]+$" }
      }
    }
  }
}
```

### Глобальный контекст ($) и разница между `.Values` и `$.Values`

В Helm существует два способа обращения к встроенным объектам:

- **`.Values`** — обращение к объекту `Values` в **текущем контексте** (scope). В большинстве случаев, за пределами циклов и блоков `with`, `.Values` и `$.Values` эквивалентны.
- **`$.Values`** — обращение к объекту `Values` в **корневом (глобальном) контексте**. Префикс `$` всегда указывает на верхний уровень шаблона, независимо от текущего положения внутри `range` или `with`.

**Проблема:** внутри блоков `range` и `with` «точка» (`.`) меняет своё значение и перестаёт указывать на корень. В результате `.Values` перестаёт работать, а `$.Values` остаётся валидным.

```go
{{- range .Values.items }}
  # . — текущий элемент списка (например, строка или словарь)
  # .Values — НЕВЕРНО: пытается найти поле Values у текущего элемента
  # $.Values — ВЕРНО: обращение к корневому объекту Values
  name: {{ . }}-{{ $.Release.Name }}
  image: {{ $.Values.image.repository }}:{{ $.Values.image.tag }}
{{- end }}
```

**Типичные ошибки:**
- `can't evaluate field... in type string` — попытка доступа к `.Values` внутри `range`/`with` через точку.
- `nil pointer evaluating field Release` — потеря контекста при вложенных блоках.

**Правило:** внутри `range`, `with` и вложенных `include` всегда используйте `$.Values`, `$.Release`, `$.Chart` для доступа к глобальным объектам.

### Динамическая оценка строк (tpl)

Функция `tpl` позволяет рендерить значения из `values.yaml` так, как если бы они сами были шаблонами Helm. Это полезно для многоуровневой параметризации, когда часть конфигурации должна генерироваться динамически на основе других значений.

```yaml
# values.yaml:
# custom_labels: "app={{ .Release.Name }},env={{ .Values.global.environment }}"

# template.yaml:
metadata:
  labels:
    {{ tpl .Values.custom_labels . | nindent 4 }}
```

---

## Детальное описание объектов

### Объект .Release

Содержит данные о жизненном цикле и состоянии текущего релиза.

*   **.Release.Name**: Имя релиза (например, `my-app`). Должно удовлетворять требованиям DNS-1123 (строчные буквы, цифры, дефисы; начинается и заканчивается буквой/цифрой; макс. 53 символа).
*   **.Release.Namespace**: Целевое пространство имён. Если не указано явно через `--namespace`, используется неймспейс, определённый в контексте Kubernetes (`kubectl config view --minify --output jsonpath='{..namespace}'`). При `helm install` без указания неймспейса Helm использует значение по умолчанию из конфигурационного файла (`~/.kube/config`) или `default`.
*   **.Release.IsInstall**: `true`, если выполняется `helm install`.
*   **.Release.IsUpgrade**: `true`, если выполняется `helm upgrade` или `helm rollback`.
*   **.Release.IsRollback**: `true`, если текущая операция является откатом (rollback).
*   **.Release.IsTest**: `true`, если релиз запущен через `helm test`.
*   **.Release.IsPending**: `true`, если релиз находится в стадии ожидания развёртывания (pending install/upgrade).
*   **.Release.Revision**: Номер ревизии (инкрементируется при каждом обновлении или откате; начинается с 1).
*   **.Release.Service**: Название службы рендеринга (всегда `Helm`).
*   **.Release.Time**: Timestamp создания релиза в формате RFC3339 (например, `2026-08-31T18:00:00Z`).

### Объект .Chart

Предоставляет доступ к полям файла `Chart.yaml`.

*   **.Chart.Name**: Имя чарта.
*   **.Chart.Version**: Версия чарта в формате SemVer (должна совпадать с версией в `Chart.lock`).
*   **.Chart.AppVersion**: Версия приложения (может использоваться как тег образа; не влияет на версионирование релиза).
*   **.Chart.Type**: Тип чарта (`application` или `library`).
*   **.Chart.IsRoot**: Показывает, является ли данный чарт корневым.
*   **.Chart.Maintainers**: Список объектов с полями `name`, `email`, `url`. Отображается в `helm show chart`.
*   **.Chart.Home**: URL домашней страницы проекта.
*   **.Chart.Sources**: Список URL исходного кода.
*   **.Chart.Keywords**: Список строк для поиска в репозиториях.
*   **.Chart.Dependencies**: Список зависимостей, объявленных в `Chart.yaml` (доступен через `.Chart.Dependencies`).

### Объект .Capabilities

Используется для создания адаптивных чартов, работающих в разных версиях Kubernetes.

*   **.Capabilities.KubeVersion**: Объект с версией Kubernetes.
    *   `.Version`: Полная строка версии (например, `v1.30.2`).
    *   `.Major`: Мажорная версия (обычно `1`).
    *   `.Minor`: Минорная версия (например, `30`).
    *   `.GitVersion`: Полная строка версии, включая git-метаданные (например, `v1.30.2+k3s1`).
*   **.Capabilities.APIVersions.Has**: Метод проверки доступности API-ресурса. Принимает строку формата `<group>/<version>/<resource>`.
*   **.Capabilities.HelmVersion**: Объект с версией клиента Helm.
    *   `.Version`: Полная строка версии (например, `v4.0.0`).
    *   `.SemVer`: Объект для семантического сравнения (`Major`, `Minor`, `Patch`).

**Важное ограничение:** При `helm template` (оффлайн-режим) Helm не подключается к кластеру и использует дефолтные значения `.Capabilities`. Для разработки адаптивных шаблонов используйте флаги `--kube-version` и `--api-versions`.

### Объект .Files

Позволяет считывать содержимое файлов из директории чарта.

*   **.Files.Get**: Чтение файла как строки (`{{ .Files.Get "config.json" }}`).
*   **.Files.GetBytes**: Чтение файла как массива байтов (для бинарных данных).
*   **.Files.Glob**: Поиск файлов по glob-маске (`{{ range .Files.Glob "files/*.txt" }}`).
*   **.Files.Lines**: Построчное чтение файла для итерации (`{{ range .Files.Lines "files/ips.txt" }}`).
*   **.Files.AsConfig**: Форматирует результат `Glob` для вставки в `ConfigMap`.
*   **.Files.AsSecrets**: Форматирует результат `Glob` для вставки в `Secret` (Base64).
*   **.Files.Charset**: Определяет кодировку файлов (по умолчанию UTF-8).
*   **.Files.TrimPrefix**: Удаляет префикс из пути файла в результатах `Glob`.
*   **.Files.TrimSuffix**: Удаляет суффикс из имени файла в результатах `Glob`.

**Ограничения:**
*   Не видит файлы в `templates/`.
*   Не видит файлы, указанные в `.helmignore`.
*   Максимальный размер файла — 1 МБ (ограничение etcd/Kubernetes на размер ConfigMap и Secret).
*   Пути с `../` для выхода за пределы чарта запрещены.

### Объект .Template

Информация о самом шаблоне.

*   **.Template.Name**: Путь к текущему файлу шаблона относительно корня чарта (например, `mychart/templates/deployment.yaml`).
*   **.Template.BasePath**: Путь к директории шаблонов (обычно `mychart/templates`).

### Объект .Subcharts

Предоставляет доступ к данным и значениям вложенных чартов (зависимостей), объявленных в `Chart.yaml`.

**Важное правило изоляции:** Дочерний чарт **не видит** `.Values` родительского чарта, если:
*   значения не переданы через секцию с именем зависимости (или `alias`);
*   значения не объявлены в `global`;
*   не настроен `import-values`.

**Доступ к значениям субчарта из родителя:**

```yaml
# templates/deployment.yaml (родительский чарт)
spec:
  containers:
    - name: app
      image: "{{ .Values.postgresql.image.repository }}:{{ .Values.postgresql.image.tag }}"
```

**Доступ к родительским значениям из субчарта:**

```yaml
# charts/postgresql/templates/statefulset.yaml (субчарт)
spec:
  serviceName: "{{ .Release.Name }}-headless"
  # .Chart внутри субчарта ссылается на метаданные САМГО субчарта, а не родителя
```

**Чтение метаданных зависимостей:**

```go
{{- range .Chart.Dependencies }}
  {{ .Name }} {{ .Version }} {{ .Repository }}
{{- end }}
```

**Механизмы управления зависимостями:**
*   **condition:** Булев флаг в `values.yaml` (например, `postgresql.enabled`). Если `false`, субчарт не устанавливается.
*   **tags:** Группировка зависимостей. Активация через `tags.database: true`.
*   **alias:** Псевдоним для одного и того же чарта, устанавливаемого несколько раз с разными конфигурациями.

---

## Практические сценарии

### Динамический выбор API-версии

Обеспечение совместимости чарта с кластерами разных поколений.

```yaml
apiVersion: {{ if .Capabilities.APIVersions.Has "policy/v1/PodDisruptionBudget" -}}
policy/v1
{{- else -}}
policy/v1beta1
{{- end }}
kind: PodDisruptionBudget
```

### Массовое добавление конфигурационных файлов

Автоматизация наполнения ConfigMap из папки.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .Release.Name }}-configs
data:
{{ (.Files.Glob "configs/**").AsConfig | indent 2 }}
```

### Использование .Chart.AppVersion для тегирования

Синхронизация версии манифеста с версией приложения.

```yaml
spec:
  containers:
  - name: app
    image: "myreg.com/app:{{ .Values.image.tag | default .Chart.AppVersion }}"
```

### Многослойная параметризация окружений

Использование нескольких `values`-файлов для dev/staging/prod без изменения шаблонов.

```bash
# Базовый values.yaml + переопределения для production
helm upgrade --install my-app ./chart \
  -f values.yaml \
  -f values-production.yaml \
  --namespace prod
```

В `values-production.yaml` можно переопределять любые поля, включая списки. Помните: списки замещаются целиком, поэтому для добавления элементов используйте полное определение списка.

### Инъекция секретов через .Files.AsSecrets

Автоматическое создание Secret из файлов с сертификатами или ключами.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: {{ .Release.Name }}-tls
type: kubernetes.io/tls
data:
  tls.crt: {{ .Files.Get "certs/tls.crt" | b64enc }}
  tls.key: {{ .Files.Get "certs/tls.key" | b64enc }}
```

Для массового импорта:
```yaml
data:
{{ (.Files.Glob "secrets/*.key").AsSecrets | nindent 2 }}
```

### Условная активация субчартов через condition и tags

Управление зависимостями без изменения `Chart.yaml`.

```yaml
# values.yaml
postgresql:
  enabled: true
  auth:
    username: app
    password: "{{ .Values.global.dbPassword }}"

tags:
  database: true   # активирует все чарты с тегом 'database'
  cache: false     # отключает redis
```

### Импорт значений из субчарта (import-values)

Когда родительскому чарту нужны параметры дочернего для построения шаблонов.

```yaml
# Chart.yaml
dependencies:
  - name: backend
    import-values:
      - data: backend.servicePort  # импортирует .backend.servicePort в корень родителя
```

### Имена релизов для автоматизации

Ограничение в 53 символа требует аккуратной работы с длинными именами окружений.

```yaml
# values.yaml
fullnameOverride: "{{ .Values.global.environment }}-{{ .Chart.Name }}"

# Или в шаблоне:
metadata:
  name: {{ .Values.global.environment }}-{{ .Chart.Name | trunc 40 | trimSuffix "-" }}
```

### Доступ к метаданным чарта для Service Mesh

Использование `.Chart` для автоматической маркировки ресурсов, что упрощает работу Istio или Linkerd.

```yaml
metadata:
  labels:
    app.kubernetes.io/name: {{ .Chart.Name }}
    app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
    app.kubernetes.io/managed-by: {{ .Release.Service }}
    app.kubernetes.io/instance: {{ .Release.Name }}
```

### Валидация через values.schema.json

Защита от неверных типов на этапе CI.

```bash
# Линт чарта с валидацией схемы
helm lint ./my-chart --strict
```

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "required": ["image"],
  "properties": {
    "image": {
      "type": "object",
      "required": ["repository", "tag"],
      "properties": {
        "tag": { "type": "string" }
      }
    },
    "replicaCount": {
      "type": "integer",
      "minimum": 1,
      "maximum": 20
    }
  }
}
```

---

## Лучшие практики

*   **Всегда используйте `$` в циклах:** Обращение к `.Values` внутри `range` без `$` — самая частая причина ошибок рендеринга.
*   **Глобальные значения (`global`):** Используйте раздел `.Values.global` для передачи данных между родительским и дочерними чартами (например, имя окружения, registry, домены).
*   **Инкапсуляция субчартов:** Помните, что субчарты не видят `.Values` родителя, если только они не переданы через `global`, вложенную секцию или `import-values`.
*   **Валидация схем:** Используйте `values.schema.json` для строгой типизации. Это предотвращает падение рендеринга в production из-за опечаток в `values.yaml`.
*   **Кавычки для строк:** Обертывайте `.Release.Name` и `.Chart.Name` в `| quote`, если они используются в качестве тегов образов или меток, чтобы избежать проблем с парсингом YAML.
*   **Ограничение размера .Files:** Помните о лимите в 1 МБ для ConfigMap/Secret. Для файлов большего размера используйте PersistentVolume или выносите данные в Docker-образ.

---

## Устранение неисправностей

| Ошибка | Вероятная причина | Решение |
|--------|-------------------|---------|
| `nil pointer evaluating field Release` | Потеря контекста внутри `range` или `with` | Используйте `$.Release` вместо `.Release` |
| `.Files.Get` возвращает пустую строку | Файл в `templates/` или ошибка в пути | Переместите файл в корень чарта или проверьте `.helmignore` |
| Неверная версия API в манифесте | Использование `helm template` без эмуляции capabilities | Добавьте `--api-versions` или `--kube-version` |
| `.Values` не обновляются | Конфликт приоритетов `--set` и файлов `-f` | Проверьте порядок аргументов в CLI (последний имеет приоритет) |
| `file too large` для ConfigMap/Secret | Размер `.Files.Glob` превысил 1 МБ | Разбейте на несколько ConfigMap или используйте PV |
| `invalid character` при чтении .Files | Файл не в UTF-8 | Пересохраните файл в UTF-8 без BOM |
| `subchart values not applied` | Неверное имя секции или alias | Проверьте имя зависимости в `Chart.yaml` и соответствующую секцию в `values.yaml` |
| `condition не работает` | Отсутствует поле `enabled` или неверный путь | Убедитесь, что `condition: name.enabled` соответствует пути в `values.yaml` |
| `import-values не импортирует` | Несовпадение имени секции | Проверьте точное имя ключа в дочернем `values.yaml` |
| `Capabilities.Has возвращает false` в `helm template` | Оффлайн-режим использует дефолты | Добавьте `--api-versions "networking.k8s.io/v1/Ingress"` |
| `schema validation failed` | Несоответствие типов данных | Проверьте `values.yaml` на соответствие `values.schema.json` |
| `release name exceeds 53 chars` | Слишком длинное имя из комбинации env + chart | Используйте `nameOverride` или `fullnameOverride` с `trunc` |

### См. также
* [Обзор шаблонизации Helm](../helm_templating.md) — фундаментальные основы и архитектура.
* [Зависимости и библиотечные чарты](../helm_dependencies_and_library_charts.md) — механизмы `condition`, `tags`, `alias` и `import-values`.
* [Проверка версий API и возможностей](./scenarios/api_versions.md) — детальное использование `.Capabilities`.
