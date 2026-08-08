# OpenSearch: Администрирование и устранение неполадок

> Эта заметка является частью обзора [OpenSearch](./opensearch_overview.md) и рассматривает ключевые аспекты администрирования кластера OpenSearch, включая управление конфигурацией безопасности, ролями узлов, оптимизацию производительности и решение распространенных проблем.

## Определения

* **opensearch-security**: плагин безопасности OpenSearch для защиты кластера (аутентификация, авторизация, шифрование TLS (Transport Layer Security)).
* **Security REST API**: интерфейс REST (Representational State Transfer) API (Application Programming Interface) для управления пользователями, ролями и сопоставлениями (маппингами). Позволяет вносить динамические изменения без перезагрузки кластера.
* **securityadmin.sh**: утилита командной строки для инициализации и принудительного применения конфигурации безопасности из YAML-файлов. Является единственным способом изменения базовых настроек аутентификации (например, LDAP/SAML) в `config.yml`.
* **Cluster Manager (ранее Master)**: роль узла, ответственного за управление состоянием кластера, создание/удаление индексов и распределение шардов.
* **Segment Replication (SegRep)**: механизм репликации в OpenSearch 2.x, при котором первичный шард копирует готовые сегменты Lucene на реплики, вместо повторной индексации документов на каждом узле.
* **Remote-Backed Storage (RBS)**: технология хранения данных в объектном хранилище (S3/GCS/Azure), где облако выступает в роли "источника истины". Требует SegRep и обеспечивает RPO (Recovery Point Objective) близкий к нулю.
* **Wildcard Field**: специализированный тип поля для эффективного поиска по шаблонам с префиксами и регулярными выражениями (аналог в Elasticsearch).
* **Derived Fields**: виртуальные поля, вычисляемые во время выполнения запроса (query-time) на основе существующих данных.
* **Snapshot (Снимок)**: резервная копия индексов или всего состояния кластера, хранимая во внешнем репозитории (S3, GCS, Azure, NFS).

## Основные концепции

### Роли узлов (Node Roles)

В OpenSearch 2.x произошел отказ от термина "Master" в пользу "Cluster Manager". Основные роли:
* **cluster_manager**: управление метаданными кластера. Минимум 3 узла для кворума в Prod.
* **data**: хранение данных и выполнение операций поиска/индексации.
* **ingest**: предварительная обработка документов перед индексацией.
* **search**: выделенные узлы для выполнения тяжелых поисковых запросов (Search Head).

### Модель конфигурации безопасности

* **Принцип авторитетного источника**: Вся активная конфигурация безопасности хранится во внутреннем скрытом индексе `.opendistro_security` (или `.security`).
* **GitOps vs Runtime**:
    * **securityadmin.sh**: используется для синхронизации настроек из Git (YAML-файлы) с индексом безопасности. Это единственный способ изменения настроек аутентификации (LDAP/SAML/OIDC) в `config.yml`.
    * **REST API**: используется для оперативного создания пользователей и ролей. ВНИМАНИЕ: запуск `securityadmin.sh` без флага `-backup` может перезаписать (удалить) изменения, внесенные через API.

### Репликация и хранение (SegRep & RBS)

* **Document-level Replication (по умолчанию)**: первичный шард отправляет запрос на индексацию на реплики. Каждый узел самостоятельно выполняет CPU-затратную операцию индексации.
* **Segment Replication (SegRep)**: первичный шард индексирует данные и копирует полученные файлы сегментов на реплики. Снижает нагрузку на CPU на репликах и повышает общую производительность индексации, но увеличивает нагрузку на сеть.
* **Remote-Backed Storage (RBS)**: В версии 2.15+ является production-ready. Данные пишутся в удаленное хранилище (S3/GCS). Это позволяет:
    * Отказаться от хранения полных копий данных на всех узлах.
    * Мгновенно заменять упавшие узлы без долгого процесса восстановления шардов (данные подтягиваются из S3).
    * Снизить стоимость хранения за счет использования дешевого объектного хранилища.

### Оптимизация и новые типы полей

* **Shard Management**: В OpenSearch 2.15 жесткий лимит — **1000 шардов на узел**. В 2.17+ увеличен до 4000. Целевой показатель: **25 шардов на 1 ГБ JVM heap**.
* **Wildcard Fields**: Оптимизированы для логов. Индексируются дольше, чем `text`, но обеспечивают высокую производительность при поиске типа `*error*`.
* **Derived Fields**: Позволяют добавлять логику обработки данных без переиндексации. **Накладные расходы**: вычисляются в момент запроса, что значительно увеличивает нагрузку на CPU при больших объемах данных.
* **Parallel Ingestion**: Возможность обработки документов в параллельном режиме (batch_ingestion: parallel). Критично для тяжелых ingestion pipelines (например, с ML-эмбеддингами).
* **SIMD & Dynamic Pruning**: Автоматические оптимизации в 2.15+, ускоряющие поиск (до 1.5x) и агрегации (до 100x) на поддерживаемом железе.

## Практические сценарии

### Методы управления конфигурацией безопасности

#### 1. REST API (Повседневное управление)

```bash
# Получение информации о пользователе 'admin'
curl -k -u admin:new_password "https://opensearch-host:9200/_plugins/_security/api/internalusers/admin"

# Обновление роли 'my_role' из JSON-файла
curl -k -u admin:new_password -XPUT "https://opensearch-host:9200/_plugins/_security/api/roles/my_role" \
-H "Content-Type: application/json" -d @role.json
```

#### 2. securityadmin.sh (Инфраструктурный подход)

Утилита незаменима при полной автоматизации через CI/CD.

```bash
# Применяем конфигурацию из смонтированных YAML-файлов (например, в Kubernetes)
./securityadmin.sh \
  -f /usr/share/opensearch/config/opensearch-security/internal_users.yml \
  -cacert /usr/share/opensearch/config/root-ca.pem \
  -cert /usr/share/opensearch/config/admin-cert.pem \
  -key /usr/share/opensearch/config/admin-key.pem \
  -h opensearch-cluster-manager-service -icl -nhnv -backup
```

**Специальные сценарии:**
* **Сброс пароля администратора**: Обновите хеш пароля в `internal_users.yml` и запустите `securityadmin.sh`. Это единственный способ вернуть доступ, если API недоступен или учетные данные утеряны.
* **Восстановление на "красном" кластере**: Если индекс `.security` поврежден, API не будет работать. Используйте флаг `-arc` (accept-red-cluster) для принудительного применения конфигурации.

### Резервное копирование и восстановление (Snapshots)

#### 1. Регистрация репозитория и создание снимка

```http
# Регистрация S3
PUT /_snapshot/my_s3_repository
{
  "type": "s3",
  "settings": {
    "bucket": "opensearch-backups",
    "region": "us-east-1",
    "role_arn": "arn:aws:iam::123456789012:role/OpenSearchSnapshotRole"
  }
}

# Создание снимка (асинхронно)
PUT /_snapshot/my_s3_repository/snapshot_2024_05_20?wait_for_completion=false
```

#### 2. Восстановление (Restore)

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

### Обновление и миграция на RBS

*   **Upgrade Path**: Для перехода на 3.x (будущие версии) необходимо сначала обновиться до **2.19**.
*   **Rolling Upgrade to RBS**: Можно перевести кластер с Document Replication на Remote-Backed Storage без простоя. 
    1. Включите SegRep на индексах.
    2. Настройте RBS в настройках кластера.
    3. Выполните rolling restart узлов.
    * **ВНИМАНИЕ**: Это необратимая операция. Возврат к обычной репликации возможен только через Snapshot Restore.

### Параллельная индексация (Parallel Ingestion)

Используйте в Bulk запросах для ускорения обработки:
```json
POST /_bulk?batch_ingestion=parallel
{ "index" : { "_index" : "test", "_id" : "1" } }
{ "field1" : "value1" }
```

### Устранение неполадок в Kubernetes

#### Ошибка 502 при доступе к OpenSearch Dashboards

**Проблема**: Pod помечается как `Ready` до того, как Node.js веб-сервер внутри контейнера готов принимать запросы.

**Решение**:
1.  **Кастомизация `readinessProbe`**: Проверяйте эндпоинт `/api/status` (возвращает JSON со статусом плагинов) или корневую страницу логина вместо простой проверки порта.
    ```yaml
    readinessProbe:
      httpGet:
        path: /api/status
        port: 5601
      initialDelaySeconds: 90
      periodSeconds: 10
    ```
2.  **Initial Delay**: Установите `initialDelaySeconds` не менее 60-90 секунд. Dashboards инициализирует плагины безопасности и визуализации, что требует времени.

## Оперативное управление и диагностика (Dev Tools)

### Состояние кластера и нод

```http
# Статус здоровья кластера
GET /_cluster/health?pretty

# Детальное состояние нод: нагрузка, CPU, RAM, Heap и текущий cluster_manager
GET /_cat/nodes?v&h=name,ip,node.role,heap.percent,ram.percent,cpu,load_1m,cluster_manager
```

### Диагностика репликации и шардов

```http
# Статус Segment Replication (отставание реплик)
GET /_cat/segment_replication?v

# Объяснение причин unassigned шардов
GET /_cluster/allocation/explain
{
  "index": "my-index-name",
  "shard": 0,
  "primary": true
}
```

### Настройки кластера

```http
# Просмотр текущих настроек (persistent и transient)
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
* **[OpenSearch Dashboards: Визуализация и Управление](./opensearch_dashboards.md)** — подробное руководство по веб-интерфейсу.
* **[Управление жизненным циклом (ISM)](./opensearch_ism_lifecycle.md)** — автоматизация ротации индексов.
* **[Официальная документация OpenSearch](https://opensearch.org/docs/latest/)** — первоисточник по всем API.
