# Зависимости и Library Charts в Helm

Механизмы композиции чартов через зависимости (subcharts) и переиспользования шаблонов через library charts.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Subchart (Зависимость)** | Helm-чарт, устанавливаемый вместе с родительским чартом. Основной механизм композиции. См. [Структура Helm-чарта](./helm_chart_structure.md) для общей организации файлов |
| **Library Chart** | Чарт типа `library` для предоставления переиспользуемых шаблонов другим чартам. Не рендерит ресурсы самостоятельно |
| **Chart.lock** | Файл с зафиксированными версиями зависимостей. См. [Управление версиями релизов](./helm_release_versioning.md) |
| **condition** | Поле в `dependencies`, позволяющее включать/отключать установку зависимости через `values.yaml` |
| **alias** | Псевдоним зависимости для использования одного чарта несколько раз |

---

## Основные концепции

### Управление зависимостями

Зависимости определяются в `Chart.yaml` в секции `dependencies`.

```yaml
# Chart.yaml
apiVersion: v2
name: my-application
description: A Helm chart for my web application
version: 0.1.0

dependencies:
  - name: postgresql
    version: "14.2.4"
    repository: "https://charts.bitnami.com/bitnami"
    # Зависимость установится, только если postgresql.enabled = true
    condition: postgresql.enabled
  - name: redis
    version: "19.0.2"
    repository: "https://charts.bitnami.com/bitnami"
    # Псевдоним: в values.yaml обращаемся как 'cache'
    alias: cache
```

| Поле | Описание |
|------|----------|
| `name` | Имя чарта-зависимости |
| `version` | Версия чарта |
| `repository` | URL Helm-репозитория |
| `condition` | Включение/отключение зависимости по значению из `values.yaml` |
| `alias` | Переименование зависимости внутри родительского чарта |

Для загрузки/обновления зависимостей:

```bash
helm dependency update ./my-chart-directory
```

Команда скачивает архивы (`.tgz`) в `charts/` и создаёт `Chart.lock` для фиксации версий.

### Передача значений (Values) в Subcharts

Два способа передачи значений из родительского чарта в дочерний:

**1. Вложенная структура (предпочтительный):**

В `values.yaml` родительского чарта создаётся секция с именем дочернего чарта (или псевдонима).

```yaml
# parent-chart/values.yaml

# Переопределение для postgresql
postgresql:
  primary:
    persistence:
      size: 2Gi

# Переопределение для redis (через alias 'cache')
cache:
  architecture: standalone
```

**2. Глобальные значения (`global`):**

Значения в секции `global` доступны всем дочерним чартам через `.Values.global`.

```yaml
# parent-chart/values.yaml
global:
  env: production
  domain: my-company.com
```

### Использование Library Charts

Library-чарт объявляется через `type: library` в `Chart.yaml`.

```yaml
# my-library/Chart.yaml
apiVersion: v2
name: my-library
description: A library of common Helm templates
type: library
version: 0.1.0
```

- **Особенность:** Helm не устанавливает library-чарт. `helm install ./my-library` вернёт ошибку.
- **Назначение:** Хранение переиспользуемых шаблонов в `_helpers.tpl`. Другие чарты подключают его как зависимость и используют шаблоны для сокращения дублирования кода (DRY).

---

## Практические сценарии

### Создание общего чарта для микросервисов

Классический пример library-чартов — единый шаблон для множества однотипных микросервисов.

**Задача:** Создать общий шаблон для `Deployment`, `Service` и `Ingress`, переиспользуемый для каждого микросервиса.

**Решение:**

1. Создать Library Chart (`common-chart`) с `type: library`.
2. В `common-chart/templates/_helpers.tpl` определить именованные шаблоны:

    ```go
    {{/* templates/_helpers.tpl */}}
    {{- define "common-chart.deployment" -}}
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: {{ .Release.Name }}
    spec:
      replicas: {{ .Values.replicaCount | default 1 }}
      ...
    {{- end -}}
    ```

3. Создать Application Chart для конкретного микросервиса (`my-service-a`).
4. В `my-service-a/Chart.yaml` добавить `common-chart` как зависимость.
5. В `my-service-a/templates/deployment.yaml` вызвать шаблон из library-чарта:

    ```go
    {{- include "common-chart.deployment" . -}}
    ```

6. В `my-service-a/values.yaml` определить только уникальные значения микросервиса (образ, порты, ресурсы).

Такой подход позволяет централизованно управлять общей структурой развёртывания и обновлять её для всех микросервисов одновременно через изменения в `common-chart`.

**Важно:** library chart (`type: library`) не устанавливается — он только предоставляет шаблоны для `include`. Если нужно развернуть один и тот же чарт для сотни сервисов с разными values, используется **shared-чарт** (обычный, с `templates/`) в OCI-регистри. Подробнее: [Практические сценарии: shared-чарт для 100 микросервисов](./helm_chart_practical_scenarios.md).

---

## См. также

- [Структура Helm-чарта](./helm_chart_structure.md)
- [Управление версиями релизов](./helm_release_versioning.md)
- [Практические сценарии Helm-чартов](./helm_chart_practical_scenarios.md)
