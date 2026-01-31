# Helm: Зависимости и Library Charts

## Определения

*   **Subchart (Подчарт) или Зависимость (Dependency):** Это Helm-чарт, который устанавливается вместе с родительским чартом. Это основной механизм для переиспользования и композиции чартов в Helm.
*   **Library Chart (Библиотечный чарт):** Это особый тип чарта, который предназначен не для развертывания, а для предоставления переиспользуемых шаблонов и определений (helpers) другим чартам. Он не рендерит никаких ресурсов сам по себе, а служит лишь как "библиотека" для других.

## Основные концепции

### Управление зависимостями

Зависимости чарта определяются в файле `Chart.yaml` в секции `dependencies`.

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
    # Условие для установки: зависимость будет установлена, только если
    # значение postgresql.enabled в родительском values.yaml равно true.
    condition: postgresql.enabled
  - name: redis
    version: "19.0.2"
    repository: "https://charts.bitnami.com/bitnami"
    # Псевдоним: в values.yaml мы будем обращаться к этому чарту как 'cache'
    alias: cache
```

*   **`name`**: Имя чарта-зависимости.
*   **`version`**: Версия чарта.
*   **`repository`**: URL Helm-репозитория, где находится чарт.
*   **`condition`**: Позволяет включать или выключать установку зависимости на основе значения в `values.yaml` родительского чарта.
*   **`alias`**: Позволяет переименовать зависимость внутри родительского чарта. Это полезно, если вы используете один и тот же чарт несколько раз.

Для загрузки или обновления зависимостей используется команда:
```bash
helm dependency update ./my-chart-directory
```
Эта команда скачивает архивы (`.tgz`) зависимостей в директорию `charts/` и создает файл `Chart.lock` для фиксации версий.

### Передача значений (Values) в Subcharts

Существует два способа передать значения из родительского чарта в дочерний:

1.  **Вложенная структура (предпочтительный способ):**
    В `values.yaml` родительского чарта создается секция с именем дочернего чарта (или его псевдонима).

    **`parent-chart/values.yaml`:**
    ```yaml
    # Переопределение значений для чарта postgresql
    postgresql:
      primary:
        persistence:
          size: 2Gi

    # Переопределение значений для redis (используя alias 'cache')
    cache:
      architecture: standalone
    ```

2.  **Глобальные значения (`global`):**
    Значения, определенные в секции `global`, доступны **всем** дочерним чартам. Это удобно для общих параметров, таких как доменное имя или окружение.

    **`parent-chart/values.yaml`:**
    ```yaml
    global:
      env: production
      domain: my-company.com
    ```
    В дочернем чарте к этим значениям можно обратиться через `.Values.global.env`.

## Library Charts

Library-чарт объявляется путем установки поля `type` в `Chart.yaml` в значение `library`.

**`my-library/Chart.yaml`:**
```yaml
apiVersion: v2
name: my-library
description: A library of common Helm templates
type: library
version: 0.1.0
```

*   **Особенность:** Helm не будет пытаться установить такой чарт. Если вы запустите `helm install ./my-library`, вы получите ошибку.
*   **Назначение:** Основное назначение library-чарта — хранить общие, переиспользуемые шаблоны в файле `_helpers.tpl`. Другие чарты могут затем включить его как зависимость и использовать его шаблоны для сокращения дублирования кода (принцип DRY).

### Практический сценарий: "Общий" чарт для микросервисов

В интервью обсуждался сценарий создания "универсального" или "общего" чарта для развертывания множества однотипных микросервисов. Это классический пример использования library-чартов.

**Задача:** Создать общий шаблон для `Deployment`, `Service` и `Ingress`, который можно было бы переиспользовать для каждого микросервиса.

**Решение:**

1.  **Создается Library Chart** (например, `common-chart`) с `type: library`.
2.  В `common-chart/templates/_helpers.tpl` определяются именованные шаблоны для `Deployment`, `Service` и т.д.
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
3.  **Создается Application Chart** для конкретного микросервиса (например, `my-service-a`).
4.  В `my-service-a/Chart.yaml` `common-chart` добавляется как зависимость.
5.  В `my-service-a/templates/` создаются простые файлы, которые вызывают шаблоны из library-чарта.

    **`my-service-a/templates/deployment.yaml`:**
    ```go
    {{- include "common-chart.deployment" . -}}
    ```
6.  В `my-service-a/values.yaml` определяются только уникальные для этого микросервиса значения (имя образа, порты, ресурсы).

Такой подход позволяет централизованно управлять общей структурой развертывания и обновлять ее для всех микросервисов одновременно, изменяя только `common-chart`.
