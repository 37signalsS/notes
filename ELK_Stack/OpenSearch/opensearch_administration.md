# OpenSearch: Администрирование и устранение неполадок

> Эта заметка является частью обзора [OpenSearch](./opensearch_overview.md) и рассматривает ключевые аспекты администрирования кластера OpenSearch, включая управление конфигурацией безопасности, ролями узлов, оптимизацию производительности, резервное копирование и решение распространенных проблем. Первоисточник по всем API: [официальная документация OpenSearch](https://docs.opensearch.org/latest/).

## Определения

* **opensearch-security**: плагин безопасности OpenSearch для защиты кластера (аутентификация, авторизация, шифрование TLS (Transport Layer Security), аудит, Document-/Field-Level Security).
* **Security REST API**: интерфейс REST (Representational State Transfer) API (Application Programming Interface) для управления пользователями, ролями и сопоставлениями (маппингами). Позволяет вносить динамические изменения без перезагрузки кластера.
* **securityadmin.sh**: утилита командной строки для инициализации и принудительного применения конфигурации безопасности из YAML-файлов. Основной способ изменения базовых настроек аутентификации (LDAP/SAML/OIDC) в `config.yml`. Требует TLS на HTTP-слое и сертификата, чей DN внесен в `plugins.security.admin_dn`.
* **Cluster Manager (ранее Master)**: роль узла, ответственного за управление состоянием кластера, создание/удаление индексов и распределение шардов.
* **Segment Replication (SegRep)**: механизм репликации в OpenSearch 2.x, при котором первичный шард копирует готовые сегменты Lucene на реплики, вместо повторной индексации документов на каждом узле.
* **Remote-Backed Storage (RBS)**: технология хранения данных в объектном хранилище (S3/GCS/Azure), где облако выступает в роли авторитетного хранилища. Требует SegRep и обеспечивает RPO (Recovery Point Objective) близкий к нулю. В документации ветки 3.x механизм именуется **Remote store** и включает дополнительные подсистемы (remote cluster state, backpressure, warmer).
* **Wildcard Field**: специализированный строковый тип поля, оптимизированный под поиск по шаблонам (`*`, `?`) и регулярным выражениям; индексирует термины так, чтобы запрос вида `*error*` не превращался в полный перебор (аналогичный тип есть в Elasticsearch).
* **Derived Fields**: виртуальные поля, вычисляемые во время выполнения запроса (query-time) на основе существующих данных без переиндексации. Экспериментальный функционал ветки 3.x.
* **Snapshot (Снимок)**: резервная копия индексов или всего состояния кластера, хранимая во внешнем репозитории (S3, GCS, Azure, NFS). Снимки инкрементальны: повторный снимок переносит только изменения со времени предыдущего.
* **Snapshot Management (SM)**: автоматизация создания и удаления снимков по расписанию (cron) с политиками удержания; часть плагина Index Management, эндпоинты `_plugins/_sm/policies`. Функциональный аналог SLM в Elasticsearch.
* **Circuit Breaker (Размыкатель цепи)**: механизм защиты JVM heap — операция (запрос, агрегация) прерывается ошибкой, если оценка ее потребления памяти превысит лимит брейкера; это предотвращает падение узла из-за OutOfMemoryError.

## Основные концепции

### Роли узлов (Node Roles)

В OpenSearch 2.x произошел отказ от термина "Master" в пользу "Cluster Manager" (переименование введено в версии 1.3). Роли задаются параметром `node.roles` в `opensearch.yml`; узел без явного списка ролей выполняет все роли, а пустой список делает узел выделенным координирующим:

| Роль | Назначение | Замечания по планированию |
| :--- | :--- | :--- |
| `cluster_manager` | Управление метаданными кластера, публикация состояния | Минимум 3 узла для кворума в Prod; желательно выделенные |
| `data` | Хранение данных, CRUD, поиск, агрегации | Самая ресурсоемкая роль; интенсивная нагрузка на I/O, CPU, память |
| `ingest` | Предварительная обработка документов (pipelines) | Выделяйте при тяжелых пайплайнах (парсинг, обогащение) |
| `search` | Выделенное обслуживание поисковых запросов | В релизах ветки 3.x поддерживает search replica |
| `warm` | Теплый ярус для редко запрашиваемых данных | Используется ISM-политиками через `allocation.require` |
| `coordinating` (пустой список ролей) | Маршрутизация запросов, merge результатов | Балансировщики нагрузки в крупных кластерах |
| `ml` | Выполнение ML-моделей (ML Commons) | Отдельный пул ресурсов для эмбеддингов/inference |
| `remote_cluster_client` | Клиент cross-cluster search/replication | Нужен узлам, участвующим в кросс-кластерных операциях |

Разделение нагрузок индексации и поиска (релизы ветки 3.x 2025 года): вводятся **write replica** (копия первичного шарда, может быть повышена до primary при сбое) и **search replica** (обслуживает только поиск, не может стать primary). Первичные шарды и write replica размещаются на узлах роли `data`, search replica — только на узлах роли `search`. Это позволяет масштабировать индексацию и поиск независимо друг от друга и использовать специализированное железо под каждый класс нагрузки.

### Модель конфигурации безопасности

* **Принцип авторитетного источника**: Вся активная конфигурация безопасности хранится во внутреннем системном индексе `.opendistro_security`. Изменения применяются динамически, без рестарта кластера и без правки файлов на каждом узле.
* **GitOps vs Runtime**:
    * **securityadmin.sh**: используется для синхронизации настроек из Git (YAML-файлы в `config/opensearch-security/`) с индексом безопасности. Основной способ изменения настроек аутентификации (LDAP/SAML/OIDC) в `config.yml`. Правка YAML-файлов сама по себе ничего не меняет — их нужно явно загрузить скриптом.
    * **REST API**: используется для оперативного управления пользователями и ролями. Эндпоинт обновления всей конфигурации (`PUT _plugins/_security/api/securityconfig`) существует, но официальная документация прямо предостерегает от него ("operation can easily break your existing configuration") и рекомендует securityadmin.sh как более безопасный инструмент.
    * **ВНИМАНИЕ**: запуск `securityadmin.sh` без предварительного бэкапа может перезаписать (удалить) изменения, внесенные через API. Официальный пример из документации: инициализация индекса, создание 10 пользователей через API, затем повторный запуск скрипта со всем каталогом конфигурации — все 10 пользователей будут потеряны.
* **Предусловия securityadmin.sh**: на HTTP-слое должен быть включен TLS (`plugins.security.ssl.http.enabled: true`; если TLS не используется во всем кластере, включите его хотя бы на одном узле и запускайте скрипт там), а DN административного сертификата должен быть прописан в `plugins.security.admin_dn` в `opensearch.yml`.

### Репликация и хранение (SegRep и Remote Store)

* **Document-level Replication (по умолчанию)**: первичный шард отправляет запрос на индексацию на реплики. Каждый узел самостоятельно выполняет CPU-затратную операцию индексации.
* **Segment Replication (SegRep)**: первичный шард индексирует данные и копирует полученные файлы сегментов на реплики. Снижает нагрузку на CPU на репликах и повышает общую производительность индексации, но увеличивает потребление сети. Включается настройкой индекса `"index.replication.type": "SEGMENT"`; GA начиная с версии 2.7. При равномерном распределении первичных шардов между узлами (`cluster.routing.allocation.balance.prefer_primary`, динамическая настройка) снижается риск узких мест по сети.
* **Remote-Backed Storage (RBS)**: в версии 2.15+ является production-ready. Данные пишутся в удаленное хранилище (S3/GCS). Это позволяет:
    * Отказаться от хранения полных копий данных на всех узлах.
    * Мгновенно заменять упавшие узлы без долгого процесса восстановления шардов (данные подтягиваются из объектного хранилища).
    * Снизить стоимость хранения за счет использования дешевого объектного хранилища.
* **Экосистема Remote Store (ветка 3.x)**: вокруг механизма выросли подсистемы, описанные в отдельном разделе документации: миграция существующего кластера (migrating-to-remote), вынесенное состояние кластера (remote cluster state), обратное давление на запись при медленном объектном хранилище (remote segment backpressure), прогрев сегментов (warmer), shallow snapshots (снимки, ссылающиеся на данные в remote store) и Remote Store Stats API для наблюдаемости.

### Оптимизация и новые типы полей

* **Shard Management**: Жесткий лимит шардов на узел — **1000** до версии 2.15 включительно. С версии **2.17** лимит масштабируется от heap: **1000 шардов на каждые 16 ГБ JVM heap**, максимум **4000** на узел. Целевой показатель по рекомендациям: **не более 25 шардов на ГиБ heap** (консервативный ориентир — 20). Контролируется настройкой `cluster.max_shards_per_node` (по умолчанию 1000 на один data-узел; закрытые индексы не учитываются).
* **Wildcard Fields**: Оптимизированы для логов. Индексируются дольше, чем `text`, но обеспечивают высокую производительность при поиске типа `*error*`.
* **Derived Fields**: Позволяют добавлять логику обработки данных без переиндексации. **Накладные расходы**: вычисляются в момент запроса, что значительно увеличивает нагрузку на CPU при больших объемах данных.
* **Parallel Ingestion**: Возможность обработки документов в параллельном режиме (batch_ingestion: parallel). Критично для тяжелых ingestion pipelines (например, с ML-эмбеддингами). Замечание: этот параметр не входит в публично задокументированный REST API (проверено по официальной документации); перед использованием проверяйте его доступность в вашей сборке. Документированные способы ускорения тяжелой индексации — оптимальный размер bulk-запросов (старт с 3–5 МиБ), gzip-сжатие (`Accept-Encoding: gzip`), выделенные ingest-узлы.
* **SIMD & Dynamic Pruning**: Аппаратные и алгоритмические оптимизации релизов 2.13–2.17: SIMD-ускорение операций (Lucene 9.7+) и динамическое отсечение шардов по статистике индекса (dynamic pruning). Заявленные в релизных материалах приросты — до 1.5x на поиске и до 100x на отдельных числовых агрегациях на поддерживаемом железе.

## Практические сценарии

### Управление конфигурацией безопасности

#### 1. REST API (Повседневное управление)

```bash
# Получение информации о пользователе 'admin'
curl -k -u admin:new_password "https://opensearch-host:9200/_plugins/_security/api/internalusers/admin"
# → {"admin":{"hash":"$2y$12$...","reserved":true,"backend_roles":[],"attributes":{}}}

# Обновление роли 'my_role' из JSON-файла
curl -k -u admin:new_password -XPUT "https://opensearch-host:9200/_plugins/_security/api/roles/my_role" \
-H "Content-Type: application/json" -d @role.json
```

Полный цикл создания сервисной учетной записи для записи логов (пользователь + роль + маппинг):

```bash
# Шаг 1. Хеш пароля генерируется утилитой на любом узле кластера
export OPENSEARCH_JAVA_HOME=/usr/share/opensearch/jdk
./plugins/opensearch-security/tools/hash.sh -p 'S3cur3-P@ssw0rd'
# → $2y$12$xP1tDq... (bcrypt-хеш)

# Шаг 2. Создание пользователя (можно сразу с хешем вместо открытого пароля)
curl -k -u admin:new_password -XPUT "https://opensearch-host:9200/_plugins/_security/api/internalusers/log_writer" \
  -H "Content-Type: application/json" -d '{
    "password": "S3cur3-P@ssw0rd",
    "backend_roles": []
  }'
# → {"user":{"created":true}}

# Шаг 3. Роль с правами только на свой набор индексов
curl -k -u admin:new_password -XPUT "https://opensearch-host:9200/_plugins/_security/api/roles/log_writer_role" \
  -H "Content-Type: application/json" -d '{
    "cluster_permissions": ["cluster_composite_operations"],
    "index_permissions": [{
      "index_patterns": ["logs-app-*"],
      "allowed_actions": ["crud", "create_index"]
    }]
  }'

# Шаг 4. Сопоставление пользователя с ролью
curl -k -u admin:new_password -XPUT "https://opensearch-host:9200/_plugins/_security/api/rolesmapping/log_writer_role" \
  -H "Content-Type: application/json" -d '{"users": ["log_writer"]}'

# Шаг 5. Проверка от имени нового пользователя
curl -k -u log_writer:S3cur3-P@ssw0rd "https://opensearch-host:9200/_plugins/_security/api/authenticate"
# → {"user_name":"log_writer","roles":["log_writer_role"],...}
```

`backend_roles` заполняются при внешних провайдерах аутентификации (LDAP-группы, JWT claims) — они приходят из бэкенда и сопоставляются с ролями OpenSearch через `roles_mapping.yml`.

#### 2. securityadmin.sh (Инфраструктурный подход)

Утилита незаменима при полной автоматизации через CI/CD. Расположение: `<OPENSEARCH_HOME>/plugins/opensearch-security/tools/securityadmin.sh`. Перед первым запуском убедитесь в выполнении предусловий из раздела «Модель конфигурации безопасности» (TLS на HTTP-слое и `admin_dn`).

```bash
# Применяем конфигурацию из смонтированных YAML-файлов (например, в Kubernetes)
./securityadmin.sh \
  -f /usr/share/opensearch/config/opensearch-security/internal_users.yml \
  -cacert /usr/share/opensearch/config/root-ca.pem \
  -cert /usr/share/opensearch/config/admin-cert.pem \
  -key /usr/share/opensearch/config/admin-key.pem \
  -h opensearch-cluster-manager-service -icl -nhnv -backup
```

Ключевые флаги:

| Флаг | Назначение |
| :--- | :--- |
| `-cd <dir>` | Применить все YAML-файлы из каталога |
| `-f <file>` + `-t <type>` | Применить один файл; тип: `config`, `roles`, `rolesmapping`, `internalusers`, `actiongroups`, `nodesdn`, `tenants` |
| `-backup <dir>` | Выгрузить текущую живую конфигурацию из кластера в файлы |
| `-icl`, `-nhnv` | Игнорировать имя хоста в сертификате / проверку hostname |
| `-cacert/-cert/-key` | PEM-сертификаты (root CA, admin-сертификат, ключ); для JKS — `-ks/-kspass/-ts/-tspass` |
| `-rev` | Разрешить переменные окружения вида `${env.LDAP_PASSWORD}` перед применением |
| `-rl` | Перечитать текущую конфигурацию и сбросить внутренний кэш плагина |
| `-arc` | Принять красное состояние кластера (accept red cluster) |

**Безопасная практика точечного обновления**: флаг `-f` вместе с `-t` перезаписывает только одну секцию конфигурации. Если вы создали десять ролей через API и хотите добавить лишь одного внутреннего пользователя, загрузите один файл (`-f internal_users.yml -t internalusers`) — роли останутся нетронутыми, перезапишутся только внутренние пользователи. Перед любым применением делайте резервную копию живой конфигурации:

```bash
./securityadmin.sh -backup /tmp/sec-backup -icl -nhnv \
  -cacert root-ca.pem -cert admin-cert.pem -key admin-key.pem
```

**Специальные сценарии:**
* **Сброс пароля администратора**: Обновите хеш пароля в `internal_users.yml` (сгенерированный `hash.sh`) и запустите `securityadmin.sh`. Это единственный способ вернуть доступ, если API недоступен или учетные данные утеряны.
* **Восстановление на "красном" кластере**: Если системный индекс безопасности недоступен и API не работает, используйте флаг `-arc` для принудительного применения конфигурации.
* **Начальный пароль администратора (2.12+)**: стандартные демо-учетные данные больше не допустимы — при первом запуске требуется переменная окружения `OPENSEARCH_INITIAL_ADMIN_PASSWORD`. Если API доступен, пароль меняется без скрипта: `PUT _plugins/_security/api/internalusers/admin` с телом `{"password": "..."}`.

#### 3. Аудит действий пользователей

Аудит включен по умолчанию и пишет события в индексы вида `audit-YYYY.MM.dd`; настройка глубины ведения — в `audit.yml` (категория `config`):

```yaml
config:
  audit:
    enable_rest: true                      # аудит REST-запросов
    disabled_rest_categories: [AUTHENTICATED]   # не логировать успешную аутентификацию
    enable_transport: true                 # аудит транспортного слоя
    disabled_transport_categories: [GRANTED_PRIVILEGES, AUTHENTICATED]
    resolve_bulk_requests: true            # разбирать bulk на отдельные запросы
    log_request_body: false                # не писать тела запросов (объем и приватность)
    resolve_indices: true                  # резолвить затронутые индексы
    ignore_users: [kibanaserver]           # исключить сервисную учетную запись
```

Применяется как остальные YAML-файлы конфигурации (через securityadmin.sh). Индексы аудита растут постоянно — подключите к ним ISM-политику ротации и удаления, чтобы не переполнить кластер собственным журналом безопасности.

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
```

Секреты доступа к бакету рекомендуется хранить не в настройках репозитория, а в зашифрованном keystore узлов (`opensearch-keystore add s3.client.default.access_key`). Создание снимка:

```http
# Создание снимка (асинхронно)
PUT /_snapshot/my_s3_repository/snapshot_2026_08_23?wait_for_completion=false

# Прогресс выполнения снимка
GET /_snapshot/my_s3_repository/snapshot_2026_08_23/_status
# → "state":"SUCCESS", "shards":{"failed":0,...}
```

#### 2. Восстановление (Restore)

```http
POST /_snapshot/my_s3_repository/snapshot_2026_08_23/_restore
{
  "indices": "logs-*",
  "index_settings": {
    "index.number_of_replicas": 0
  },
  "ignore_unavailable": true,
  "include_global_state": false
}
```

Пояснения: `ignore_unavailable` пропускает отсутствующие в снимке индексы из шаблона; `include_global_state: false` не восстанавливает состояние кластера поверх живого; временные настройки (`index_settings`) позволяют ускорить восстановление без реплик. Восстановление в переименованный индекс выполняется блоком `"rename_pattern": "logs-(.*)", "rename_replacement": "restored-logs-$1"`.

#### 3. Автоматизация через Snapshot Management (SM)

SM-политики (плагин Index Management) снимают весь кластер по расписанию и удаляют устаревшие снимки по условиям удержания. Идентификатор политики становится `<name>-sm-policy`, поэтому имя должно быть уникальным и неизменяемым.

```json
POST _plugins/_sm/policies/daily-policy
{
  "description": "Ежедневный снимок всех индексов",
  "creation": {
    "schedule": { "cron": { "expression": "0 8 * * *", "timezone": "UTC" } },
    "time_limit": "1h"
  },
  "deletion": {
    "schedule": { "cron": { "expression": "0 1 * * *", "timezone": "UTC" } },
    "condition": { "max_age": "30d", "max_count": 60, "min_count": 7 },
    "time_limit": "1h"
  },
  "snapshot_config": {
    "date_format": "yyyy-MM-dd",
    "timezone": "UTC",
    "indices": "*",
    "repository": "my_s3_repository",
    "ignore_unavailable": true,
    "include_global_state": false,
    "partial": false
  },
  "notification": {
    "channel": { "id": "<notifications-channel-id>" },
    "conditions": {
      "creation": false,
      "deletion": false,
      "failure": true,
      "time_limit_exceeded": true
    }
  }
}
# → {"_id":"daily-policy-sm-policy","policy_seq_no":0,"policy_primary_term":1,"enabled":true}
```

Управление политикой:

```bash
GET _plugins/_sm/policies/daily-policy/_explain
# → "creation":{"current_state":"CREATION_START","trigger":{...}},"enabled":true

POST _plugins/_sm/policies/daily-policy/_stop     # пауза (enabled=false)
POST _plugins/_sm/policies/daily-policy/_start    # возобновить
```

Важные детали: обновление политики требует optimistic concurrency control — `PUT _plugins/_sm/policies/daily-policy?if_seq_no=N&if_primary_term=M`; для SM существуют предопределенные роли `snapshot_management_full_access` и `snapshot_management_read_access`; первый снимок тяжелый, последующие инкрементальны; при нескольких кластерах, пишущих в один репозиторий, разведите расписания cron, чтобы избежать конфликтов.

### Обновление кластера и миграция на Remote Store

*   **Upgrade Path**: Для перехода на ветку 3.x необходимо сначала обновиться до последнего минорного релиза 2.x — **2.19** (актуальный минор линии 2.x — 2.19.x). Обновляйте через тестовый стенд с копией данных.
*   **Rolling Upgrade to RBS**: Можно перевести кластер с Document Replication на Remote-Backed Storage без простоя.
    1. Включите SegRep на индексах (`index.replication.type: SEGMENT`).
    2. Настройте RBS/Remote store в настройках кластера.
    3. Выполните rolling restart узлов.
    * **ВНИМАНИЕ**: Это необратимая операция. Возврат к обычной репликации возможен только через Snapshot Restore.

### Параллельная индексация (Parallel Ingestion)

Для ускорения обработки используйте оптимальный размер bulk-запросов и gzip-сжатие; параметр `batch_ingestion=parallel` упоминается для параллельной обработки тяжелых пайплайнов (например, с ML-эмбеддингами), однако не входит в публично задокументированный API — проверьте его поддержку в вашей сборке:

```json
POST /_bulk?batch_ingestion=parallel
{ "index" : { "_index" : "test", "_id" : "1" } }
{ "field1" : "value1" }
```

Документированная базовая оптимизация bulk: стартуйте с размера 3–5 МиБ на запрос и увеличивайте шагами до прекращения роста пропускной способности; включайте сжатие заголовками `Accept-Encoding: gzip` / `Content-Encoding: gzip`.

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
# → {"cluster_name":"...","status":"green","number_of_nodes":6,"active_shards":120,...}
```

Интерпретация статусов: **green** — все шарды (первичные и реплики) размещены; **yellow** — размещены все первичные, но часть реплик не назначена (частая причина: меньше узлов данных, чем реплик, либо лимиты размещения); **red** — отсутствует минимум один первичный шард, данные частично недоступны. Полезные флаги: `?level=indices|shards` для детализации.

```http
# Детальное состояние нод: нагрузка, CPU, RAM, Heap и текущий cluster_manager
GET /_cat/nodes?v&h=name,ip,node.role,heap.percent,ram.percent,cpu,load_1m,cluster_manager
```

Столбец `heap.percent` — главный ранний индикатор проблем: устойчивые значения выше 75% означают давление на сборщик мусора; выше 85% — риск срабатывания circuit breaker'ов.

### Диагностика репликации и шардов

```http
# Статус Segment Replication (отставание реплик)
GET /_cat/segment_replication?v

# Распределение шардов и использование диска по узлам
GET /_cat/allocation?v

# Крупнейшие шарды кластера (сортировка по размеру)
GET /_cat/shards?v&bytes=gb&s=store.size:desc

# Активные процессы восстановления шардов
GET /_cat/recovery?v&active_only=true

# Объяснение причин unassigned шардов
GET /_cluster/allocation/explain
{
  "index": "my-index-name",
  "shard": 0,
  "primary": true
}
```

Ответ `allocation/explain` называет конкретную причину отказа от размещения: превышен disk watermark (`DECIDED_BY_ALLOCATOR` + watermark в тексте), достигнут лимит `max_shards_per_node`, нет подходящего узла по фильтрам/allocation require, шард уже размещен (`ALLOCATION_COMPLETED`) и так далее.

### Диагностика производительности

```http
# Очередь ожидающих задач cluster manager (рост = проблемы метаданных)
GET /_cat/pending_tasks?v
# → insertOrder timeInQueue priority source (пусто или единицы мс — норма)

# Стеки самых активных потоков узлов под нагрузкой
GET /_nodes/hot_threads?threads=5

# JVM heap и статистика circuit breaker'ов
GET /_nodes/stats/jvm,breakers?pretty
# → jvm.mem.heap_used_percent, breakers.parent.tripped (рост трипов = тревога)
```

`hot_threads` показывает стек-трейсы потоков, потребляющих CPU — стандартный первый шаг при жалобах на медленные запросы или индексацию. Долгие поисковые задачи ищутся через `GET _tasks?detailed=true&actions=*search*`.

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

Пороговые значения disk watermarks управляют поведением при заполнении дисков:

```json
PUT _cluster/settings
{
  "persistent": {
    "cluster.routing.allocation.disk.watermark.low": "85%",
    "cluster.routing.allocation.disk.watermark.high": "90%",
    "cluster.routing.allocation.disk.watermark.flood_stage": "95%"
  }
}
```

Действия порогов: **low** — новые шарды не размещаются на узле; **high** — начинается перемещение существующих шардов на другие узлы; **flood_stage** — индексы переводятся в режим только для чтения (`index.blocks.read_only_allow_delete`). Блок снимается вручную после освобождения места:

```http
PUT logs-app-2026.08.23/_settings
{ "index.blocks.read_only_allow_delete": null }
```

## Дополнительная информация

### Ключевые ограничения и лимиты

| Ограничение | Значение | Примечание |
| :--- | :--- | :--- |
| Шардов на узел (до 2.15) | 1000 | Жесткий лимит `cluster.max_shards_per_node` |
| Шардов на узел (2.17+) | до 4000 | 1000 шардов на каждые 16 ГБ heap |
| Рекомендуемое число шардов | <= 25 на ГиБ heap | Консервативный ориентир AWS: 20–25 |
| Размер первичного шарда | 30-50 ГБ | Для логов допустимо 10-50 ГБ |
| JVM heap | 50% RAM, максимум ~31 ГБ | Сверх 31 ГБ теряется эффективность compressed oops |

Правило heap: половина памяти машины отдается JVM, вторая половина остается под страничный кэш ОС, который Lucene использует для чтения сегментов.

### Рекомендации по эксплуатации

*   **Кворум cluster manager**: нечетное число узлов (3 или 5); выделенные cluster manager узлы в продакшене избавляют метаданные кластера от влияния тяжелой индексации.
*   **Резервное копирование**: автоматизируйте снимки через SM-политики и регулярно тестируйте восстановление на стенде — бэкап, который ни разу не восстанавливали, считается несуществующим.
*   **Конфигурация безопасности в Git**: храните YAML-файлы в репозитории и применяйте securityadmin.sh из CI/CD с обязательным шагом `-backup`; это дает версионирование и воспроизводимость.
*   **Мониторинг heap и watermarks**: алерты на `heap.percent > 75`, использование диска > 80% и рост `breakers.parent.tripped`.
*   **Размер bulk-запросов**: 3-5 МиБ как стартовая точка; gzip-сжатие всегда включено по умолчанию в OpenSearch.

### Типовые проблемы кластера и их решение

1.  **Красный статус кластера**: выполните `_cluster/allocation/explain` по проблемному шарду. Типовые причины — flood_stage watermark (освободите диск, снимите блок `read_only_allow_delete`), отказ узла с единственной копией данных (восстановление из snapshot), повреждение диска. Не перезапускайте кластер хаотично — сначала объяснение, потом действие.
2.  **Желтый статус после добавления индексов**: проверьте `_cat/allocation` — чаще всего недостаточно узлов данных для числа реплик либо достигнут лимит шардов. Временное снижение числа реплик (`index.number_of_replicas: 1`) возвращает green.
3.  **Ошибка `cluster_block_exception` при записи**: индекс заблокирован flood_stage. Решение описано выше (освободить место до уровня ниже high-watermark, снять блок).
4.  **Circuit breaker exception / heap > 85%**: найдите виновника через `hot_threads` и `_tasks`; типовые источники — гигантские агрегации (terms size в тысячи бакетов), fielddata на text-полях, чрезмерное число мелких шардов на узел.
5.  **Отставание реплик в SegRep**: `_cat/segment_replication` показывает лаг; при постоянном отставании проверьте сеть между узлами и включите обратное давление (segment replication backpressure), чтобы запись не обгоняла репликацию бесконтрольно.
6.  **Рост очереди pending tasks**: долгие обновления метаданных (массовое создание индексов, шаблонов) блокируют публикацию состояния кластера. Проверьте, кто генерирует операции с метаданными (ISM, шаблоны, автосоздание индексов приложениями).

---
## См. также

*   **[OpenSearch: Обзор системы](./opensearch_overview.md)** — архитектура и основные компоненты.
*   **[OpenSearch Dashboards: Визуализация и Управление](./opensearch_dashboards.md)** — подробное руководство по веб-интерфейсу.
*   **[Управление жизненным циклом (ISM)](./opensearch_ism_lifecycle.md)** — автоматизация ротации индексов.
*   **[OpenSearch: Траблшутинг индексации](./opensearch_troubleshooting_indexing.md)** — диагностика проблем индексации и сегментов.
*   **[OpenSearch: Capacity Planning](./opensearch_capacity_planning.md)** — проектирование кластера и расчет мощностей.
