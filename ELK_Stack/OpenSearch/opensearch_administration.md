# OpenSearch: Администрирование и устранение неполадок

**Актуально для:** OpenSearch 3.9.x (релиз 29 сентября 2026). Ветка 3.0 GA — 6 мая 2025; версионные отличия (2.3, 2.7, 2.12, 2.14, 2.15, 2.17, 2.18, 3.0) отмечены в тексте.

> Эта заметка является частью обзора [OpenSearch](./opensearch_overview.md) и рассматривает ключевые аспекты администрирования кластера OpenSearch, включая управление конфигурацией безопасности, ролями узлов, оптимизацию производительности, резервное копирование и решение распространенных проблем. Первоисточник по всем API: [официальная документация OpenSearch](https://docs.opensearch.org/latest/).

## Определения

* **opensearch-security**: плагин безопасности OpenSearch для защиты кластера (аутентификация, авторизация, шифрование TLS (Transport Layer Security), аудит, Document-/Field-Level Security).
* **Security REST API**: интерфейс REST (Representational State Transfer) API (Application Programming Interface) для управления пользователями, ролями и сопоставлениями (маппингами). Позволяет вносить динамические изменения без перезагрузки кластера.
* **securityadmin.sh**: утилита командной строки для инициализации и принудительного применения конфигурации безопасности из YAML-файлов. Основной способ изменения базовых настроек аутентификации (LDAP/SAML/OIDC) в `config.yml`. Требует TLS на HTTP-слое и сертификата, чей DN внесен в `plugins.security.authcz.admin_dn`.
* **Cluster Manager (ранее Master)**: роль узла, ответственного за управление состоянием кластера, создание/удаление индексов и распределение шардов.
* **Write Replica**: в модели разделения нагрузок (Reader-Writer Separation, GA в 3.0) — обычная реплика: избыточная копия первичного шарда, обслуживает и запись, и поиск; может быть повышена до primary при сбое первичного шарда.
* **Search Replica**: реплика, обслуживающая только поисковые запросы и не может быть повышена до primary; размещается исключительно на узлах роли `search` (требуется кластер с remote store и сегментной репликацией).
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
| `search` | Выделенное обслуживание поисковых запросов | GA с 3.0: размещает search replica (нужен remote store) |
| `warm` | Теплый ярус для редко запрашиваемых данных | Используется ISM-политиками через `allocation.require` |
| `coordinating` (пустой список ролей) | Маршрутизация запросов, merge результатов | Балансировщики нагрузки в крупных кластерах |
| `ml` | Выполнение ML-моделей (ML Commons) | Отдельный пул ресурсов для эмбеддингов/inference |
| `remote_cluster_client` | Клиент cross-cluster search/replication | Нужен узлам, участвующим в кросс-кластерных операциях |

Разделение нагрузок индексации и поиска (Reader-Writer Separation; GA в OpenSearch 3.0, релиз 6 мая 2025; экспериментальный предшественник в 2.17 — флаг `opensearch.experimental.feature.read.write.split.enabled`, настройка `index.number_of_search_only_replicas` и фильтр `cluster.routing.allocation.search.replica.dedicated.include`): модель вводит два типа реплик — **write replica** (обычная реплика: избыточная копия первичного шарда, может быть повышена до primary при сбое) и **search replica** (обслуживает только поиск, не может стать primary). Первичные шарды и write replica размещаются на узлах роли `data`, search replica — только на узлах роли `search`. Модель требует кластера с remote store; индексы в таком кластере по умолчанию используют сегментную репликацию. Практические настройки:

* `index.number_of_search_replicas` (по умолчанию 0) — число search replica; динамическая настройка, применима к живому индексу.
* `index.auto_expand_search_replicas` — автомасштабирование search replica по числу search-узлов (например, `0-3`; верхняя граница `all` — по одной реплике на узел).
* `cluster.routing.search_replica.strict` (`true` по умолчанию) — маршрутизировать поиск только на search replica; `false` — fallback на primary/write replica при их недоступности.
* `cluster.remote_store.state.enabled: true` — хранить метаданные индекса в remote store, чтобы search replica восстанавливались без первичного шарда после рестарта.
* Search-only режим для write-once/read-many сценариев (лог-аналитика): `POST my-index/_scale` с телом `{"search_only": true}` отключает первичные шарды и write replica, оставляя только search replica — индекс доступен только для чтения, а статус кластера остается green; `{"search_only": false}` возвращает запись.

Это позволяет масштабировать индексацию и поиск независимо друг от друга и использовать специализированное железо под каждый класс нагрузки.

### Модель конфигурации безопасности

* **Принцип авторитетного источника**: Вся активная конфигурация безопасности хранится во внутреннем системном индексе `.opendistro_security`. Изменения применяются динамически, без рестарта кластера и без правки файлов на каждом узле.
* **GitOps vs Runtime**:
    * **securityadmin.sh**: используется для синхронизации настроек из Git (YAML-файлы в `config/opensearch-security/`) с индексом безопасности. Основной способ изменения настроек аутентификации (LDAP/SAML/OIDC) в `config.yml`. Правка YAML-файлов сама по себе ничего не меняет — их нужно явно загрузить скриптом.
    * **REST API**: используется для оперативного управления пользователями и ролями. Эндпоинт обновления всей конфигурации (`PUT _plugins/_security/api/securityconfig`) существует, но официальная документация прямо предостерегает от него ("operation can easily break your existing configuration") и рекомендует securityadmin.sh как более безопасный инструмент.
    * **ВНИМАНИЕ**: запуск `securityadmin.sh` без предварительного бэкапа может перезаписать (удалить) изменения, внесенные через API. Официальный пример из документации: инициализация индекса, создание 10 пользователей через API, затем повторный запуск скрипта со всем каталогом конфигурации — все 10 пользователей будут потеряны.
* **Предусловия securityadmin.sh**: на HTTP-слое должен быть включен TLS (`plugins.security.ssl.http.enabled: true`; если TLS не используется во всем кластере, включите его хотя бы на одном узле и запускайте скрипт там), а DN административного сертификата должен быть прописан в `plugins.security.authcz.admin_dn` в `opensearch.yml`.

### Репликация и хранение (SegRep и Remote Store)

* **Document-level Replication (по умолчанию)**: первичный шард отправляет запрос на индексацию на реплики. Каждый узел самостоятельно выполняет CPU-затратную операцию индексации.
* **Segment Replication (SegRep)**: первичный шард индексирует данные и копирует полученные файлы сегментов на реплики. Снижает нагрузку на CPU на репликах и повышает общую производительность индексации (до +25–40% пропускной способности по бенчмаркам проекта), но увеличивает потребление сети. Включается настройкой индекса `"index.replication.type": "SEGMENT"`; экспериментально с 2.3, GA начиная с версии 2.7. При равномерном распределении первичных шардов между узлами (`cluster.routing.allocation.balance.prefer_primary`, динамическая настройка) снижается риск узких мест по сети. Особенности: сегментная репликация не поддерживает политику обновления `refresh: wait_for`/`true` (для чтения сразу после записи используйте `get`/`mget`); механизм segment replication backpressure (отклонение записи при отставании реплик) появился в 2.7 и по умолчанию отключен.
* **Remote-Backed Storage (RBS)**: экспериментально с 2.14, production-ready с версии 2.15 (миграция кластера с документной репликацией на RBS через rolling upgrade). Данные пишутся в удаленное хранилище (S3/GCS). Это позволяет:
    * Отказаться от хранения полных копий данных на всех узлах.
    * Мгновенно заменять упавшие узлы без долгого процесса восстановления шардов (данные подтягиваются из объектного хранилища).
    * Снизить стоимость хранения за счет использования дешевого объектного хранилища.
* **Экосистема Remote Store (ветка 3.x)**: вокруг механизма выросли подсистемы, описанные в отдельном разделе документации: миграция существующего кластера (migrating-to-remote), вынесенное состояние кластера (remote cluster state), обратное давление на запись при медленном объектном хранилище (remote segment backpressure), прогрев сегментов (warmer), shallow snapshots (снимки, ссылающиеся на данные в remote store) и Remote Store Stats API для наблюдаемости.

### Оптимизация и новые типы полей

* **Shard Management**: Жесткий лимит шардов на узел — **1000** до версии 2.15 включительно. С версии **2.17** лимит масштабируется от heap: **1000 шардов на каждые 16 ГБ JVM heap**, максимум **4000** на узел. Целевой показатель по рекомендациям: **не более 25 шардов на ГиБ heap** (консервативный ориентир — 20). Контролируется настройкой `cluster.max_shards_per_node` (по умолчанию 1000): проверка кластерная — суммарное число первичных и реплицированных шардов не должно превышать `cluster.max_shards_per_node` × число non-frozen data-узлов; шарды закрытых индексов в лимит не входят.
* **Wildcard Fields**: Оптимизированы для логов. Индексируются дольше, чем `text`, но обеспечивают высокую производительность при поиске типа `*error*`.
* **Derived Fields**: Позволяют добавлять логику обработки данных без переиндексации. **Накладные расходы**: вычисляются в момент запроса, что значительно увеличивает нагрузку на CPU при больших объемах данных.
* **Parallel Ingestion**: Возможность обработки документов в параллельном режиме (batch_ingestion: parallel). Критично для тяжелых ingestion pipelines (например, с ML-эмбеддингами). Замечание: этот параметр не входит в публично задокументированный REST API (проверено по официальной документации); перед использованием проверяйте его доступность в вашей сборке. Документированные способы ускорения тяжелой индексации — оптимальный размер bulk-запросов (старт с 3–5 МиБ), gzip-сжатие (`Accept-Encoding: gzip`), выделенные ingest-узлы.
* **SIMD & Dynamic Pruning**: Аппаратные и алгоритмические оптимизации: SIMD-ускорение точного поиска (exact search) появилось в 2.15 и дает около 1.5x к скорости на поддерживаемом железе (SIMD для k-NN-приближенного поиска — ранее, на базе Java Vector API из Lucene 9.7); dynamic pruning (2.15) оптимизирует single-cardinality агрегации по полям с низкой кардинальностью — до 100x снижение latency по бенчмарку Big5. В 2.18 добавлена поддержка Intel AVX-512 (включена по умолчанию; до +15% к индексации и +13% к поиску в векторных нагрузках).

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

Аудит пишет события в индексы вида `audit-YYYY.MM.dd`. Важно: сам файл `audit.yml` поставляется с `config.enabled: true`, но без настройки хранилища (`plugins.security.audit.type` в `opensearch.yml`) плагин не создает endpoint записи и не записывает события — при старте кластера появляется предупреждение об отсутствии хранилища по умолчанию. Допустимые типы хранилища: `internal_opensearch` (индекс аудита на текущем кластере), `internal_opensearch_data_stream` (data stream `opensearch-security-auditlog`), `external_opensearch` (удаленный кластер), `webhook` (HTTP-эндпоинт), `log4j` (Log4j-аппендер, например Kafka), `debug` (stdout, только для тестов). Настройка глубины ведения — в `audit.yml` (режим FGAC; применяется через securityadmin.sh):

```yaml
_meta:
  type: "audit"
  config_version: 2

config:
  enabled: true
  audit:
    enable_rest: true                      # аудит REST-запросов
    disabled_categories: [AUTHENTICATED]   # не логировать успешную аутентификацию (единый список для обоих слоев)
    enable_transport: true                 # аудит транспортного слоя
    resolve_bulk_requests: true            # разбирать bulk на отдельные запросы
    log_request_body: false                # не писать тела запросов (объем и приватность)
    resolve_indices: true                  # резолвить затронутые индексы
    exclude_sensitive_headers: true        # не писать заголовки с учетными данными
    ignore_users: [kibanaserver]           # исключить сервисную учетную запись
    ignore_requests: []                    # не логировать выбранные типы запросов
```

Примечания:

* Устаревшие послойные настройки `disabled_rest_categories`/`disabled_transport_categories` заменены единым `disabled_categories`; при одновременном использовании категория отключается, если она есть хотя бы в одном из списков. По умолчанию на транспортном слое отключены `CLUSTER_SETTINGS_CHANGED` и `INDEX_SETTINGS_CHANGED` — удалите их из `disabled_transport_categories`, чтобы отслеживать изменения настроек кластера и индексов.
* В standalone-режиме (только SSL или отключенная безопасность) часть аудиторных настроек (`log_request_body`, `resolve_indices`, `disabled_categories`, `enable_rest`, `ignore_users`) меняется динамически через Cluster Settings API; в режиме FGAC конфигурация живет в `audit.yml` внутри индекса безопасности, и `PUT _cluster/settings` ее не изменит (исключение — `body_logging_exclusions`).
* Индексы аудита растут постоянно — подключите к ним ISM-политику ротации и удаления, чтобы не переполнить кластер собственным журналом безопасности.

### Резервное копирование и восстановление (Snapshots)

Резервное копирование и восстановление OpenSearch (snapshot/restore), автоматизация через Snapshot Management, совместимость версий, security-ограничения при restore и полный план аварийного восстановления вынесены в отдельный документ: [Snapshots и Disaster Recovery](./opensearch-disaster-recovery.md). Там же — регистрация репозиториев (`fs`/`s3`, keystore-секреты), клонирование и очистка снапшотов, состояния снапшота, shallow snapshots и runbook восстановления. Миграция кластера на Remote Store и его настройки остаются в разделе ниже.

### Обновление кластера и миграция на Remote Store

*   **Upgrade Path**: Для перехода на ветку 3.x необходимо сначала обновиться до последнего минорного релиза 2.x — **2.19** (актуальный минор линии 2.x — 2.19.x). Обновляйте через тестовый стенд с копией данных.
*   **Rolling Upgrade to RBS**: Можно перевести кластер с Document Replication на Remote-Backed Storage без простоя:
    1. Включите SegRep на индексах (`index.replication.type: SEGMENT`).
    2. Перед миграцией сделайте снимок и сохраните его удаленно — узлы 2.15+ не могут вернуться к документной репликации.
    3. Разрешите смешанный состав узлов: `PUT _cluster/settings` с `"cluster.remote_store.compatibility_mode": "mixed"` (по умолчанию `strict` — только узлы одного типа).
    4. Направьте новые индексы на remote store: `"cluster.migration.direction": "remote_store"`.
    5. Выполните rolling restart узлов с настроенным remote store (репозитории из `opensearch.yml` регистрируются автоматически при бутстрапе).
    6. После миграции очистите оба служебных параметра (`compatibility_mode`, `migration.direction`).
    * **ВНИМАНИЕ**: Remote store включается только при создании (bootstrapping) кластера и не отключается afterward. Откат к документной репликации требует свежей установки OpenSearch и восстановления из удаленного снимка.

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

Дефолтные лимиты брейкеров (динамические настройки, меняются через `PUT _cluster/settings`):

| Брейкер | Настройка | Дефолт | Назначение |
| :--- | :--- | :--- | :--- |
| Parent (total) | `indices.breaker.total.limit` | 95% heap при `indices.breaker.total.use_real_memory: true` (дефолт); 70% при `false` | Суммарный лимит всех дочерних брейкеров |
| Request | `indices.breaker.request.limit` | 60% heap (overhead 1) | Структуры, строящиеся для запроса (агрегации) |
| Fielddata | `indices.breaker.fielddata.limit` | 40% heap (overhead 1.03) | Загрузка fielddata в кэш |

Parent-брейкер с `use_real_memory: true` оценивает реальное потребление heap — поэтому триппится ближе к 95% занятости heap, а не к сумме дочерних лимитов.

`hot_threads` показывает стек-трейсы потоков, потребляющих CPU — стандартный первый шаг при жалобах на медленные запросы или индексацию. Долгие поисковые задачи ищутся через `GET _tasks?detailed=true&actions=*search*`.

### Пулы потоков, задачи и кэши

```http
# Пулы потоков: активные задачи, очередь, отклонения (рост rejected = насыщение пула)
GET /_cat/thread_pool?v&h=node_name,name,active,queue,rejected

# Отмена долгой задачи (task_id берется из GET /_tasks)
POST /_tasks/<task_id>/_cancel

# Очистка кэшей: освобождает heap, но следующие запросы медленнее до прогрева кэшей
POST /logs-*/_cache/clear
# Точечная очистка: только fielddata, без query/request
POST /logs-*/_cache/clear?fielddata=true&query=false&request=false

# Перечитать secure settings из keystore без рестарта узлов (после opensearch-keystore add)
POST /_nodes/reload_secure_settings
```

`active` и `queue` — мгновенные значения, `rejected` и `completed` — кумулятивные с момента старта узла. Очистка кэшей применима только к открытым индексам; параметр `file=true` очищает неиспользуемые записи файлового кэша на узлах с ролью `search`.

### Ручное управление размещением шардов

```http
# Тест команды без применения (обязательно перед продакшеном)
POST /_cluster/reroute?dry_run=true
{
  "commands": [
    { "move": { "index": "logs-app-2026.08.23", "shard": 0, "from_node": "node-1", "to_node": "node-2" } },
    { "allocate_replica": { "index": "logs-app-2026.08.23", "shard": 1, "node": "node-3" } }
  ]
}

# Повторить неудавшиеся размещения после нестабильности кластера
POST /_cluster/reroute?retry_failed=true
```

Команды `move` (шард в состоянии STARTED), `cancel` (для primary требуется `allow_primary=true`) и `allocate_replica` выполняются под контролем allocation deciders; параметр `explain=true` расписывает решения. Команды `allocate_stale_primary`/`allocate_empty_primary` приводят к потере данных и требуют явного `accept_data_loss: true` — применяются только при восстановлении после катастрофы.

### Сводная статистика и ожидание готовности

```http
# Сводка по кластеру: индексы, шарды, ОС, процесс (human-читаемые размеры)
GET /_cluster/stats?human

# Детализация по узлам: ОС, процесс, HTTP, ingest, пулы потоков
GET /_nodes/stats/os,process,http,ingest,thread_pool?pretty

# Индексы с проблемным здоровьем
GET /_cat/indices?v&health=red

# Ожидание green-статуса до 50 секунд (удобно в скриптах и CI/CD)
GET /_cluster/health?wait_for_status=green&timeout=50s
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
*   **Мониторинг heap и watermarks**: алерты на `heap.percent > 75`, использование диска > 80%, рост `breakers.parent.tripped` и рост `rejected` в пулах `write`/`search` (`_cat/thread_pool`).
*   **Размер bulk-запросов**: 3-5 МиБ как стартовая точка; gzip-сжатие ответов активируется заголовком `Accept-Encoding: gzip` — современные клиенты отправляют его автоматически, убедитесь, что прокси/балансировщик не strip'ит его.

### Типовые проблемы кластера и их решение

1.  **Красный статус кластера**: выполните `_cluster/allocation/explain` по проблемному шарду. Типовые причины — flood_stage watermark (освободите диск, снимите блок `read_only_allow_delete`), отказ узла с единственной копией данных (восстановление из snapshot), повреждение диска. Не перезапускайте кластер хаотично — сначала объяснение, потом действие.
2.  **Желтый статус после добавления индексов**: проверьте `_cat/allocation` — чаще всего недостаточно узлов данных для числа реплик либо достигнут лимит шардов. Временное снижение числа реплик (`index.number_of_replicas: 1`) возвращает green.
3.  **Ошибка `cluster_block_exception` при записи**: индекс заблокирован flood_stage. Решение описано выше (освободить место до уровня ниже high-watermark, снять блок).
4.  **Circuit breaker exception / heap > 85%**: найдите виновника через `hot_threads` и `_tasks`; типовые источники — гигантские агрегации (terms size в тысячи бакетов), fielddata на text-полях, чрезмерное число мелких шардов на узел.
5.  **Отставание реплик в SegRep**: `_cat/segment_replication` показывает лаг; при постоянном отставании проверьте сеть между узлами и включите обратное давление (segment replication backpressure), чтобы запись не обгоняла репликацию бесконтрольно.
6.  **Рост очереди pending tasks**: долгие обновления метаданных (массовое создание индексов, шаблонов) блокируют публикацию состояния кластера. Проверьте, кто генерирует операции с метаданными (ISM, шаблоны, автосоздание индексов приложениями).
7.  **Рост `rejected` в пулах потоков**: `_cat/thread_pool` показывает отклоненные задачи write/search — пул насыщен. Типовые причины: всплеск bulk-нагрузки, медленные поисковые запросы, удерживающие потоки search, или недостаточно узлов под нагрузку. Масштабируйте кластер или оптимизируйте тяжелые запросы (`_tasks`, `hot_threads`).
8.  **Circuit breaker exception**: проверьте `breakers.*.tripped` в `_nodes/stats/breakers` и сверьтесь с таблицей лимитов выше; сначала найдите тяжелый запрос, а повышение лимитов брейкеров используйте как крайнюю меру — это прямой путь к OutOfMemoryError.

---
## См. также

*   **[OpenSearch: Обзор системы](./opensearch_overview.md)** — архитектура и основные компоненты.
*   **[OpenSearch Dashboards: Визуализация и Управление](./opensearch_dashboards.md)** — подробное руководство по веб-интерфейсу.
*   **[Управление жизненным циклом (ISM)](./opensearch_ism_lifecycle.md)** — автоматизация ротации индексов.
*   **[OpenSearch: Траблшутинг индексации](./opensearch_troubleshooting_indexing.md)** — диагностика проблем индексации и сегментов.
*   **[OpenSearch: Capacity Planning](./opensearch_capacity_planning.md)** — проектирование кластера и расчет мощностей.
*   **[Безопасность: TLS и SSO](./opensearch-security-tls-sso.md)** — конфигурация TLS, LDAP/SAML, roles mapping.
*   **[Апгрейды OpenSearch](./opensearch-upgrades.md)** — rolling upgrade: порядок нод и правила версий.
*   **[Снапшоты и восстановление](./opensearch-disaster-recovery.md)** — резервное копирование и план восстановления.
