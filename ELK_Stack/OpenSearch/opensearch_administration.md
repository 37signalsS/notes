# OpenSearch: Администрирование и устранение неполадок

> Эта заметка является частью обзора [OpenSearch](./opensearch_overview.md) и рассматривает ключевые аспекты администрирования кластера OpenSearch, включая управление конфигурацией безопасности, ролями узлов и решение распространенных проблем.

## Определения

* **opensearch-security**: плагин безопасности OpenSearch для защиты кластера (аутентификация, авторизация, шифрование TLS (Transport Layer Security)).
* **Security REST API**: интерфейс REST (Representational State Transfer) API (Application Programming Interface) для управления пользователями, ролями и сопоставлениями (маппингами). Позволяет вносить динамические изменения без перезагрузки кластера.
* **securityadmin.sh**: утилита командной строки для инициализации и принудительного применения конфигурации безопасности из YAML-файлов. Является единственным способом изменения базовых настроек аутентификации (например, LDAP/SAML) в `config.yml`.
* **Cluster Manager (ранее Master)**: роль узла, ответственного за управление состоянием кластера, создание/удаление индексов и распределение шардов.
* **Segment Replication (SegRep)**: механизм репликации в OpenSearch 2.x, при котором первичный шард копирует готовые сегменты Lucene на реплики, вместо повторной индексации документов на каждом узле.
* **Snapshot (Снимок)**: резервная копия индексов или всего состояния кластера, хранимая во внешнем репозитории (S3, GCS, Azure, NFS).

## Основные концепции

### Роли узлов (Node Roles)

В OpenSearch 2.x произошел отказ от термина "Master" в пользу "Cluster Manager". Основные роли:
* **cluster_manager**: управление метаданными кластера.
* **data**: хранение данных и выполнение операций поиска/индексации.
* **ingest**: предварительная обработка документов перед индексацией.
* **search**: выделенные узлы для выполнения тяжелых поисковых запросов (Search Head).

### Модель конфигурации безопасности

* **Принцип авторитетного источника**: Вся активная конфигурация безопасности хранится во внутреннем скрытом индексе `.opendistro_security` (или `.security` в новых версиях).
* **GitOps vs Runtime**:
    * **securityadmin.sh**: используется для синхронизации настроек из Git (YAML-файлы) с индексом безопасности. Это предпочтительный метод для инфраструктурных настроек.
    * **REST API**: используется для оперативного создания пользователей и ролей. ВНИМАНИЕ: запуск `securityadmin.sh` без флага `-backup` может перезаписать (удалить) изменения, внесенные через API.

### Репликация: Document vs Segment

* **Document-level Replication (по умолчанию)**: первичный шард отправляет запрос на индексацию на реплики. Каждый узел самостоятельно выполняет CPU-затратную операцию индексации.
* **Segment Replication (SegRep)**: первичный шард индексирует данные и копирует полученные файлы сегментов на реплики. Это снижает нагрузку на CPU на репликах и повышает общую производительность индексации, но увеличивает нагрузку на сеть.

### Методы управления конфигурацией

#### Современный подход: REST API

Для повседневного управления пользователями, ролями и маппингами следует использовать Security REST API. Это предпочтительный и наиболее безопасный метод.

```bash
# Получение информации о пользователе 'admin'
curl -k -u admin:new_password "https://opensearch-host:9200/_plugins/_security/api/internalusers/admin"

# Обновление роли 'my_role' из файла role.json (формат JSON — JavaScript Object Notation)
curl -k -u admin:new_password -XPUT "https://opensearch-host:9200/_plugins/_security/api/roles/my_role" \
-H "Content-Type: application/json" -d @role.json
```

#### Инфраструктурный подход (GitOps): securityadmin.sh

Утилита `securityadmin.sh` — единственный способ изменить настройки в `config.yml` (например, добавить новый LDAP-сервер) и основной инструмент для синхронизации конфигурации безопасности с системой контроля версий (Git).

> **Внимание**: по умолчанию `securityadmin.sh` **перезаписывает** индекс безопасности. Чтобы сохранить изменения, внесенные через API, используйте флаг `-backup`.

**Сценарии использования:**

1.  **Синхронизация из Git**:
    ```bash
    # Применяем конфигурацию из смонтированных YAML-файлов (например, в Kubernetes)
    ./securityadmin.sh \
      -f /usr/share/opensearch/config/opensearch-security/internal_users.yml \
      -cacert /usr/share/opensearch/config/root-ca.pem \
      -cert /usr/share/opensearch/config/admin-cert.pem \
      -key /usr/share/opensearch/config/admin-key.pem \
      -h opensearch-cluster-manager-service -icl -nhnv
    ```
2.  **Сброс пароля администратора**: если доступ через API потерян, обновите хеш пароля в `internal_users.yml` и запустите `securityadmin.sh`.
3.  **Восстановление на "красном" кластере**: если индекс безопасности поврежден и API недоступен, используйте флаг `-arc` (accept-red-cluster) для принудительного восстановления.

### Резервное копирование и восстановление (Snapshots)

Для работы со снимками необходимо сначала зарегистрировать репозиторий.

#### 1. Регистрация S3-репозитория (пример)

```http
PUT /_snapshot/my_s3_repository
{
  "type": "s3",
  "settings": {
    "bucket": "opensearch-backups",
    "region": "us-east-1",
    "role_arn": "arn:aws:iam::123456789012:role/OpenSearchSnapshotRole"
  }
}
```

#### 2. Создание снимка

```http
# Создание снимка всего кластера (асинхронно)
PUT /_snapshot/my_s3_repository/snapshot_2024_05_20?wait_for_completion=false

# Проверка статуса
GET /_snapshot/my_s3_repository/snapshot_2024_05_20/_status
```

#### 3. Восстановление снимка

При восстановлении рекомендуется отключать реплики для ускорения процесса и переименовывать индексы, если они уже существуют.

```http
POST /_snapshot/my_s3_repository/snapshot_2024_05_20/_restore
{
  "indices": "logs-*",
  "index_settings": {
    "index.number_of_replicas": 0
  },
  "ignore_unavailable": true,
  "include_global_state": false
}
```

### Ошибка 502 при доступе к OpenSearch Dashboards (Kubernetes)

**Проблема**: Helm-чарт для `opensearch-dashboards` может иметь некорректно настроенную пробу готовности `readinessProbe`. Под помечается как `Ready` до того, как веб-сервер внутри контейнера действительно начнет отвечать.

**Решение**:
* **Кастомизация `readinessProbe`**: в `values.yaml` для `opensearch-dashboards` укажите проверку эндпоинта `/api/status` или страницы логина.
* **Initial Delay**: увеличьте `initialDelaySeconds` до 60–90 секунд, чтобы дать Node.js время на инициализацию плагинов.

## Оперативное управление и диагностика (Dev Tools)

Для выполнения диагностических запросов используется вкладка **Dev Tools** в OpenSearch Dashboards.

### Состояние кластера и нод

```http
# Общий статус здоровья кластера (green, yellow, red)
GET /_cluster/health?pretty

# Список нод, их IP и роли
GET /_cat/nodes?v

# Детальное состояние нод: нагрузка, CPU, RAM, Heap и текущий cluster_manager
GET /_cat/nodes?v&h=name,ip,node.role,heap.percent,ram.percent,cpu,load_1m,cluster_manager
```

### Диагностика репликации и задач

```http
# Просмотр статуса Segment Replication (отставание реплик)
GET /_cat/segment_replication?v

# Список длительных задач (индексация, восстановление, удаление)
GET /_tasks?detailed=true&actions=*reindex,internal:admin/indices/shard*

# Просмотр активных процессов восстановления шардов
GET /_cat/recovery?v&active_only=true
```

### Управление индексами и шардами

```http
# Список всех индексов и их текущий статус
GET /_cat/indices?v

# Информация о заполнении дисков нодами
GET /_cat/allocation?v

# Объяснение причин проблемного шарда (unassigned)
GET /_cluster/allocation/explain
{
  "index": "my-index-name",
  "shard": 0,
  "primary": true
}
```

### Настройки кластера

```http
# Просмотр текущих настроек кластера (persistent и transient)
GET /_cluster/settings?include_defaults=false

# Пример ограничения скорости восстановления (throttle)
PUT /_cluster/settings
{
  "persistent": {
    "indices.recovery.max_bytes_per_sec": "100mb"
  }
}
```

## Дополнительная информация

* **[OpenSearch: Обзор системы](./opensearch_overview.md)** — архитектура и основные компоненты.
* **[Управление жизненным циклом (ISM)](./opensearch_ism_lifecycle.md)** — автоматизация ротации индексов.
* **[Официальная документация OpenSearch](https://opensearch.org/docs/latest/)** — первоисточник по всем API.
