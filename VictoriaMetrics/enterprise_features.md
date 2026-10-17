# VictoriaMetrics Enterprise: расширенные функции

**Актуально для:** VictoriaMetrics v1.154.x (Community) / v1.148.x LTS (Enterprise)

## Определения

**VictoriaMetrics Enterprise** — платная редакция с расширенными производственными функциями поверх той же data-модели/формата хранения, что и Community. Модель данных и формат хранения **идентичны** — переход Community→Enterprise не требует переиндексации или миграции данных (нужен файл лицензии и включение флагов).

**Лицензирование** — подписка на инстансы; запуск с расширенными флагами требует наличие лицензионного ключа (флаги серии `-license...`). Без ключа Enterprise-сборка предоставляет набор только базовых функций.

**Enterprise-лицензия** — base64-кодированный ключ, содержащий: срок действия, лимит активных узлов/инстансов, набор разрешённых функций. Загружается через `-license=<ключ>` или `-licenseFile=/path/to/file`. При использовании `-licenseFile` ключ перечитывается с интервалом `-licenseFile.reloadInterval` (по умолчанию 1 h) без перезапуска компонента.

**FIPS 140-3** — режим Enterprise-сборки, использующий криптографический модуль Go FIPS 140-3 (начиная с v1.118.0) для соответствия требованиям ФОРМС. Доступен для amd64 и arm64.

**vmgateway** — Enterprise-компонент над vmauth: JWT/OIDC-аутентификация, тенантные ACL, rate limiting (RPS) и прокси для записи/чтения.

**vmbackupmanager** — утилита Enterprise для автоматизации регламентного резервного копирования (hourly/daily/weekly/monthly) и retention-политики. Управляется через CLI или HTTP API на порту `:8300`.

**Storage node groups** — Enterprise-функция: группы `vmstorage`, изолирующие данные определённых тенантов на выделенных узлах хранения.

**mTLS (mutual TLS)** — двусторонняя проверка сертификатов. Enterprise-уровень: TLS на входящих запросах (`-tls`, `-mtls`, `-mtlsCAFile`) и TLS между компонентами кластера (`-cluster.tls*`).

**Global querying** — возможность запрашивать данные из нескольких инстансов/кластеров через один эндпоинт vmselect с `-globalRouting`.

**Query execution stats** — сбор статистики выполнения запросов (время, количество прочитанных строк, использованная память) для диагностики медленных запросов. Включается флагом `-search.logQueryStats` (Enterprise).

**Automatic vmstorage discovery** — автоматическое обновление списка узлов `vmstorage` на `vminsert` и `vmselect` без перезапуска через DNS+SRV записи.

## Базовые концепции

### Ключевые Enterprise-функции VictoriaMetrics

| Функция | Где | Что даёт |
| :--- | :--- | :--- |
| **Downsampling** | vmstorage / single-node | Автоматическая агрегация старых данных (уменьшение занимаемого места, типично для периода >30д). Flags: `-downsampling.period` (простой) и `-retentionFilter` с YAML-правилами `interval`/`offset` (Granular, per-series) — Enterprise |
| **Per-series retention filters** | vmstorage / single-node | Разное хранение для разных серий (`-retentionFilter` с `retentionPeriod`) |
| **vmbackupmanager** | vmbackup | Планировщик бэкапов + retention (хранить N копий/периоды) — Enterprise. CLI: `vmbackupmanager backup list/lock/unlock`, `restore create/get/delete` |
| **vmgateway** | отдельный компонент | JWT/OIDC-аутентификация, тенантные ACL и rate limiting (RPS) шлюз к VM; proxy для записи/чтения — Enterprise |
| **Storage node groups** | cluster | Изоляция данных тенантов на выделенных группах `vmstorage` — Enterprise |
| **Per-tenant statistics** | vmselect | Метрики использования по тенантам (объём записанных серий, запросов, размер индекса) — Enterprise |
| **vmalert multitenancy** | vmalert | Изоляция правил алертинга по тенантам (`-clusterMode=true`) — Enterprise |
| **Rules from Object Storage** | vmalert | Чтение alerting/recording rules из S3/GCS/Azure Blob — Enterprise |
| **Доп. функции MetricsQL** | vmselect | `histogram_quantiles` и др. (см. также [metricsql_reference.md](./metricsql_reference.md)) — Enterprise |
| **vmanomaly** | отдельный компонент | Anomaly detection для метрик (модельный ML-сервис) — Enterprise |
| **Streaming Aggregation (vmagent)** | vmagent | Агрегация на стороне агента (Enterprise-расширение, но базовый `-streamAggr.*` доступен в Community) |
| **mTLS** | все компоненты | `-tls`/`-mtls`/`-mtlsCAFile` на HTTP-портах; `-cluster.tls*` между vminsert/vmselect/vmstorage — Enterprise |
| **Automatic vmstorage discovery** | cluster | DNS+SRV обновление списка vmstorage без перезапуска (`-storageNode` через SRV) — Enterprise |
| **Query execution stats** | vmselect | Статистика выполнения запросов (`-search.logQueryStats`) — Enterprise |
| **Global querying** | vmselect | Запросы через несколько инстансов/кластеров (`-globalRouting`) — Enterprise |
| **Kafka integration** | vmagent | Чтение/запись метрик из/в Kafka — Enterprise |
| **Google PubSub integration** | vmagent | Чтение/запись метрик через Google PubSub — Enterprise |
| **IP filters (vmauth)** | vmauth | Ограничение доступа по CIDR/адресам (`ip_filters`) — Enterprise |
| **mTLS-based routing (vmauth)** | vmauth | Маршрутизация по полям субъекта TLS-сертификата (OU, O, CN) — Enterprise |
| **Automatic TLS certificates** | все компоненты | Автоматическая выдача сертификатов Let's Encrypt (`-tlsAutocert*`) — Enterprise |
| **FIPS 140-3** | все компоненты | Совместимость с криптографическим модулем Go FIPS — Enterprise (с v1.118.0) |
| **Monitoring of Monitoring (MoM)** | отдельный сервис | Прогнозирование и предотвращение проблем в инфраструктуре VM — Enterprise |

> Подробности mTLS, vmgateway, IP filters и аутентификации — в [Руководстве по безопасности](./security.md). CLI-команды vmbackupmanager — в [vmbackup_restore.md](./vmbackup_restore.md). Enterprise-функции vmagent и streaming aggregation — в [vmagent_overview.md](./vmagent_overview.md).

### Архитектура лицензирования и запуска

```
┌──────────────────────────────────────────────────┐
│  Enterprise-бинарник / Docker image               │
│  (суффикс -enterprise в имени / теге)             │
│  -license=KEY  или  -licenseFile=/path/to/key    │
│  -licenseFile.reloadInterval=1h   (перезагрузка без рестарта)│
│  -license.forceOffline=true       (offline-проверка ключа)    │
├──────────────────────────────────────────────────┤
│  Функции активируются при старте:                 │
│  - Если лиценза валидна → все Enterprise-фичи     │
│  - Если лиценза истекла/отсутствует → только    │
│    Community-функции, компонент продолжает работу │
│    до следующего перезапуска                       │
└──────────────────────────────────────────────────┘
```

Enterprise-компоненты доступны как:

| Метод | Пример | Примечание |
| :--- | :--- | :--- |
| **Binary release** | `victoria-metrics-linux-amd64-v1.154.0-enterprise.tar.gz` | В имени файла суффикс `-enterprise` |
| **Docker image** | `victoriametrics/victoria-metrics:v1.154.0-enterprise` | Суффикс `-enterprise` в теге |
| **Helm chart** | `image.tag: v1.154.0-enterprise` + `license.key/secret` | Ключ через `values.yaml` или K8s Secret |
| **K8s Operator** | `spec.license.key/keyRef` + `image.tag: v1.154.0-enterprise` | CRD VMSingle/VMCluster  |

### Зачем это в заметках

На прод-e решения «долго хранить дешевле» и «изолировать тенантов» упираются в эти функции: интервью «чем Enterprise отличается, когда оправдан», и задачи оптимизации затрат хранения без потери гранулярности.

Enterprise оправдан, когда нужны: долгосрочное хранение (downsampling/retention filters), высокая доступность с изоляцией тенантов (storage node groups, vmgateway ACL), автоматизация бэкапов (vmbackupmanager), аналитика качества (per-tenant stats, query stats), продвинутая маршрутизация и аутентификация (mTLS, IP filters), compliance (FIPS), или anomaly detection без ручных порогов.

## Практические сценарии

### 1. Downsampling (агрегация старых серий)

Снижает объём для периодов, где нужен тренд, но не point-точность. Есть два подхода:

**Простой (single-node и vmstorage):**

```bash
# -downsampling.period=offset:interval
# Для данных старше 30 дней оставить 1 sample на 10 минут
victoria-metrics \
  -storageDataPath=/var/lib/victoria-metrics \
  -downsampling.period=30d:10m \
  -license=enterprise-key
```

**Гранулярный (per-series через YAML):**

```yaml
# downsamplingFilter.yml (флаг -downsamplingFilter=...)
- match: '{__name__=~"node_(cpu|mem).*"}'
  interval: 5m          # агрегация в 5-минутные значения
  offset: 168h          # начинается после недели
```

- Задаётся на `vmstorage`/single-node; флаг `-downsamplingFilter=/path/to/file.yml` (в cluster также может указываться per-node);
- Запускайте в «окно»: применение проходит в фоне и создаёт доп. merge-нагрузку;
- Не затрагивает горячие данные (offset начинается применяться с указанного сдвига от now());
- `-downsampling.period` (простой) и `-downsamplingFilter` (YAML) — взаимно дополняют друг друга: простой задаёт глобальное правило, YAML — per-series.

Подробности: [downsampling в overview.md](./overview.md) и [отладка в vmui](./vmui_overview.md).

### 2. Per-series retention filters

Для длительного хранения только важных серий:

```yaml
# retentionFilter.yml
- match: '{env="prod"}'                       # серии прода
  retentionPeriod: 90d
- match: '{__name__=~"node_cpu_seconds_total"}'  # CPU — 30 дней
  retentionPeriod: 30d
- match: '{__name__=~".*"}'  # всё прочее — базовый
  retentionPeriod: 7d
```

Преимущество: гранулярность/место управляются per-series, а не одним `-retentionPeriod` для всех.

### 3. vmgateway (аутентификация и маршрутизация)

```bash
# Шлюз с JWT: клиенты аутентифицируются, а доступ к записи/чтению ограничивается правами
vmgateway \
  -httpListenAddr=:8431 \
  -auth.token=$GATEWAY_TOKEN \
  -write.url=http://vminsert:8480/insert/0/prometheus/ \
  -read.url=http://vmselect:8481/select/0/prometheus/
```

- Клиент шлёт `Authorization: Bearer <jwt>`; gateway проверяет и проксирует;
- Удобно как внешняя точка доступа для команд без предоставления прямого доступа к vmauth/vminsert.
- Поддерживает tenant-ACL и rate limiting (RPS) — детали в [security.md](./security.md).

### 4. vmbackupmanager: планирование и retention бэкапов

```bash
vmbackupmanager \
  -storageDataPath=/var/lib/vmstorage \
  -snapshot.createURL=http://vmstorage-0:8482/snapshot/create \
  -dst=s3://backups/victoria-cluster/0 \
  -run="0 2 * * *"        # cron-выражение: каждый день в 02:00
```

- Автоматически делает снапшот и инкремент по расписанию (`-run`);
- Retention (хранить последние N копий / по времени) задаётся отдельной конфигурацией — сверяйтесь с официальной документацией (раздел `vmbackupmanager`);
- Плановая ротация избавляет от ручных CRON-скриптов чистки.

CLI-команды vmbackupmanager и HTTP API (порт `:8300`) — подробно в [vmbackup_restore.md](./vmbackup_restore.md).

### 5. Streaming aggregation в vmagent (кратко)

Флаг `-streamAggr.config=/path/streamAggr.yml` (подробно — в [vmagent_overview.md](./vmagent_overview.md), секция Streaming Aggregation).

Для Enterprise доступен `-streamAggr.keepDataFor` — per-stream retention для агрегированных серий (удаление необновляемых агрегатов через интервалы).

### 6. Per-tenant statistics (vmselect)

Enterprise-сборка `vmselect` предоставляет метрики использования по тенантам — объём записанных серий, запросов, размер индекса:

```bash
# Включить per-tenant персонализированную статистику
vmselect -httpListenAddr=:8481 \
  -envflag.enable \
  -envflag.prefix=VM_ \
  -search.logQuery=true          # логировать запросы по тенантам (на скорость)
  -pprof                         # pprof на /debug/pprof
```

Метрики для мониторинга:

```bash
# Серии и запись по тенантам
curl -s http://vmselect:8481/metrics | grep -E 'vm_tenant_series_count|vm_tenant_rows_inserted'
# → метрики с меткой `account_id=<tenant_id>`
```

### 7. Storage node groups (cluster)

Изоляция тенантов на выделенных группах `vmstorage` — Enterprise-функция, позволяющая привязывать тенантов к конкретным storage-узлам:

```yaml
# cluster/vmstorage-group.yaml ( CRD, если используется VictoriaMetrics Operator )
apiVersion: VictoriaMetrics.com/v1beta1
kind: VMStorage
metadata:
  name: vmstorage-group-a
spec:
  storageNodeID: 1           # привязка к storageNodeID=1
  # ...
```

Флаг на `vmselect`/`vminsert`:

```bash
# vmselect: чтение с конкретной группы storage
vmselect -storageNodeGroups='group1=1:2:3'   # тенанты из группы group1 → vmstorage 1,2,3
# vminsert: запись в конкретную группу
vminsert -storageNodeGroups='group1=4:5'     # тенанты из группы group1 → vmstorage 4,5
```

Требования — см. [cluster_operations.md](./cluster_operations.md) секцию о storage node groups и [security.md](./security.md) для изоляции сети между группами.

### 8. vmanomaly (anomaly detection)

```bash
# vmanomaly: сервис anomaly detection
vmanomaly \
  -httpListenAddr=:8428 \
  -loggerLevel=DEBUG \
  -configFile=/etc/vmanomaly/config.yml
```

```yaml
# /etc/vmanomaly/config.yml
# (конфигурация моделей, dataset и алертов — сверяйтесь с официальной документацией vmanomaly)
models:
  - name: "cpu_anomaly_model"
    type: isolation_forest
    metrics:
      - name: "node_cpu_seconds_total"
        # ...
```

vmanomaly — отдельный сервис с ML-моделями; требует лицензии и отдельных ресурсов (CPU). Подробности — в [overview.md](./overview.md) и [operator_overview.md](./operator_overview.md).

### 9. License management и деплой

**Binary release:**

```bash
# Скачать enterprise-бинарник
wget https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/v1.154.0/victoria-metrics-linux-amd64-v1.154.0-enterprise.tar.gz
tar xzf victoria-metrics-linux-amd64-v1.154.0-enterprise.tar.gz

# Запуск с ключом
./victoria-metrics-prod -license=BASE64_ENCODED_LICENSE_KEY
# Или через файл (перезагружается без рестарта)
./victoria-metrics-prod -licenseFile=/path/to/vm-license
```

**Docker / docker-compose:**

```bash
docker run --name=victoria-metrics \
  victoriametrics/victoria-metrics:v1.154.0-enterprise \
  -license=BASE64_ENCODED_LICENSE_KEY
```

```yaml
# docker-compose.yml
version: "3.5"
services:
  victoriametrics:
    container_name: victoriametrics
    image: victoriametrics/victoria-metrics:v1.154.0-enterprise
    volumes:
      - vmdata:/storage
      - /vm-license:/vm-license
    command:
      - "-storageDataPath=/storage"
      - "-licenseFile=/vm-license"
volumes:
  vmdata: {}
```

**Helm (K8s):**

```yaml
# values.yaml
server:
  image:
    tag: v1.154.0-enterprise
  license:
    key: BASE64_ENCODED_LICENSE_KEY
```

```yaml
# Или через Kubernetes Secret
server:
  image:
    tag: v1.154.0-enterprise
  license:
    secret:
      name: vm-license
      key: license
```

```bash
kubectl create secret generic vm-license --from-literal=license=BASE64_ENCODED_LICENSE_KEY
```

**Kubernetes Operator (VMSingle/VMCluster):**

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMSingle
metadata:
  name: example-vmsingle
spec:
  license:
    keyRef:
      name: vm-license
      key: license
  image:
    tag: v1.154.0-enterprise
```

**Обновление ключа без перезапуска** (через `-licenseFile`):

```bash
# Перезаписать файл — компонент перечитает через reloadInterval (по умолчанию 1h)
cat new-license.key > /path/to/vm-license
```

**FIPS 140-3 (Enterprise):**

```bash
# FIPS-совместимый Docker образ (base: scratch)
docker run --name=victoria-metrics \
  victoriametrics/victoria-metrics:v1.154.0-enterprise-fips \
  -license=BASE64_ENCODED_LICENSE_KEY
```

FIPS-бинарники доступны для amd64 и arm64 начиная с v1.118.0. Содержат отдельный бинарник `victoria-metrics-fips`.

### 10. Чтение правил алертинга из Object Storage (vmalert)

Enterprise-версия `vmalert` может загружать alerting и recording правила напрямую из S3/GCS/Azure Blob, а не только из локальных файлов и HTTP-URL:

```yaml
# vmalert config: правила из S3
-rule=s3://bucket/rules/*.yml
-credentialsFile=/etc/vmalert/s3-creds
```

- Поддерживается `s3://`, `gs://`, `azblob://` префиксы в `-rule`;
- Для аутентификации используются те же флаги, что и в `vmbackup` (`-credsFilePath`, `-customS3Endpoint`);
- Подробности: [vmalert_overview.md](./vmalert_overview.md) и [vmalert_rules_management_with_manifests.md](./vmalert_rules_management_with_manifests.md).

### 11. Автоматическое обнаружение vmstorage (DNS+SRV)

Enterprise позволяет `vminsert` и `vmselect` автоматически обновлять список узлов `vmstorage` через DNS SRV-записи, без перезапуска при масштабировании:

```bash
# vminsert: SRV-запись _vmstorage._tcp.example.com
vminsert -storageNode=srv:_vmstorage._tcp.example.com

# vmselect: аналогично
vmselect -storageNode=srv:_vmstorage._tcp.example.com
```

- Экономит ручное обновление `-storageNode` при горизонтальном масштабировании;
- Требует Enterprise-лицензии; настраивается через Operator CRD `VMCluster` или флаги бинаря.

### 12. Query execution stats и Global querying

**Query execution stats** — диагностика медленных запросов (количество прочитанных строк, время, память):

```bash
# Включить статистику на vmselect
vmselect -search.logQueryStats=true
# → в ответе /api/v1/query добавляется поле `metrics` с breakdown
```

**Global querying** — один `vmselect` запрашивает данные из нескольких инстансов/кластеров:

```bash
# vmselect с поддержкой глобального роутинга
vmselect -globalRouting=true \
  -storageNode=10.0.0.1:8482 \
  -storageNode=10.0.1.1:8482  # storage из разных кластеров/AZ
```

- Агрегирует результаты из всех `-storageNode` в одном ответе;
- Подходит для cross-cluster dashboards без federативного Prometheus.

## Валидация установки

```bash
# Лицензия загружена корректно
curl -s http://localhost:8428/api/v1/status/buildinfo | jq -r '.data.productName'
# → VictoriaMetrics (cluster/node) [enterprise]

# Downsampling/retention фильтр активен
curl -s http://vmstorage-0:8482/flags | grep -E "retentionFilter|downsamplingPeriod|downsamplingFilter"

# Per-tenant statistics — есть метрики с account_id
curl -s http://vmselect:8481/metrics | grep 'vm_tenant_' | head -3

# Storage node groups — видна конфигурация
curl -s http://vminsert:8480/flags | grep storageNodeGroups

# vmanomaly живой
curl -s http://localhost:8428/health

# Лицензия не истекла (метрикa на /metrics)
curl -s http://localhost:8428/metrics | grep -E 'vm_license_expires_at|vm_license_expires_in_seconds'

# Query execution stats включены
curl -s 'http://vmselect:8481/select/0/prometheus/api/v1/query?query=up' | jq '.metrics'
# → объект с breakdown статистики выполнения

# vmbackupmanager API доступен (Enterprise)
curl -s http://localhost:8300/api/v1/backups | jq .

# vmgateway alive (Enterprise шлюз)
curl -s http://localhost:8431/health
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Функция недоступна / «trial expired» | Лицензия истекла/не загружена | Обновить ключ; проверить `-license`/`-licenseFile` флаги |
| `-licenseFile` не перезагружает ключ | `reloadInterval` слишком большой | Установить `-licenseFile.reloadInterval=1m` для теста |
| Downsampling не применяется | Ошибка в YAML / не тот формат `match` | Проверить синтаксис YAML, `victoria-metrics log` |
| `-downsamplingFilter` не распознаётся | Флаг только в Enterprise | Проверить `-license`, сборка `[enterprise]` в buildinfo |
| vmbackupmanager не бэкапит | `-snapshot.createURL` неверный / нет прав | Убедиться что snapshot-эндпоинт отвечает |
| Per-series retention не учитывается | Формат совпал раньше (первый matching) | Упорядочить правила от частного к общему |
| Per-tenant statistics пустые | `-pprof`/`-search.logQuery` не включены | Включить флаги, перезапустить vmselect |
| Storage node groups не работают | `vmstorage` без `-storageNodeID` / mismatch с `vminsert` | Проверить `-storageNodeGroups` на всех компонентах |
| vmanomaly не стартует | Конфиг неверный / модель не загружена | Проверить `-configFile`, логи vmanomaly |
| vmgateway отклоняет запросы | JWT-ключ неверный / ACL | Проверить `-auth.token`, tenant-правила в конфиге |
| Query stats пустые | `-search.logQueryStats` не включён | Включить флаг, перезапустить vmselect |
| Global querying не агрегирует | `-globalRouting` не включён | Включить флаг на vmselect |
| FIPS-билд не работает | Использован не FIPS-образ | Использовать `victoriametrics/victoria-metrics:v1.154.0-enterprise-fips` |
| IP filters vmauth не работают | Флаги только в Enterprise vmauth | Проверить сборку vmauth `[enterprise]`, `-license` |

## Рекомендации по эксплуатации

- Переходите на Enterprise только при явной потребности (долгое хранение/изоляция/аномалии) — Community покрывает базовые кейсы;
- Лицензионные ключи храните в секретах (K8s secret / Hashicorp Vault), не коммитьте в Git;
- Используйте `-licenseFile` с `-licenseFile.reloadInterval` вместо `-license` — позволяет обновлять ключ без перезапуска;
- Downsampling и per-series retention **проверяйте на тестовом инстансе** до прод-окна (merge-нагрузка перераспределяет диски);
- Для изоляции тенантов используйте `storage node groups` кластера в сочетании с [vmauth](./vmauth_overview.md);
- Per-tenant statistics включайте только при необходимости — сбор per-tenant метрик добавляет нагрузку на vmselect;
- vmanomaly требует отдельного ресурса (CPU для ML-моделей) — не запускайте на маленьких нодах;
- Настраивайте мониторинг истечения лицензии (`vm_license_expires_in_seconds`) — алерт за 30 и 7 дней до expiry;
- FIPS-сборку используйте только если требуется соответствие ФОРМС/соответствующим регуляторным требованиям;
- Automatic vmstorage discovery (DNS+SRV) упрощает масштабирование, но требует Enterprise.

## Ограничения и особые случаи

- Нет публичного формата Enterprise-данных: бэкапы/restore совместимы между Community/Enterprise, но downsampled-данные не «раскручиваются» обратно в полную гранулярность;
- Streaming aggregation в vmagent — базовый режим доступен в Community (`-streamAggr.*`); Enterprise-расширения (`-streamAggr.keepDataFor`) добавляют per-stream retention; полные исторические исходники следует держать в исходном виде отдельно, если нужны;
- Retention/downsampling применяются фоном: сразу после включения места мало освобождаются — следите за `vm_data_size_*` и `vm_retention_filters_partitions_scheduled`;
- vmanomaly работает как отдельный сервис и не встроен в VictoriaMetrics core — требует собственного конфига и ресурсов;
- При истечении лицензии Enterprise-функции недоступны после перезапуска, но работающие компоненты продолжают работать до следующего рестарта;
- FIPS-билды доступны только для amd64 и arm64 (нет ppc64le/s390x);
- Global querying требует Enterprise на vmselect и согласованной конфигурации `-storageNode` между кластерами;
- Reading rules from Object Storage (vmalert) требует Enterprise-биллинга и доступа к объектному хранилищу;
- Kafka/PubSub integration в vmagent — Enterprise, требует отдельной конфигурации источников/потребителей.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — сравнение Community/Enterprise, флаги, версии;
- [vmagent: Streaming Aggregation](./vmagent_overview.md) — раздел про `-streamAggr.*`;
- [metricsql_reference.md](./metricsql_reference.md) — Enterprise-функции MetricsQL;
- [vmbackup/vmrestore](./vmbackup_restore.md) — бэкап и ротация (vmbackupmanager CLI и API);
- [Операции с кластером](./cluster_operations.md) — storage node groups, RF;
- [Безопасность](./security.md) — vmgateway, mTLS, аутентификация, IP filters;
- [vmauth](./vmauth_overview.md) — mTLS-based routing, IP filters (Enterprise);
- [vmalert](./vmalert_overview.md) — multitenancy, rules from Object Storage;
- [vmestimator](./vmestimator.md) — оценка кардинальности для планирования;
