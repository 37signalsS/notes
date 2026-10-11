# Kibana: Эксплуатация в production

> **Актуально для:** Kibana 8.19 / 9.x

Роли узлов, reverse proxy, таймауты, диагностика, системные индексы, снапшоты и миграции Saved Objects — операционный минимум для промышленной эксплуатации Kibana.

## Определения

* **System indices (`.kibana*`)** — системные индексы Elasticsearch, где хранятся Saved Objects (дашборды, Data Views, настройки), состояния задач Task Manager и служебные данные Kibana. С 8.8.0 основной индекс `.kibana` разбит на несколько индексов `.kibana_*`; отдельно существует `.kibana_task_manager`.
* **Feature state** — набор системных индексов/data stream'ов конкретной функции стека (Kibana, security, Fleet, Watcher). Список — API `GET /_features`. Снапшот с feature state Kibana — единственная штатная откатка после неудачной миграции Saved Objects.
* **Saved Object migration** — переиндексация Saved Objects в формат новой версии, выполняемая Kibana при старте, до запуска плагинов и HTTP-сервера.
* **`node.roles`** — режим работы процесса Kibana: `background_tasks` (фоновые задачи: alerting, reporting, Task Manager), `ui` (обслуживание браузеров) или `*` (все роли, по умолчанию). Self-managed only.
* **basePath** — путь, под которым Kibana обслуживается за reverse proxy (`/kibana`); требует согласованной настройки `server.basePath`, `server.rewriteBasePath` и `server.publicBaseUrl`.

## Основные концепции

### Разделение UI и фоновых задач

Масштабирование Kibana сводится к двум осям: браузерные запросы и фоновые задачи.

* Инстансы с `node.roles: [ui]` обслуживают пользователей, с `node.roles: [background_tasks]` — выполняют alerting, reporting и прочие фоновые job'ы.
* Так тяжёлая генерация отчётов и обработка правил не конкурируют с интерактивной аналитикой; деградация одного типа узлов не бьёт по другому.
* Режим `*` (по умолчанию) подходит для малых сред; разделение начинает оправдываться при нескольких инстансах и заметной фоновой нагрузке.

### Reverse proxy и URL

| Настройка | Назначение | Дефолт |
| :--- | :--- | :--- |
| `server.basePath` | Путь монтирования Kibana за прокси; не может заканчиваться на `/` | не задан |
| `server.rewriteBasePath` | `false` — Kibana ожидает, что прокси **сами срежет** basePath с входящих запросов; `true` — Kibana убирает basePath сам | `false` |
| `server.publicBaseUrl` | Публичный URL (protocol + host + порт + basePath), для корректных ссылок в алертах, email и отчётах; не заканчивается на `/` | не задан |
| `server.host` / `server.port` | Адрес и порт бэкенда | `localhost` / `5601` |

Правило: если `rewriteBasePath: false`, прокси должен проксировать `location /kibana/` и переписывать URI на `/`. Ошибка здесь — классическая причина «бесконечного редиректа» и 404 на статике.

**Протокол.** `server.protocol` принимает `http1`/`http2` (статус — Preview). В **8.19 по умолчанию `http1`**; в **9.x дефолт условный**: `http2`, если включён TLS, иначе `http1` (проверено в исходниках: `schema.conditional` на `ssl.enabled` в ветке main и `defaultValue: 'http1'` в v8.19.0). Для http2 нужен валидный h2c — `server.ssl.enabled: true` и поддерживаемые протоколы ≥ TLSv1.2; строгую проверку можно отключить через `server.http2.allowUnsecure: true`.

### Таймауты Kibana → Elasticsearch

| Настройка | Дефолт | Смысл |
| :--- | :--- | :--- |
| `elasticsearch.requestTimeout` | `30000` мс | Общий таймаут ответа Elasticsearch |
| `elasticsearch.shardTimeout` | `30000` мс | Ожидание ответа от шард (`0` — отключить) |
| `elasticsearch.pingTimeout` | равен `requestTimeout` | Пинг соединения с ES |
| `elasticsearch.maxSockets` | `800` (в 8.19 — `Infinity`) | Максимум сокетов на связку Kibana ↔ ES |
| `elasticsearch.maxIdleSockets` | `256` | Резерв простоя сокетов |
| `elasticsearch.idleSocketTimeout` | `60s` | Закрытие простаивающего сокета; при прозрачном прокси между Kibana и ES значение должно быть ≤ таймаута прокси |
| `elasticsearch.verificationMode` | `full` | Проверка сертификата ES (`full` / `certificate` / `none`) |

Для долгих аналитических запросов (`elasticsearch.shardTimeout: 0`) учитывайте, что в это время держится сокет из `maxSockets`.

**Остановка:** `server.shutdownTimeout` (по умолчанию `30s`) — грейс-период после SIGTERM/SIGINT: Kibana пытается завершить текущие HTTP-запросы, новые отклоняет. Важно для перезапусков инстансов по одному (та же версия — это не апгрейд) и подтверждения readiness-пробы.

### Диагностика и логи

```bash
# Состояние: status.overall.level (available / degraded / unavailable / critical);
# 503, пока Kibana не готова (идут миграции Saved Objects или нет связи с Elasticsearch).
# Эндпоинт официально заявлен Elastic как liveness/readiness-проба.
curl -s http://localhost:5601/api/status
# → {"status":{"overall":{"level":"available","summary":"All services are available"},
#     "core":{"elasticsearch":{"level":"available"},"savedObjects":{"level":"available"}},
#     "plugins":{...}},
#    "metrics":{"elasticsearch_client":{"totalActiveSockets":4,"totalIdleSockets":2,
#                "totalQueuedRequests":0},...}, ...}
# ?v7format=true — ответ в старом (7.x) формате, где вместо level — state: green/yellow/red

# Метрики процесса: CPU, память, запросы, соединения с ES
# (тот endpoint, который собирает Metricbeat/Stack Monitoring)
curl -s http://localhost:5601/api/stats
```

* `status.allowAnonymous: false` (дефолт) — доступ к status API и странице статуса без аутентификации закрыт; для проб балансировщика/мониторинга без учётных данных выставьте `true`. Тогда unauth-вызов, как и вызов пользователя без привилегии `monitor`, получает обрезанный (redacted) ответ — только `status.overall.level`; для проверки по HTTP-коду `200`/`503` этого достаточно, полной картины (core/plugins/metrics) такой ответ не содержит.
* `status.statusPageBypassMonitorPrivilege: false` (дефолт) — полный статус доступен аутентифицированным пользователям только с кластерной привилегией Elasticsearch `monitor`, без неё ответ redacted. Актуально, только пока `status.allowAnonymous: false`.
* Насыщение соединений с Elasticsearch — блок `metrics` полного ответа `/api/status`: `totalActiveSockets`/`totalIdleSockets`/`totalQueuedRequests` против предела `elasticsearch.maxSockets`; растущие `totalQueuedRequests` при нулевых `totalIdleSockets` — сокетов не хватает.
* Логи: `logging.root.level` (дефолт `info`), `logging.root.appenders` (дефолт — appender `console`), пользовательские логгеры — `logging.loggers[]`. Для DEB/RPM — `journalctl -u kibana.service`, для архивной установки — `path.logs`.
* Перечитывание конфигурации логирования — `SIGHUP` к процессу Kibana.

### Диагностика Task Manager

Правила, отчёты и прочие фоновые задачи исполняет Task Manager (архитектура и настройки `xpack.task_manager.*` — в [Alerting](../Elasticsearch/elasticsearch_alerting.md)). Для диагностики «правила не выполняются / отстают» есть штатный health-эндпоинт:

```bash
# Состояние подсистемы Task Manager
curl -s http://localhost:5601/api/task_manager/_health
# → { "status": "OK", "last_update": ...,
#     "stats": { "capacity_estimation": {...}, "configuration": {...},
#                "runtime": {...}, "workload": {...} } }
```

Что смотреть в ответе:

* `stats.configuration.value` — фактически применённая конфигурация: `poll_interval` (`500` мс), `capacity` (единицы работы за цикл: `config` / `as_workers` / `as_cost`), `claim_strategy` (`mget`), `request_capacity`, пороги `monitored_task_execution_thresholds.default` (`warn_threshold: 80`, `error_threshold: 90` — доля неуспешных выполнений задач, после которой исполнение помечается подозрительным/падающим).
* `stats.capacity_estimation` — грубая оценка sufficiency ёмкости по историческим данным; сам API предупреждает, что это не прогноз. `status`/`value.observed.*` заполняются только на background-нодах.
* `stats.workload` — сводка задач по типам и статусам (какая нагрузка висит в очереди).
* `stats.runtime.value` — измеренные характеристики: `polling` (длительности циклов опроса и `claim_duration`/`claim_conflicts`/`claim_stale_tasks` в p50/p90/p95/p99), `drift` и `drift_by_type` (насколько выполнение отстаёт от расписания — просроченные задачи), `execution` (длительности и результаты по типам задач).
* `stats.runtime.value.polling.result_frequency_percent_as_number` — как часто циклы завершаются с тем или иным результатом; ключевые для диагностики:
  * `NoAvailableWorkers` — цикл не нашёл свободных воркеров: все инстансы в роли `ui`, либо capacity занята долгими задачами;
  * `RanOutOfCapacity` — задач в очереди больше, чем `capacity`: нужно повышать `xpack.task_manager.capacity` либо снижать нагрузку (число правил, интервалы);
  * `NoTasksClaimed` — цикл завершился без захваченных задач; близко к `100%` нормально, когда задач нет, и подозрительно, если `workload` показывает иное.

**Важно:** вызывать `_health` нужно с инстанса, который исполняет задачи. На узлах с `node.roles: [ui]` поля исполнения (`capacity_estimation.status`, `runtime.value.polling.result_frequency_percent_as_number`, `runtime.value.execution.*`, `drift_by_type`) отсутствуют или null — полную картину отдают только background-ноды.

Порядок диагностики «правило молчит»: `GET /api/status` (Kibana жива?) → `GET /api/task_manager/_health` **с background-нода** (подсистема живёт и не в `RanOutOfCapacity`?) → `GET /api/alerting/rule/<id>` (правило включено, `last_run` без ошибок?) → логи. Связанные строки — в разделе Troubleshooting ниже.

**Остановка исполнения задач в инциденте.** Штатной runtime-паузы Task Manager (без рестарта) в релизах нет: в тегах до `v9.5.4` включительно роуты `POST /internal/task_manager/execution/_pause` / `_resume` отсутствуют (есть только в ветке main — проверить по своей версии перед использованием). Доступные в релизе рычаги, оба со рестартом: увести инстансы в `node.roles: [ui]` (см. раздел выше) и experimental `xpack.task_manager.unsafe.exclude_task_types` — unsupported, только для отладки, вызывает неожиданное поведение.

### Telemetry (сбор статистики использования)

Kibana по умолчанию собирает и отправляет обезличенную статистику использования в Elastic. Штатный opt-out на уровне конфигурации:

```yaml
# kibana.yml — фиксированный отказ от сбора
telemetry.optIn: false
telemetry.allowChangingOptInStatus: false   # запрещает менять решение из UI
telemetry.sendUsageFrom: server             # отправка с сервера (дефолт); browser — из браузера
```

* Интерфейсный переключатель — **Advanced Settings → Usage Collection** (без `allowChangingOptInStatus: false` пользователь может снова включить сбор).
* Ключ `telemetry.enabled: false` **устарел** (elastic/kibana#129015 «Deprecate telemetry.enabled: false») и в актуальном configuration reference уже не описан — новые конфигурации задавайте через пару `optIn` / `allowChangingOptInStatus`.
* Настройка относится к Kibana; отдельные компоненты стека имеют собственные параметры телеметрии — для каждого конкретного компонента параметры нужно проверять по его документации.

### Снапшоты системных индексов Kibana

```bash
# Какие feature state'ы доступны в кластере
GET _features

# Снапшот по умолчанию включает feature state (в т.ч. kibana)
PUT _snapshot/backup
{ "type": "fs", "settings": { "location": "/mnt/backup" } }

PUT _snapshot/backup/pre_upgrade?wait_for_completion=true
{ "indices": ["*"], "include_global_state": true }
```

Снапшоты включают feature state **по умолчанию** — отдельно указывать `kibana` не нужно. Без такого снапшота откат после неудачного апгрейда невозможен.

### Апгрейд и миграции Saved Objects

Порядок и ограничения (официальные требования):

1. **Все инстансы Kibana останавливаются перед апгрейдом.** Rolling upgrade не поддерживается; работа смешанной версии Kibana приводит к ошибкам миграции и потере данных.
2. Сначала Elasticsearch, затем Kibana, **той же версии**.
3. Перед стартом — здоровый кластер: свободного диска **не менее чем вдвое больше суммарного размера** индексов `.kibana` и `.kibana_task_manager`, достаточный heap и статус `green`.
4. Для деплоев **>10 инстансов Kibana и >10 000 Saved Objects**: поднять один инстанс, дождаться окончания миграции, затем остальные.
5. Миграция выполняется при старте до плагинов и HTTP; начиная с 7.12 устаревший индекс получает write block.

Чек-лист операции:

* **До:** снапшот с feature state kibana → все инстансы на одной версии, конфигурации и наборе плагинов → диск ≥ 2× размера `.kibana` + `.kibana_task_manager`, кластер `green` → остановить **все** инстансы Kibana → обновить пакеты.
* **После:** запустить инстансы и ждать `GET /api/status` → `200` и `status.overall.level: available` (503 означает, что миграция ещё идёт) → только затем включать в балансировщик → проверить правила и отчёты.

**Откат при неудачной миграции:** остановить все инстансы Kibana → восстановить feature state kibana из снапшота, сделанного до апгрейда → откатить пакеты на прежнюю версию → запустить. Порядок восстановления — в [Disaster recovery](../Elasticsearch/elasticsearch_disaster_recovery.md).

Настройки миграций:

```yaml
migrations.batchSize: 1000            # доков за пачку; меньше — ниже риск OOM/circuit_breaker
migrations.maxBatchSizeBytes: 100mb   # не выше http.max_content_length в ES
migrations.retryAttempts: 15          # повторы временных ошибок (503, таймауты)
migrations.algorithm: v2             # v2 — классический (self-managed, апгрейд с даунтаймом);
                                     # zdt — zero-downtime (Serverless)
# разовое средство при застрявших объектах — указывается версия цели:
migrations.discardUnknownObjects: "9.5.0"
migrations.discardCorruptObjects: "9.5.0"
```

Импорт Saved Objects совместим с той же версией, более новым минором в рамках того же major либо со следующим major — это ограничение стоит учитывать при переносе NDJSON между окружениями.

## Практические сценарии

### Конфигурация кластера Kibana за балансировщиком

```yaml
# kibana.yml (инстанс UI)
server.host: "0.0.0.0"
server.basePath: "/kibana"
server.rewriteBasePath: false          # прокси срезает basePath сам
server.publicBaseUrl: "https://kibana.example.com/kibana"
server.protocol: http2                 # 9.x + TLS; в 8.19 дефолт http1

elasticsearch.hosts: ["https://es-1:9200", "https://es-2:9200"]
elasticsearch.ssl.certificateAuthorities: ["/etc/kibana/certs/ca.crt"]
elasticsearch.requestTimeout: 30000
elasticsearch.shardTimeout: 30000

# Одинаково на всех инстансах за LB (иначе падают reporting-задачи,
# не расшифровываются зашифрованные Saved Objects правил/коннекторов
# и принудительно завершаются сессии):
xpack.reporting.encryptionKey: "..."
xpack.security.encryptionKey: "..."
xpack.encryptedSavedObjects.encryptionKey: "..."   # ≥32 байт; ключи — bin/kibana-encryption-keys generate

# status.allowAnonymous: true   # если пробы LB идут без аутентификации

logging.root.level: "info"
```

```nginx
# nginx: срезаем basePath и отдаём Kibana
location /kibana/ {
    proxy_pass http://kibana_ui:5601/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;      # не меньше elasticsearch.requestTimeout (30s): прокси не должен рвать ответ на долгих запросах к ES
    client_max_body_size 30m;     # для импорта Saved Objects: дефолт nginx — 1m, лимит Kibana — savedObjects.maxImportPayloadBytes (25m)
}
```

### Проверка после выката

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://kibana_ui:5601/api/status
# → 200 и "status":{"overall":{"level":"available"}}; 503 — миграции ещё идут, не включать в LB
```

Проба без аутентификации работает только с `status.allowAnonymous: true`; без неё доступ к status API без учётных данных закрыт (дефолт), а аутентифицированный вызывающий без привилегии `monitor` получает redacted-ответ — для LB-пробы достаточно кода и `overall.level`.

### Резервное копирование конфигурации Kibana

* **Снапшот с feature state kibana** — восстановление состояния (миграции, апгрейды).
* **Экспорт Saved Objects в NDJSON** — GitOps и перенос между окружениями: [Kibana: Поиск, визуализация и управление](./kibana_search_and_visualization.md).
* Оба способа не заменяют друг друга: NDJSON переносит объекты, feature state — состояние целиком.

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `/api/status` отдаёт 503 | Идут миграции Saved Objects либо Kibana не может достучаться до Elasticsearch | Смотреть логи; проверить `elasticsearch.hosts`, сертификаты, версии |
| Бесконечный редирект после настройки basePath | Прокси не срезает путь при `rewriteBasePath: false` (или наоборот) | Согласовать прокси и `server.rewriteBasePath` |
| Ссылки в алертах/email ведут не туда | Не задан или неверен `server.publicBaseUrl` (включая basePath) | Задать полный публичный URL без завершающего `/` |
| «Kibana X.Y.Z deployment detected. Please upgrade to ... before upgrading to 9.x series» | Прыжок через major-версии | Промежуточный апгрейд (например, до 8.19.x), затем 9.x |
| Миграция падает: недостаточно места / circuit breaker | Мало свободного диска относительно `.kibana*`, переполнен heap | Освободить диски (≥ 2× размера `.kibana` + `.kibana_task_manager`), уменьшить `migrations.batchSize` |
| Миграция падает на неизвестных/битых объектах | Остатки отключённых плагинов, повреждённые записи | `migrations.discardUnknownObjects` / `discardCorruptObjects` с версией цели (после резервной копии) |
| Фоновые задачи (alerting, reporting) не выполняются, UI жив | Все инстансы работают в режиме `ui` | Выделить инстансы с `node.roles: [background_tasks]` |
| Правила отстают от расписания / выполняются не вовремя | Task Manager в `RanOutOfCapacity` либо дрейф/просроченные задачи в `_health` | `GET /api/task_manager/_health`: поднять `xpack.task_manager.capacity`, снизить число правил/их интервалы |
| Сессии сбрасываются на часть инстансов | Разные `xpack.security.encryptionKey` за LB | Привести ключи к одинаковым значениям |
| Kibana не завершается по SIGTERM | Долгие запросы держат грейс-период | Увеличить `server.shutdownTimeout` либо сократить тяжёлые запросы |
| Проба балансировщика без аутентификации не получает статус | `status.allowAnonymous: false` (дефолт) — доступ к status API без учётных данных закрыт | Выставить `status.allowAnonymous: true`: unauth-вызов получает redacted-ответ с `status.overall.level`, для пробы по коду `200`/`503` этого достаточно |
| Импорт NDJSON падает с 413 Request Entity Too Large | Прокси режет тело запроса раньше Kibana: `client_max_body_size` в nginx по умолчанию `1m` | Увеличить `client_max_body_size` не меньше `savedObjects.maxImportPayloadBytes` (дефолт `26214400` = 25 МБ; он же перекрывает `server.maxPayload` = `1048576` только для импорта Saved Objects) |
| Импорт NDJSON отклоняет объекты пачкой | Превышен `savedObjects.maxImportExportSize` (дефолт `10000` объектов) | Разбить выгрузку на части либо поднять лимит (осторожно: память Kibana) |
| Правила/коннекторы падают с ошибками шифрования, часть отчётов не генерируется на инстансах | Разные `xpack.encryptedSavedObjects.encryptionKey` (и/или `xpack.reporting.encryptionKey`, `xpack.security.encryptionKey`) на инстансах за LB | Привести ключи к одинаковым значениям; ротация ключа — `xpack.encryptedSavedObjects.keyRotation.decryptionOnlyKeys` + `POST /api/encrypted_saved_objects/_rotate_key` |
| `_health` отдаёт блоки `capacity_estimation` и `runtime` (`polling`, `execution`, `drift`) пустыми или null | Запрос выполнен на инстансе с `node.roles: [ui]` — полную картину отдают только background-ноды | Повторить вызов `GET /api/task_manager/_health` с background-ноды |

## Best Practices

* **Остановка всех инстансов** перед апгрейдом; никогда не смешивать версии Kibana в одном кластере.
* **Всегда снапшот с feature state** перед апгрейдом — это единственный штатный откат.
* **Одинаковые секреты** (`xpack.reporting.encryptionKey`, `xpack.security.encryptionKey`, `xpack.encryptedSavedObjects.encryptionKey`) на всех узлах за LB; генерировать через `bin/kibana-encryption-keys generate`, хранить в `kibana-keystore` (`kibana-keystore add <setting>` — любую валидную настройку).
* **Разделяйте** `ui` и `background_tasks` при нескольких инстансах; health-check LB — `/api/status`, диагностика фоновых задач — `/api/task_manager/_health`.
* **Следите за диском** рядом с `.kibana*` и `.kibana_task_manager`: это система очередей (Task Manager) и объектов, а не только «настройки».
* **Версионируйте** Saved Objects в Git и держите снапшоты — два разных уровня backup'а.
* Мониторинг инстансов и фоновых задач — [Stack Monitoring](../Elasticsearch/elasticsearch_stack_monitoring.md).

## Дополнительная информация

* **[Kibana: Обзор](./kibana_overview.md)** — ресурсы, `kibana.yml`, безопасность.
* **[Kibana: Reporting](./kibana_reporting.md)** — фоновые задачи генерации отчётов и их настройки.
* **[Kibana: Поиск, визуализация и управление](./kibana_search_and_visualization.md)** — Saved Objects, NDJSON, GitOps.
* **[Elasticsearch: Disaster recovery](../Elasticsearch/elasticsearch_disaster_recovery.md)** — снапшоты, feature state, восстановление.
* **[Elasticsearch: Upgrades](../Elasticsearch/elasticsearch_upgrades.md)** — порядок апгрейда компонентов стека.
* **[Alerting: Kibana Alerting и Watcher](../Elasticsearch/elasticsearch_alerting.md)** — Task Manager, правила, connectors.
