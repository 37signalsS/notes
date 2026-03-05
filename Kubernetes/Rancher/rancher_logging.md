# Логирование в Rancher

## Определения

**Rancher Logging** — встроенное решение Rancher для централизованного сбора, хранения и анализа логов, основанное на Fluentd и Logging Operator.

## Базовые концепции

### Основные концепции логирования

* **12 Factor App: Логи как поток событий**: Современные приложения должны выводить логи на стандартные потоки (`stdout`/`stderr`). Обработка и хранение логов делегируется инфраструктуре.
* **Хранение логов на узлах**: В Kubernetes логи контейнеров физически сохраняются на узлах в директории `/var/log/containers/`.
* **Эфемерность логов**: Логи, хранящиеся на узлах, эфемерны: при удалении пода его логи также удаляются.

### Архитектура логирования Rancher (Logging Operator)

Rancher использует специализированный `Logging Operator` (основанный на проекте Banzai Cloud):

* `Logging Operator` развертывает `Fluent Bit` на каждом узле кластера. `Fluent Bit` собирает *все* логи контейнеров с узла и пересылает их в `Fluentd`.
* `Fluentd` выступает в роли маршрутизатора логов: фильтрует, обогащает логи и отправляет их в различные системы хранения (Elasticsearch, OpenSearch, Kafka и т.д.).

**Критика архитектуры**: Подход, при котором `Fluent Bit` собирает *все* логи и пересылает их в централизованный `Fluentd`, может привести к значительному сетевому трафику и нагрузке.

### Концепции Logging Operator: Output и Flow

Система логирования Rancher использует Custom Resources для декларативной настройки:

* **`Output` и `ClusterOutput` (Куда отправлять логи)**:
  * Определяют место назначения для собранных логов (Elasticsearch, OpenSearch, Kafka, S3, файл).
  * **`Output`**: Привязан к конкретному `namespace`.
  * **`ClusterOutput`**: Кластерный ресурс. Может использоваться из любого `namespace`.

* **`Flow` и `ClusterFlow` (Какие логи отбирать и как обрабатывать)**:
  * Определяют правила отбора (matching), фильтрации и обогащения логов.
  * **`Match`**: Секция для выбора логов на основе Pod Labels, Node Names, Container Names.
  * **`Filters`**: Секция для модификации или обогащения логов.
    * **`tag_normalizer`**: Для динамического формирования тегов логов.
    * **`kube_events_timestamp`**: Для генерации поля `mtime` с временем события.
  * **`Output`**: Секция, указывающая на `Output` или `ClusterOutput`.
  * **`Flow`**: Привязан к конкретному `namespace`.
  * **`ClusterFlow`**: Кластерный ресурс.

## Практические сценарии

### Включение логирования через Web UI

#### 1. Включение логирования для кластера или проекта

1. **Создайте отдельный Rancher Project для логирования**: Рекомендуется.
2. Перейдите в **Cluster Dashboard** -> **Tools** -> **Logging**.
3. Нажмите **Install**. Всегда выбирайте опцию "Customize Helm Options for install".
4. **Конфигурация `systemd` логов**: Укажите правильный путь к журналам `systemd` (например, `/run/log/journal` или `/var/log/journal`).
5. **Настройка `Tolerations` для Control Plane узлов**:
    * По умолчанию, узлы Control Plane имеют `taint` (`node-role.kubernetes.io/master:NoSchedule` или `node-role.kubernetes.io/control-plane:NoSchedule`).
    * Система логирования по умолчанию не будет развернута на таких узлах.
    * **Решение**: В `values.yaml` Helm-чарта необходимо добавить соответствующую `toleration`:

    ```yaml
    fluentbit:
      tolerations:
      - effect: NoSchedule
        key: node-role.kubernetes.io/master
        operator: Exists
      - effect: NoSchedule
        key: node-role.kubernetes.io/control-plane
        operator: Exists
    ```

    **Важно:** Проверьте актуальные taints на ваших control plane узлах через `kubectl describe node <node-name>`.

6. Выберите **Destination** (цель отправки логов):
    * **Elasticsearch**
    * **Splunk**
    * **Kafka**
    * **Syslog**
    * **Fluentd**

#### 2. Конфигурация для Elasticsearch (пример)

* **Endpoint**: Полный URL Elasticsearch (например, `http://<elasticsearch-ip>:9200`).
* **Authentication**: Учетные данные пользователя Elasticsearch.
* **Index Pattern**: Формат имени индекса (например, `mycluster-YYYY.MM.DD`).
  * **Рекомендация**: Всегда используйте ежедневные индексы.
* **Include System Log**: Включение/отключение сбора логов системных компонентов Kubernetes.
* **Enable JSON Parsing**: Попытка парсить логи в формате JSON.

#### 3. Расширенная конфигурация Fluentd

Rancher предоставляет возможность тонкой настройки Fluentd через опцию **"Edit As File"**.

После настройки логирования в Kibana можно создавать [индекс-паттерны](../../MonitoringLogging/EFK/kibana_guide.md#1-создание-индекс-паттерна-для-логов-kubernetes).

#### 4. Создание ClusterOutput для OpenSearch

1. **Подготовка Secret с учетными данными**: Создайте Kubernetes `Secret` в `namespace cattle-logging-system`.

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

2. **Создание `ClusterOutput`**:
    * Выберите тип "Elasticsearch" (даже если используется OpenSearch).
    * Настройте Endpoint, Index Name, Authentication.
    * **Ручное редактирование YAML**: Измените `type: elasticsearch` на `type: opensearch`, добавьте `suppress_type_name: true` и настройку буферизации.

    **Пример конфигурации ClusterOutput для OpenSearch:**

    ```yaml
    apiVersion: logging.banzaicloud.io/v1beta1
    kind: ClusterOutput
    metadata:
      name: opensearch-output
    spec:
      opensearch:
        host: https://opensearch-cluster-master.es.svc.cluster.local:9200
        index_name: control-plane-%Y%m%d
        user:
          username:
            valueFrom:
              secretKeyRef:
                name: opensearch-auth
                key: username
          password:
            valueFrom:
              secretKeyRef:
                name: opensearch-auth
                key: password
        ssl_verify: false
        suppress_type_name: true
        buffer:
          timekey: 1m
          timekey_wait: 30s
          timekey_use_utc: true
          chunk_limit_size: 8MB
    ```

    **Важно:** Веб-интерфейс Rancher не поддерживает OpenSearch напрямую — после создания через UI необходимо редактировать YAML вручную. Параметр `suppress_type_name: true` обязателен для современных версий OpenSearch/Elasticsearch. Индекс с `%Y%m%d` создаётся ежедневно.

#### 5. Создание Flow для сбора логов Control Plane

1. **Создание `Flow`**:
    * Выберите `namespace` (например, `kube-system`).
    * В секции **Outputs** выберите созданный `ClusterOutput`.
    * В секции **Filters** добавьте `Tag Normalizer` и `Kube Events Timestamp`.

2. **Настройка фильтров**:

    * **Tag Normalizer** — формирует тег для динамического именования индексов на основе namespace, pod и container:

        ```yaml
        filters:
        - tag_normalizer:
            tag: ${namespace_name}.${pod_name}.${container_name}
        ```

    * **Kube Events Timestamp** — генерирует поле `mtime` с временной меткой события (критично для временной сортировки в OpenSearch/Elasticsearch):

        ```yaml
        filters:
        - kube_events_timestamp:
            time_field: mtime
        ```

    **Пример Flow для сбора логов из kube-system:**

    ```yaml
    apiVersion: logging.banzaicloud.io/v1beta1
    kind: Flow
    metadata:
      name: control-plane-flow
      namespace: kube-system
    spec:
      filters:
      - tag_normalizer:
          tag: ${namespace_name}.${pod_name}.${container_name}
      - kube_events_timestamp:
          time_field: mtime
      globalOutputRefs:
      - opensearch-output
    ```

### Важный нюанс логирования Fluentd

По умолчанию логи самого `Fluentd` не выводятся в `stdout/stderr` контейнера, а сохраняются внутри него (например, `/var/log/fluentd/out`). Для отладки может потребоваться `kubectl exec` в контейнер `fluentd`:

```bash
kubectl exec -n cattle-logging-system <fluentd-pod> -- cat /var/log/fluentd/out
```

**Просмотр конфигурации Fluentd:** Текущая конфигурация хранится в `Secret` (например, `fluentd-app`), который автоматически обновляется при изменении `Flow` и `Output`.

**Troubleshooting:**

1. **Проверка логов Fluent Bit** (сборщики на узлах):

    ```bash
    kubectl logs -n cattle-logging-system -l app.kubernetes.io/name=fluentbit
    ```

    Ошибки подключения к Fluentd могут указывать на проблемы с буферизацией или сетевые проблемы.

2. **Проверка логов Fluentd** (маршрутизатор):

    ```bash
    kubectl exec -n cattle-logging-system <fluentd-pod> -- cat /var/log/fluentd/out
    ```

    Ищите ошибки `flush_unavailable` или ошибки подключения к output.

3. **Буферизация:** Если логи не появляются в OpenSearch сразу, проверьте настройки буфера в `ClusterOutput`. По умолчанию Fluentd может отправлять логи пакетами раз в минуту.

## Ограничения RBAC

* **`ClusterFlow` и `ClusterOutput`**: Могут быть созданы только администраторами Rancher.
* **`Flow` и `Output` (привязанные к `namespace`)**:
  * `Project Owner` может создавать и изменять `Flow` и `Output`.
  * `Project Member` **не может** создавать `Flow` и `Output` (только просмотр).

**Критическое замечание:** Это ограничение делает функциональность логирования Rancher для пользовательских приложений малопригодной для самостоятельного использования разработчиками с ролью `Project Member`. Пользователь с ролью `Project Member` не может самостоятельно настроить сбор логов своего приложения — требуется вмешательство администратора или `Project Owner`.

**Сравнение ролей:**

| Роль | ClusterFlow/Output | Flow/Output |
| :--- | :--- | :--- |
| **Admin** | ✅ Создание/чтение/удаление | ✅ Создание/чтение/удаление |
| **Project Owner** | ❌ Нет доступа | ✅ Создание/чтение/удаление |
| **Project Member** | ❌ Нет доступа | ⚠️ Только чтение |

## Дополнительная информация

См. также: [rancher_overview](./rancher_overview.md) — обзор платформы Rancher.
