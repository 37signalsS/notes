# Зависимости и библиотечные чарты в Helm

Механизмы композиции чартов через зависимости (subcharts) и переиспользования логики через библиотечные чарты (library charts) в среде **v4 (стандарт 2026 года)**.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Subchart (Зависимость)** | Вложенный чарт, устанавливаемый вместе с родительским. Основной механизм композиции ресурсов. См. [Структура Helm-чарта](./helm_chart_structure.md). |
| **Library Chart** | Чарт типа `library` для предоставления общих шаблонов другим чартам. Не рендерит ресурсы самостоятельно. |
| **Chart.lock** | Файл фиксации точных версий зависимостей. Должен находиться под контролем версий (Git). См. [Управление версиями релизов](./helm_release_versioning.md). |
| **condition / tags** | Механизмы динамического включения или отключения зависимостей через файл `values.yaml`. |
| **alias** | Псевдоним зависимости, позволяющий использовать один и тот же чарт несколько раз с разными настройками. |
| **import-values** | Механизм экспорта значений из дочернего чарта в область видимости родительского. |

---

## Основные концепции

### Управление зависимостями

В Helm v4 зависимости описываются исключительно в `Chart.yaml` в секции `dependencies`. Использование устаревшего файла `requirements.yaml` запрещено.

```yaml
# Chart.yaml
apiVersion: v2
name: my-application
description: Промышленный чарт с зависимостями
version: 1.0.0

dependencies:
  - name: postgresql
    version: "15.x.x"
    repository: "oci://registry.example.com/charts"
    # Зависимость установится, только если postgresql.enabled = true
    condition: postgresql.enabled
  - name: redis
    version: "19.0.2"
    repository: "https://charts.bitnami.com/bitnami"
    # Псевдоним: в values.yaml обращаемся как 'cache'
    alias: cache
    tags:
      - database
```

| Поле | Описание |
| :--- | :--- |
| **name** | Имя чарта-зависимости. |
| **version** | Версия чарта (поддерживаются диапазоны SemVer). |
| **repository** | URL Helm-репозитория или OCI-ссылка (`oci://...`). |
| **condition** | Путь к булеву флагу в `values.yaml` для управления установкой. |
| **tags** | Группировка зависимостей. Если в родительском `values.yaml` указано `tags.database: true`, все чарты с этим тегом будут установлены. |
| **alias** | Переименование зависимости внутри родительского чарта для устранения конфликтов имен. |
| **import-values** | Описание полей, которые будут импортированы из дочернего чарта в родительский. |

Для загрузки и фиксации зависимостей:

```bash
# Обновление зависимостей и создание Chart.lock
helm dependency update ./my-chart

# Сборка зависимостей строго по Chart.lock (рекомендуется для CI/CD)
helm dependency build ./my-chart
```

### Передача значений (Values) в дочерние чарты

Существует три основных способа управления значениями в иерархии чартов:

**1. Вложенная структура (Nested Values):**
Родительский чарт переопределяет значения дочернего через секцию, имя которой совпадает с именем зависимости (или ее `alias`). Это наиболее частый и безопасный способ.

```yaml
# parent-chart/values.yaml

# Переопределение для postgresql
postgresql:
  primary:
    persistence:
      size: 10Gi

# Переопределение для redis (через alias 'cache')
cache:
  architecture: standalone
```

**2. Глобальные значения (Global Values):**
Значения, помещенные в секцию `global`, доступны всем дочерним чартам любого уровня вложенности через объект `.Values.global`. Это стандарт для общих параметров инфраструктуры.

```yaml
# parent-chart/values.yaml
global:
  env: production
  domain: company.internal
  imageRegistry: registry.company.com
```

**3. Импорт значений (import-values):**
Позволяет "поднимать" значения из дочернего чарта в родительский. Это полезно, когда родительскому чарту нужно знать параметры своих компонентов для настройки логики шаблонов.

```yaml
# Chart.yaml родителя
dependencies:
  - name: backend-service
    import-values:
      - data  # Импортирует секцию 'data' из дочернего values.yaml в корень родительского
```

### Использование библиотечных чартов (Library Charts)

Library-чарт объявляется через `type: library` в `Chart.yaml`.

- **Особенность:** Helm не устанавливает библиотечный чарт как самостоятельный релиз.
- **Назначение:** Служит контейнером для переиспользуемых именованных шаблонов (Named Templates) в файлах `_helpers.tpl`. Другие чарты подключают его как зависимость для соблюдения принципа DRY.

---

## Практические сценарии

### Создание общей библиотеки для микросервисов

Для исключения дублирования кода в сотнях микросервисов создается единая библиотека шаблонов.

**1. В библиотечном чарте (`common-lib`):**
Создайте файл `templates/_helpers.tpl` с общей логикой деплоймента.

```go
{{/* common-lib/templates/_helpers.tpl */}}
{{- define "common.deployment" -}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "common.fullname" . }}
  labels: {{ include "common.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount | default 1 }}
  selector:
    matchLabels: {{ include "common.selectorLabels" . | nindent 6 }}
  template:
    ...
{{- end -}}
```

**2. В чарте приложения-потребителя:**
Добавьте библиотеку в зависимости и вызовите шаблон.

```yaml
# my-app/Chart.yaml
dependencies:
  - name: common-lib
    version: "1.x.x"
    repository: "oci://registry.company.com/charts"
```

```go
# my-app/templates/deployment.yaml
{{- include "common.deployment" . -}}
```

### Масштабирование библиотечных чартов (100+ сервисов)

При инфраструктурах с большим количеством сервисов (100+) библиотечные чарты становятся критически важным инструментом стандартизации. Следуйте принципам:

1.  **Один чарт на технологический стек:** Создавайте отдельные библиотечные чарты для Java, PHP, Python, Node.js. Общие шаблоны (метки, селекторы, NetworkPolicy) выносите в общий `common-lib`, а_stack-specific_ шаблоны (JVM-опции, конфигурация веб-сервера, graceful shutdown) — в `java-lib`, `php-lib` и т.д.
2.  **Четкий контракт с разработкой:** Документируйте, какие переменные (`Values`) ожидает каждый чарт. Например, `java-lib` требует `jvm.memory`, `php-lib` — `php.fpm.max_children`.
3.  **Версионирование по стеку:** Java-сервисы обновляют версию `java-lib` независимо от `php-lib`. Это позволяет поэтапно внедрять изменения (например, обновление базового образа JVM) без риска сломать PHP-сервисы.
4.  **CI-автоматизация обновлений:** Настройте пайплайн, который сканирует репозитории и открывает MR при появлении новой версии библиотечного чарта.

```yaml
# java-service/Chart.yaml
dependencies:
  - name: common-lib
    version: "2.3.0"
    repository: "oci://registry.company.com/charts"
  - name: java-lib
    version: "3.1.0"
    repository: "oci://registry.company.com/charts"
```

**Проблема «универсального» library chart:**
Если library chart пытается охватить все стеки сразу, он становится «божественным объектом» с hundreds of condition-блоков и нечитаемым кодом. Признак проблемы: разработчики не могут понять, какие переменные им нужно задать. Решение — разбиение по стекам.

### Изоляция сервисов: один namespace — один сервис

Паттерн «один сервис — один namespace» упрощает администрирование и реформацию кластера:

- **Сетевые политики:** Каждый namespace имеет собственную NetworkPolicy, разрешающую трафик только от инфраструктурных компонентов (Prometheus, Argo CD, Ingress Controller).
- **Resource Quota:** Ограничения на CPU/memory применяются per-namespace, что предотвращает «соседство» шумного сервиса с критичным.
- **RBAC:** ServiceAccount для сервиса существует только в его namespace, что снижает радиус поражения при компрометации.
- **Версионирование Helm:** Каждый релиз чарта существует в собственном namespace, что упрощает канареечные выкатки и откат.

```yaml
# values.yaml для приложения
namespace:
  create: true
  name: auth-service

networkPolicy:
  enabled: true
  allowIngress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
  allowEgress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: database
      ports:
        - protocol: TCP
          port: 5432
```

**Когда НЕ использовать:**
- Для микросервисов с интенсивным межсервисным взаимодействием (десятки RPS между собой) избыточное количество namespace может усложнить сетевые политики. В таком случае используйте один namespace на bounded context (домен).

### Иерархия приоритетов значений

При объединении значений Helm следует строгому приоритету (от низшего к высшему):
1.  `values.yaml` дочернего чарта (Default).
2.  `values.yaml` родительского чарта (Override).
3.  Значения, переданные через `import-values` (Export).
4.  Внешние файлы значений (`-f` / `--values`).
5.  Индивидуальные значения, переданные через `--set`.

---

## Дополнительная информация

### Важные нюансы
- **Shared Chart против Library Chart:**
    *   **Library Chart (`type: library`)** — не устанавливается, предоставляет только шаблоны для `include`.
    *   **Shared Chart** — полноценный чарт-движок в OCI-реестре, который устанавливается с разными `values.yaml` для множества сервисов. Подробнее: [Практические сценарии: shared-чарт](./helm_chart_practical_scenarios.md).
- **Chart.lock:** Всегда коммитьте этот файл в репозиторий. Он гарантирует, что все участники команды и CI-пайплайны используют идентичные версии зависимостей, предотвращая "дрейф" инфраструктуры.

### См. также
- [Структура Helm-чарта](./helm_chart_structure.md) — организация файлов и папка `charts/`.
- [Управление версиями релизов](./helm_release_versioning.md) — SemVer и жизненный цикл пакетов.
- [Практические сценарии Helm-чартов](./helm_chart_practical_scenarios.md) — Umbrella Charts и Shared Charts.
- [Встроенные объекты Helm](./templating/objects.md) — детальное описание `.Values` и глобальных объектов.
