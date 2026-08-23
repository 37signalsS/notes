# OpenSearch: Развертывание в Kubernetes с помощью Helm

> Эта заметка является частью обзора [OpenSearch](./opensearch_overview.md) и детально рассматривает процесс развертывания кластера в Kubernetes с использованием официального Helm-чарта, включая настройку отказоустойчивости, безопасности и мониторинга. Первоисточник параметров чарта — [Artifact Hub](https://artifacthub.io/packages/helm/opensearch-project-helm-charts/opensearch) и [репозиторий helm-charts](https://github.com/opensearch-project/helm-charts).

## Определения

* **Helm-чарт OpenSearch**: официальный пакет для автоматизации развертывания и управления жизненным циклом OpenSearch в Kubernetes. Репозиторий публикует два чарта: `opensearch/opensearch` (сам кластер) и `opensearch/opensearch-dashboards` (визуализация). Версии чарта следуют за версиями приложения (chart 3.x = app 3.x).
* **Cluster Manager (ранее Master)**: роль узла, ответственного за координацию кластера. В Helm-чарте настраивается через параметр `roles: [cluster_manager]`.
* **NodeGroup**: группа однотипных узлов, развертываемая одним релизом чарта как отдельный StatefulSet. Имена ресурсов строятся по шаблону `<clusterName>-<nodeGroup>-<ordinal>`; параметр `nodeGroup` по умолчанию — `master`.
* **initContainers**: вспомогательные контейнеры, выполняемые до запуска основного процесса. Используются для настройки `vm.max_map_count` (привилегированный `sysctl-init`) и прав доступа к тому данных (`fsgroup-volume`, отключается `persistence.enableInitChown: false`). Через `extraInitContainers` добавляются пользовательские шаги, например установка плагинов.
* **PodDisruptionBudget (PDB)**: ресурс Kubernetes, гарантирующий наличие минимального количества доступных подов при плановом обслуживании узлов. Чарт создает PDB с `maxUnavailable: 1` для каждой NodeGroup.
* **ServiceMonitor**: ресурс Prometheus Operator для автоматического обнаружения эндпоинтов метрик OpenSearch. Включается параметром `serviceMonitor.enabled: true`; метрики плагина-экспортера отдаются по пути `/_prometheus/metrics`.
* **Remote-Backed Storage (RBS)**: конфигурация OpenSearch 2.15+, позволяющая использовать объектные хранилища (S3/GCS/Azure) как основной уровень хранения через Helm-конфигурацию. Задается атрибутами узла `node.attr.remote_store.*` и включается только при бутстрапе кластера. В документации ветки 3.x именуется **remote store**.
* **securityConfig**: секция чарта для управления конфигурацией плагина безопасности. По умолчанию применяется небезопасная демонстрационная конфигурация (известные пароли) — перед продакшеном обязательна замена через секреты или inline-конфигурацию.

## Основные концепции

### Архитектура развертывания (Node Groups)

Для промышленных сред рекомендуется разделять узлы на специализированные группы (Node Groups), каждая из которых устанавливается как отдельный Helm-релиз:

1.  **Cluster Manager**: минимум 3 узла. Обеспечивают стабильность метаданных. Не должны хранить данные.
2.  **Data (Hot/Warm/Cold)**:
    *   **Hot**: быстрые NVMe SSD для активной записи и поиска.
    *   **Warm/Cold**: HDD или более дешевые хранилища для архивных данных. Настраиваются через `persistence.storageClass`.
3.  **Ingest**: выделенные узлы для тяжелых пайплайнов обработки данных.
4.  **Dashboards**: отдельный чарт для визуализации.

Минимальное развертывание (по умолчанию) — один релиз из трех подов с полным набором ролей (`nodeGroup: master`), чего достаточно для dev/staging. Для production каждая группа — отдельный релиз со своим `values.yaml`.

Механика обнаружения узлов: каждый релиз создает headless-сервис для discovery (порт 9300). Если имя группы cluster manager отличается от `master`, обязательно задайте `masterService` во всех релизах кластера — иначе поды будут искать сервис `<clusterName>-master` и не соберутся в кластер. Параметр `podManagementPolicy: Parallel` (умолчание чарта) запускает поды StatefulSet одновременно, чтобы узлы могли обнаружить друг друга без долгой последовательной прокрутки.

### Жизненный цикл подов и обновления

*   **StatefulSet + PDB**: чарт разворачивает StatefulSet с PDB (`maxUnavailable: 1`) — при дренировании Kubernetes-узла одновременно недоступен максимум один под группы.
*   **updateStrategy**: по умолчанию `RollingUpdate` — StatefulSet обновляет поды по одному и ждет `green`. Значение `OnDelete` дает полный ручной контроль последовательности (полезно при крупных апгрейдах мажорных версий).
*   **terminationGracePeriod** (по умолчанию 120 c): время на корректную остановку процесса — завершение индексации, вывод шарда из размещения. При большом числе шардов на узле увеличьте значение, иначе под будет убит по SIGKILL с последующим дорогим восстановлением.
*   **Probes**: чарт определяет liveness/readiness/startup пробы на HTTP API. Startup probe защищает медленный старт тяжелых узлов (восстановление шардов), readiness исключает под из балансировки до готовности принимать запросы.

### Сетевое взаимодействие и Ingress

* **Headless Service**: используется для `discovery` (порт 9300).
* **Ingress**: рекомендуется для доступа к API (порт 9200) и Dashboards (порт 5601).
    * **Best Practice**: установка аннотации `nginx.ingress.kubernetes.io/proxy-body-size: "50m"` для поддержки больших Bulk-запросов.
    * **Timeouts**: увеличение `proxy-read-timeout` до 300с для тяжелых поисковых запросов.
    * Для TLS-бэкенда (когда сам OpenSearch обслуживает HTTPS) контроллеру nginx нужна аннотация `nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"` либо терминирование TLS на ingress с обычным HTTP к подам.

### Мониторинг и обсервабилити

Интеграция с Prometheus через Helm требует установки плагина `prometheus-exporter` (поддерживается сообществом [Aiven-Open](https://github.com/Aiven-Open/prometheus-exporter-plugin-for-opensearch)). Чарт устанавливает плагины декларативно через секцию `plugins`:

```yaml
plugins:
  enabled: true
  installList:
    # Версия плагина ДОЛЖНА точно совпадать с версией OpenSearch!
    - https://github.com/aiven/prometheus-exporter-plugin-for-opensearch/releases/download/3.1.0.0/prometheus-exporter-3.1.0.0.zip
```

**Критично**: версия плагина обязана побайтово совпадать с мажорно-минорной версией OpenSearch (`Plugin [prometheus-exporter] was built for OpenSearch version 2.17.1 but version 2.18.0 is running`) — при несоответствии поды уходят в CrashLoopBackOff на этапе установки плагинов. При апгрейде кластера URL плагина меняется синхронно с `image.tag`; лишние плагины можно убрать через `plugins.removeList`.

Включение сбора метрик:

```yaml
serviceMonitor:
  enabled: true          # требует установленного Prometheus Operator
  path: /_prometheus/metrics
  scheme: http           # или https при включенном TLS
  interval: 10s
```

Для scheme https настройте `tlsConfig`; для аутентификации скрейпера — `basicAuth` с существующим Secret. Готовый Grafana-дашборд для этого плагина — [ID 20827](https://grafana.com/grafana/dashboards/20827-opensearch/).

* **Безопасность**: рекомендуется создать отдельного пользователя в OpenSearch с ролью `cluster:monitor/prometheus/metrics` для сбора метрик — не используйте учетную запись администратора в конфигурации скрейпера.

Альтернатива плагину — сбор метрик через OpenTelemetry Collector или встроенный Performance Analyzer (порт 9600, параметр `metricsPort`), однако путь `/_prometheus/metrics` плагина остается самым простым для классического Prometheus-стека.

## Практические сценарии

### Быстрый старт (dev/staging)

```bash
# 1. Добавление репозитория чартов
helm repo add opensearch https://opensearch-project.github.io/helm-charts/
helm repo update
# → "opensearch" has been added to your repositories

# 2. Просмотр доступных версий
helm search repo opensearch
# → NAME                          CHART VERSION   APP VERSION   DESCRIPTION
# → opensearch/opensearch         3.x.x           3.x.x         A Helm chart for OpenSearch
# → opensearch/opensearch-dashboards  3.x.x       3.x.x         A Helm chart for OpenSearch Dashboards
```

Минимальный `values-dev.yaml` для одиночного узла:

```yaml
singleNode: true          # discovery.type=single-node; replicas принудительно =1

extraEnvs:
  - name: OPENSEARCH_INITIAL_ADMIN_PASSWORD
    value: "MyStr0ngP@ssw0rd!"   # обязателен начиная с OpenSearch 2.12

resources:
  requests:
    cpu: "500m"
    memory: "2Gi"

persistence:
  enabled: true
  size: 30Gi

sysctlInit:
  enabled: true           # привилегированный initContainer выставит vm.max_map_count
```

```bash
helm install os-dev opensearch/opensearch -f values-dev.yaml

# Ожидание готовности пода
kubectl get pods -w
# → os-dev-opensearch-master-0   1/1   Running   0   4m

# Проверка API из пода кластера
kubectl run curl --rm -it --image=curlimages/curl -- \
  curl -ku admin:MyStr0ngP@ssw0rd https://os-dev-opensearch-master:9200
# → {"cluster_name":"opensearch-cluster","version":{"number":"3.x.x",...},"tagline":"The OpenSearch Project: https://opensearch.org/"}
```

Требования к окружению: Kubernetes >= 1.14, Helm >= 2.17, минимум 8 ГиБ свободной памяти на трехнодовый дефолтный деплой (при менее чем 4 ГиБ деплой падает).

### Настройка Remote Store (RBS) в values.yaml

Remote store — настройка уровня кластера, включаемая **только при бутстрапе**; после создания кластера включить или выключить ее нельзя. Все узлы обязаны иметь идентичные настройки атрибутов — иначе бутстрап узлов с отличающимися атрибутами завершится ошибкой. Три репозитория (сегменты, translog, состояние кластера) могут указывать на один и тот же bucket.

Актуальный синтаксис (задается как атрибуты узла в `opensearch.yml`):

> **Историческая справка**: ранние руководства эпохи OpenSearch 2.15 задавали remote store ключами уровня кластера (`cluster.remote_store.enabled`, `cluster.indices.replication.strategy: SEGMENT`, `cluster.remote_store.state.enabled`) и помечали вынос состояния кластера в S3 как экспериментальное. Эти ключи не соответствуют текущей документации — при апгрейде с 2.15-конфигурации перенесите настройки в формат `node.attr.*` до бутстрапа новых узлов.

```yaml
config:
  opensearch.yml: |-
    # Имена репозиториев как атрибуты узла
    node.attr.remote_store.segment.repository: my-s3-repo
    node.attr.remote_store.translog.repository: my-s3-repo
    node.attr.remote_store.state.repository: my-s3-repo

    # Определение репозитория (type + settings)
    node.attr.remote_store.repository.my-s3-repo.type: s3
    node.attr.remote_store.repository.my-s3-repo.settings.bucket: opensearch-rbs-bucket
    node.attr.remote_store.repository.my-s3-repo.settings.base_path: rbs/segments
    node.attr.remote_store.repository.my-s3-repo.settings.region: us-east-1

plugins:
  enabled: true
  installList:
    - repository-s3        # плагин обязателен для работы с S3
```

Репликация при remote store работает по стратегии сегментов (segment replication): данные индексов физически живут в объектном хранилище, поэтому для индексов задается `index.replication.type: SEGMENT` (индексный сеттинг; в экспериментальных руководствах 2.15 он ошибочно указывался как кластерный `cluster.indices.replication.strategy`).

Плагин `repository-s3` можно установить и через initContainer (подходит, когда нужно скачать дистрибутив из внешнего источника):

```yaml
extraInitContainers:
  - name: install-plugins
    image: opensearchproject/opensearch:3.1.0
    command: ['sh', '-c', 'bin/opensearch-plugin install --batch repository-s3']
```

Во время бутстрапа перечисленные в `opensearch.yml` репозитории регистрируются автоматически; все создаваемые после этого индексы начинают писать данные в remote store. Сопутствующие настройки уровня кластера (`cluster.default.index.refresh_interval`, `cluster.remote_store.translog.buffer_interval` и другие) тюнят поведение записи. Экосистема вокруг механизма (миграция существующего кластера, вынос состояния кластера, backpressure, shallow snapshots) описана в [Администрирование OpenSearch](./opensearch_administration.md).

### Развертывание промышленного кластера

1.  **Настройка TLS (Cert-manager)**:
    Используйте сертификаты от `cert-manager` для автоматизации. Создайте Secret `opensearch-certs` и смонтируйте его:
    ```yaml
    secretMounts:
      - name: opensearch-certs
        secretName: opensearch-certs
        path: /usr/share/opensearch/config/certs
    ```
2.  **Установка Node Groups**:
    ```bash
    # Установка менеджеров
    helm install os-mgr opensearch/opensearch -f values-mgr.yaml
    # Установка дата-узлов (Hot)
    helm install os-data-hot opensearch/opensearch -f values-data-hot.yaml
    ```

Референсный `values-mgr.yaml` (группа cluster manager):

```yaml
nodeGroup: master
roles:
  - cluster_manager
replicas: 3

resources:
  requests:
    cpu: "500m"
    memory: "2Gi"
  limits:
    cpu: "1000m"
    memory: "2Gi"

persistence:
  enabled: false          # метаданные малы и живут в кворуме

antiAffinity: "hard"      # менеджеры строго разнесены по Kubernetes-узлам
```

Референсный `values-data-hot.yaml`:

```yaml
nodeGroup: data-hot
masterService: os-mgr-opensearch-master   # имя сервиса группы master!
roles:
  - data
replicas: 6

opensearchJavaOpts: "-Xms8g -Xmx8g"
resources:
  requests:
    cpu: "2000m"
    memory: "10Gi"
  limits:
    cpu: "4000m"
    memory: "10Gi"

persistence:
  enabled: true
  size: 500Gi
  storageClass: fast-nvme

topologySpreadConstraints:            # равномерность по зонам доступности
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        app.kubernetes.io/name: opensearch
```

Каждая следующая группа (warm, ingest, coordinating) добавляется аналогичным релизом со своим набором `roles`. Для групп с нестандартным именем не забудьте `masterService` во всех релизах.

### Управление конфигурацией безопасности через чарт

По умолчанию чарт применяет демонстрационную конфигурацию безопасности (известные дефолтные пароли) — она годится только для локальных экспериментов. Чарт поддерживает три способа задать боевую конфигурацию:

1.  **Inline через единый Secret** (конфигурация хранится в Git вместе с values):

    ```yaml
    securityConfig:
      enabled: true
      config:
        dataComplete: true     # заменяет ВСЕ yaml-файлы конфигурации безопасности
        data:
          internal_users.yml: |-
            _meta:
              type: "internalusers"
              config_version: 2
            admin:
              hash: "$2y$12$..."      # bcrypt-хеш из hash.sh
              reserved: true
          roles.yml: |-
            _meta:
              type: "roles"
              config_version: 2
          roles_mapping.yml: |-
            _meta:
              type: "rolesmapping"
              config_version: 2
    ```

    Чарт сам создаст Secret, смонтирует файлы в `/usr/share/opensearch/config/opensearch-security` и применит их при старте.
2.  **Внешние секреты пофайлово** (когда отдельные файлы управляются разными командами или инструментами):

    ```yaml
    securityConfig:
      enabled: true
      internalUsersSecret: os-internal-users   # заранее созданный Secret
      rolesSecret: os-roles
      rolesMappingSecret: os-roles-mapping
    ```

    Ключи секции: `actionGroupsSecret`, `configSecret` (для config.yml), `internalUsersSecret`, `rolesSecret`, `rolesMappingSecret`, `tenantsSecret`.
3.  **Частичное обновление одним внешним Secret**: `securityConfig.config.securityConfigSecret: <имя>` — монтируется один внешний Secret; удобно, когда нужно переопределить единственный файл (например, internal_users.yml).

Хеш пароля генерируется утилитой `hash.sh` из образа (см. полный цикл создания пользователей в [Администрирование OpenSearch](./opensearch_administration.md)). Независимо от способа, переменная `OPENSEARCH_INITIAL_ADMIN_PASSWORD` (через `extraEnvs`) обязательна начиная с OpenSearch 2.12 — без нее контейнер не стартует.

После развертывания оперативные изменения пользователей и ролей выполняются через REST API или securityadmin.sh (см. администрирование); конфигурация, заданная через чарт, применяется при каждом пересоздании подов — учитывайте это при смешении подходов.

### Обновление без простоя (Rolling Update)

1.  **Shard Allocation Awareness**:
    В `values.yaml` настройте учет зон доступности (AZ):
    ```yaml
    config:
      opensearch.yml: |-
        cluster.routing.allocation.awareness.attributes: "topology.kubernetes.io/zone"
        cluster.routing.allocation.awareness.force.zone.values: zone-a,zone-b,zone-c
    ```
2.  **Pod Anti-Affinity**:
    Используйте `hard` anti-affinity для Cluster Manager:
    ```yaml
    antiAffinity: "hard"
    ```
    Вариант `soft` (best-effort) подходит для data-групп небольших кластеров; вариант `custom` принимает полноценную спецификацию в `customAntiAffinity`.
3.  **Последовательность**:
    *   Обновляйте Data-узлы по одной группе.
    *   Дождитесь `green` статуса и завершения `shards relocation` перед переходом к следующей группе.
    *   В последнюю очередь обновляйте Cluster Manager.

Полный цикл минорного обновления одной группы:

```bash
# 1. Меняем image.tag в values-data-hot.yaml
helm upgrade os-data-hot opensearch/opensearch -f values-data-hot.yaml

# 2. Наблюдаем за прокруткой подов и здоровьем кластера
kubectl get pods -l app.kubernetes.io/instance=os-data-hot -w
kubectl run curl --rm -it --image=curlimages/curl -- \
  curl -ku admin:*** https://os-mgr-opensearch-master:9200/_cluster/health?pretty
# → "status":"green","relocating_shards":0
```

Для полного ручного контроля задайте `updateStrategy: OnDelete` и удаляйте поды по одному после проверки здоровья (`kubectl delete pod <имя>`); StatefulSet пересоздаст их с новым образом. Параметр `majorVersion` используется чартом для выбора мажорно-специфичной конфигурации при апгрейде между линиями.

**Edge case при переходе 2.19 → 3.x**: плагин ISM линии 2.x оставляет в persistent-настройках служебные параметры (`plugins.index_state_management.*`), которые после апгрейда архивируются с префиксом `archived.` и могут блокировать любые `PUT /_cluster/settings` ошибкой про unknown setting. Лечение:

```json
PUT _cluster/settings
{
  "persistent": {
    "archived.plugins.index_state_management.template_migration.control": null,
    "archived.plugins.index_state_management.metadata_migration.status": null
  }
}
```

### Оптимизация JVM Heap и ресурсов

**Strict Rule**: устанавливайте `requests` равными `limits` для обеспечения Guaranteed QoS.
*   **Memory**: `resources.limits.memory: 8Gi`.
*   **Heap**: `OPENSEARCH_JAVA_OPTS: "-Xms4g -Xmx4g"`.
*   **Storage**: используйте `volumeClaimTemplates` для гарантированного выделения дисков в StatefulSet.

Уточнения по механизму чарта: идоматичный способ задать heap — параметр `opensearchJavaOpts` (умолчание `-Xmx512M -Xms512M`, пробрасывается в контейнер тем же механизмом переменных окружения); эквивалентно работает `extraEnvs` с `OPENSEARCH_JAVA_OPTS`. Heap = половина лимита памяти пода (8Gi памяти → 4g heap): вторая половина нужна страничному кэшу ОС для Lucene и вне-heap памяти JVM. Гарантированный QoS защищает поды OpenSearch от вытеснения при давлении на Kubernetes-узел — вытесняемый search-кластер деградирует заметно дороже, чем лишние неиспользованные резервы.

Хранение: чарт разворачивает PVC из `volumeClaimTemplate` (по умолчанию `30Gi`; меняйте размер и `storageClassName`). Права на томе выставляет initContainer `fsgroup-volume` (управляется `persistence.enableInitChown`) — не отключайте его без понимания, иначе под уйдет в цикл из-за недоступности каталога данных.

### Устранение неполадок

| Симптом | Причина | Диагностика и решение |
| :--- | :--- | :--- |
| Поды в CrashLoopBackOff сразу после установки; лог: `Plugin [prometheus-exporter] was built for OpenSearch version X but version Y is running` | Версия плагина из `plugins.installList` не совпадает с версией образа | Приведите URL плагина к версии `image.tag`; либо уберите плагин через `plugins.removeList` до исправления |
| API отвечает `OpenSearch Security not initialized` | Конфигурация безопасности не применилась при старте (битый Secret, ошибка YAML в securityConfig) | Проверьте логи первого пода группы master; валидируйте содержимое Secret (`kubectl get secret <имя> -o jsonpath='{.data}' \| base64 -d`); проверьте `securityConfig.enabled` |
| Новый узел не входит в кластер, бутстрап падает | Атрибуты remote store отличаются от остальных узлов | Сравните секцию `node.attr.remote_store.*` во всех релизах; настройки обязаны быть идентичны |
| Под перезапускается с ошибкой прав доступа к `/usr/share/opensearch/data` | Отключен или сломан initContainer chown / несоответствие fsGroup | Верните `persistence.enableInitChown: true`; сверьте `podSecurityContext.fsGroup` с политикой StorageClass |
| Ошибка `max virtual memory areas vm.max_map_count [65530] is too low` | sysctl не выставлен на Kubernetes-узле | `sysctlInit.enabled: true` (требует привилегий) или выставите vm.max_map_count=262144 на узлах через DaemonSet |
| Поды в Pending | Недостаточно ресурсов или нет подходящего StorageClass | `kubectl describe pod <имя>` → события; проверьте requests и наличие storageClass в persistence |
| Dashboards не видит кластер (502/503) | Несоответствие `masterService` имени сервиса группы cluster manager | Сверьте имя headless-сервиса (`kubectl get svc`) со значением `masterService` во всех релизах |

## Дополнительная информация

### Ключевые параметры чарта (шпаргалка)

| Параметр | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `replicas` | `3` | Число подов в NodeGroup |
| `nodeGroup` | `master` | Имя группы; часть имен всех ресурсов |
| `masterService` | `""` | Имя сервиса discovery; обязателен при nodeGroup != master |
| `singleNode` | `false` | Режим одного узла; форсирует replicas=1 |
| `roles` | все роли | Список ролей узлов группы |
| `antiAffinity` | `hard` | hard/soft/custom (+ `customAntiAffinity`, ключ `antiAffinityTopologyKey`) |
| `opensearchJavaOpts` | `-Xmx512M -Xms512M` | Настройки JVM, прежде всего heap |
| `persistence.size` | `30Gi` | Размер PVC из volumeClaimTemplate |
| `sysctlVmMaxMapCount` / `sysctlInit.enabled` | `262144` / `false` | vm.max_map_count и привилегированный initContainer |
| `updateStrategy` | `RollingUpdate` | Или `OnDelete` для ручной прокрутки |
| `maxUnavailable` | `1` | Лимит PDB на группу |
| `terminationGracePeriod` | `120` | Секунды на корректную остановку |
| `plugins.{enabled,installList,removeList}` | `false/[]/[]` | Управление сторонними плагинами |
| `serviceMonitor.enabled` | `false` | ServiceMonitor для Prometheus Operator (path `/_prometheus/metrics`) |
| `securityConfig.enabled` | `true` | Применение конфигурации безопасности (demo по умолчанию) |

### Helm-чарт против Kubernetes Operator

Альтернативный путь развертывания — [OpenSearch Kubernetes Operator](https://github.com/opensearch-project/opensearch-k8s-operator) (версия 3.0, январь 2026: quorum-safe rolling restarts, multi-namespace поддержка, hot-reload TLS-сертификатов):

| Критерий | Helm-чарт | Operator |
| :--- | :--- | :--- |
| Сложность внедрения | Низкая (привычный GitOps-поток) | Выше (CRD + контроллер) |
| Масштабирование | Ручное (helm upgrade) | Декларативное через CR |
| Rolling upgrades | Базовый контроль (OnDelete/RollingUpdate) | Умный drain, quorum-safe restarts |
| Управление безопасностью | Через секреты и securityadmin.sh | CRD-автоматизация |
| Мульти-кластер | Отдельный релиз на группу | Один CR на кластер |

Чарт остается выбором по умолчанию для команд со зрелым GitOps-процессом; Operator — когда нужны автоматизированные жизненные циклы и интеграция TLS-ротации.

### Очистка окружения

```bash
helm uninstall os-dev
helm uninstall dashboards   # если ставился

# Данные (PVC) НЕ удаляются автоматически:
kubectl get pvc -l app.kubernetes.io/name=opensearch
kubectl delete pvc -l app.kubernetes.io/name=opensearch   # необратимо!
```

---
## См. также

* **[Администрирование OpenSearch](./opensearch_administration.md)** — управление индексами, безопасность, remote store и снимки.
* **[OpenSearch: Обзор системы](./opensearch_overview.md)** — архитектура и ключевые компоненты.
* **[Развертывание Ansible](./opensearch_ansible_deployment.md)** — альтернатива для виртуальных машин без Kubernetes.
