# Логирование в Rancher

## Определения

**Rancher Logging** — встроенное решение Rancher для централизованного сбора, хранения и анализа логов, основанное на Fluentd и Logging Operator.

## Базовые концепции

### Основные концепции логирования

*   **12 Factor App: Логи как поток событий**: Современные приложения должны выводить логи на стандартные потоки (`stdout`/`stderr`). Обработка и хранение логов делегируется инфраструктуре.
*   **Хранение логов на узлах**: В Kubernetes логи контейнеров физически сохраняются на узлах в директории `/var/log/containers/`.
*   **Эфемерность логов**: Логи, хранящиеся на узлах, эфемерны: при удалении пода его логи также удаляются.

### Архитектура логирования Rancher (Logging Operator)

Rancher использует специализированный `Logging Operator` (основанный на проекте Banzai Cloud):

*   `Logging Operator` развертывает `Fluent Bit` на каждом узле кластера. `Fluent Bit` собирает *все* логи контейнеров с узла и пересылает их в `Fluentd`.
*   `Fluentd` выступает в роли маршрутизатора логов: фильтрует, обогащает логи и отправляет их в различные системы хранения (Elasticsearch, OpenSearch, Kafka и т.д.).

**Критика архитектуры**: Подход, при котором `Fluent Bit` собирает *все* логи и пересылает их в централизованный `Fluentd`, может привести к значительному сетевому трафику и нагрузке.

### Концепции Logging Operator: Output и Flow

Система логирования Rancher использует Custom Resources для декларативной настройки:

*   **`Output` и `ClusterOutput` (Куда отправлять логи)**:
    *   Определяют место назначения для собранных логов (Elasticsearch, OpenSearch, Kafka, S3, файл).
    *   **`Output`**: Привязан к конкретному `namespace`.
    *   **`ClusterOutput`**: Кластерный ресурс. Может использоваться из любого `namespace`.

*   **`Flow` и `ClusterFlow` (Какие логи отбирать и как обрабатывать)**:
    *   Определяют правила отбора (matching), фильтрации и обогащения логов.
    *   **`Match`**: Секция для выбора логов на основе Pod Labels, Node Names, Container Names.
    *   **`Filters`**: Секция для модификации или обогащения логов.
        *   **`tag_normalizer`**: Для динамического формирования тегов логов.
        *   **`kube_events_timestamp`**: Для генерации поля `mtime` с временем события.
    *   **`Output`**: Секция, указывающая на `Output` или `ClusterOutput`.
    *   **`Flow`**: Привязан к конкретному `namespace`.
    *   **`ClusterFlow`**: Кластерный ресурс.

## Практические сценарии

### Включение логирования через Web UI

#### 1. Включение логирования для кластера или проекта

1.  **Создайте отдельный Rancher Project для логирования**: Рекомендуется.
2.  Перейдите в **Cluster Dashboard** -> **Tools** -> **Logging**.
3.  Нажмите **Install**. Всегда выбирайте опцию "Customize Helm Options for install".
4.  **Конфигурация `systemd` логов**: Укажите правильный путь к журналам `systemd` (например, `/run/log/journal` или `/var/log/journal`).
5.  **Настройка `Tolerations` для Control Plane узлов**:
    *   По умолчанию, узлы Control Plane имеют `taint` (`node-role.kubernetes.io/master:NoSchedule`).
    *   Система логирования по умолчанию не будет развернута на таких узлах.
    *   **Решение**: В `values.yaml` Helm-чарта необходимо добавить соответствующую `toleration`:

    ```yaml
    fluentbit:
      tolerations:
      - effect: NoSchedule
        key: node-role.kubernetes.io/master
        operator: Exists
    ```

6.  Выберите **Destination** (цель отправки логов):
    *   **Elasticsearch**
    *   **Splunk**
    *   **Kafka**
    *   **Syslog**
    *   **Fluentd**

#### 2. Конфигурация для Elasticsearch (пример)

*   **Endpoint**: Полный URL Elasticsearch (например, `http://<elasticsearch-ip>:9200`).
*   **Authentication**: Учетные данные пользователя Elasticsearch.
*   **Index Pattern**: Формат имени индекса (например, `mycluster-YYYY.MM.DD`).
    *   **Рекомендация**: Всегда используйте ежедневные индексы.
*   **Include System Log**: Включение/отключение сбора логов системных компонентов Kubernetes.
*   **Enable JSON Parsing**: Попытка парсить логи в формате JSON.

#### 3. Расширенная конфигурация Fluentd

Rancher предоставляет возможность тонкой настройки Fluentd через опцию **"Edit As File"**.

После настройки логирования в Kibana можно создавать [индекс-паттерны](../../MonitoringLogging/EFK/kibana_guide.md#1-создание-индекс-паттерна-для-логов-kubernetes).

#### 4. Создание ClusterOutput для OpenSearch

1.  **Подготовка Secret с учетными данными**: Создайте Kubernetes `Secret` в `namespace cattle-logging-system`.

    ```yaml
    apiVersion: v1
    kind: Secret
    metadata:
      name: opensearch-auth
      namespace: cattle-logging-system
    type: Opaque
    stringData:
      username: admin
      password: your_opensearch_password
    ```

2.  **Создание `ClusterOutput`**:
    *   Выберите тип "Elasticsearch" (даже если используется OpenSearch).
    *   Настройте Endpoint, Index Name, Authentication.
    *   **Ручное редактирование YAML**: Измените `type: elasticsearch` на `type: opensearch`, добавьте `suppress_type_name_true: true` и настройте буферизацию.

#### 5. Создание Flow для сбора логов Control Plane

1.  **Создание `Flow`**:
    *   Выберите `namespace` (например, `kube-system`).
    *   В секции **Outputs** выберите созданный `ClusterOutput`.
    *   В секции **Filters** добавьте `Tag Normalizer` и `Kube Events Timestamp`.

### Важный нюанс логирования Fluentd

По умолчанию логи самого `Fluentd` не выводятся в `stdout/stderr` контейнера, а сохраняются внутри него (например, `/var/log/fluentd/out`). Для отладки может потребоваться `kubectl exec` в контейнер `fluentd`.

## Ограничения RBAC

*   **`ClusterFlow` и `ClusterOutput`**: Могут быть созданы только администраторами Rancher.
*   **`Flow` и `Output` (привязанные к `namespace`)**:
    *   `Project Owner` может создавать и изменять `Flow` и `Output`.
    *   `Project Member` **не может** создавать `Flow` и `Output`.

**Критическое замечание**: Это ограничение делает функциональность логирования Rancher для пользовательских приложений малопригодной для самостоятельного использования разработчиками с ролью `Project Member`.

## Дополнительная информация

См. также: [rancher_overview](./rancher_overview.md) — обзор платформы Rancher.
