# Логирование в Rancher

## Определения

**Rancher Logging** — интегрированное решение для централизованного сбора, фильтрации и маршрутизации логов в кластерах под управлением Rancher. С 2021 года базируется на **Logging Operator** (проект Banzai Cloud / SUSE, ныне CNCF Sandbox-проект) вместо прежнего «собственного» решения (clusterlogging/projectlogging), которое было помечено как устаревшее в Rancher 2.5 и полностью заменено в Logging V2.

**Logging Operator** — Kubernetes-оператор, управляющий жизненным циклом компонентов логирования (Fluent Bit, Fluentd и syslog-ng) через декларативные пользовательские ресурсы (Custom Resources). Проект перешёл под CNCF Sandbox, официальная документация переехала на домен `kube-logging.dev`.

**Fluent Bit** — высокопроизводительный Edge-агент (написан на C), работающий как DaemonSet на каждом узле. В актуальных версиях (v3.x+) является OTel-native компонентом, собирает логи контейнеров из `/var/log/containers`, обогащает их метаданными Kubernetes через API-сервер и передает в агрегатор. Именно он является collector (шпер) во всех инсталляциях Rancher Logging.

**Fluentd / syslog-ng** — центральные агрегаторы и маршрутизаторы логов (forwarders), официально поддерживаемые Logging Operator (начиная с версии 4.0 поддерживается syslog-ng).
*   **Fluentd**: Классический агрегатор с богатой экосистемой Ruby-плагинов. Рекомендуется для сложных трансформаций и Legacy-интеграций, большого числа различных плагинов Output.
*   **syslog-ng**: Современный многопоточный агрегатор (распространение AxoSyslog), ориентированный на высокую производительность и обработку больших объёмов логов. Рекомендуется для высоконагруженных сред: многопоточная обработка даёт прирост производительности, а фильтрация может работать не только по метаданным, но и по содержанию сообщения.

> **Примечание про Vector.** Vector — быстрый агрегатор на Rust с нативной поддержкой OpenTelemetry, часто упоминается как альтернатива Fluentd в экосистеме Kubernetes. Однако **официальная поддержка Vector как forwarder'а в Logging Operator (и, соответственно, в штатном Rancher Logging app) отсутствует** — оператор поддерживает Fluentd и syslog-ng. Vector применяется в нагруженных средах как отдельный самостоятельный агрегатор, когда инженеры строят собственный пайплайн за пределами Logging Operator (например, в связке с OTel Collector). Подробнее про сам Vector — см. [обзор Vector](../../Vector/vector_overview.md).

**Flow / ClusterFlow** — пользовательские ресурсы, определяющие фильтрацию (парсинг JSON, добавление меток, исключение строк) и связывающие источники логов с `Output`.
*   `Flow`: собирает логи только из своего Namespace.
*   `ClusterFlow`: может собирать логи со всего кластера или выбранных Namespace.

**Output / ClusterOutput** — ресурсы, определяющие целевую систему хранения (Elasticsearch, OpenSearch, Kafka, S3, Loki, OTLP, Splunk, syslog и др.).
*   `Output`: доступен только внутри своего Namespace.
*   `ClusterOutput`: глобальный ресурс, эффективен только в `controlNamespace` оператора (по умолчанию `cattle-logging-system`).

## Базовые концепции

### Архитектура потоков данных

Rancher Logging реализует разделение ответственности между компонентами для обеспечения производительности и гибкости.

1.  **Сбор (Collection)**: Fluent Bit читает файлы логов из `/var/log/containers/` (сбор только `stdout`/`stderr` контейнеров), а также журналы компонентов и control plane, и пересылает их в агрегатор по протоколу Forward (для Fluentd) или OTLP (для Vector/OpenTelemetry).
2.  **Агрегация (Aggregation)**: Агрегатор принимает потоки от всех агентов, объединяет их, выполняет дедупликацию и применяет правила маршрутизации.
3.  **Маршрутизация (Routing)**: На основе правил `Flow`/`ClusterFlow` логи направляются в соответствующие `Output`/`ClusterOutput` (хранилища или брокеры).

**Пространство управления (controlNamespace):** все ресурсы оператора (`Logging`, `ClusterFlow`, `ClusterOutput`) работают в одном namespace — по умолчанию `cattle-logging-system`. Это важно: если `ClusterFlow`/`ClusterOutput` созданы вне `controlNamespace`, они не подхватываются оператором, пока не установлен флаг `allowClusterResourcesFromAllNamespaces: true` в ресурсе `Logging` (позволяет оценивать кластерные Flow/Output из любых namespace).

### Иерархия ресурсов управления

Настройка системы выполняется через несколько основных типов ресурсов (CRD группы `logging.banzaicloud.io/v1beta1`):

*   **Logging**: Глобальный ресурс, определяющий архитектуру (выбор между Fluentd и syslog-ng), параметры агентов и общие настройки (версии образов, лимиты ресурсов, Tolerations, пути к systemd, `controlNamespace`). Начиная с версии оператора **4.5**, Fluent Bit, Fluentd и syslog-ng могут конфигурироваться также как **отдельные** ресурсы (например, `fluentbitAgent`, `syslogNGConfig`) — это уменьшает размер `Logging`-ресурса и даёт более тонкий контроль RBAC.
*   **Output / ClusterOutput**: Определяют целевую систему хранения. В UI Rancher доступны готовые формы для: Amazon ElasticSearch, Azure Storage, Cloudwatch, Datadog, Elasticsearch, File, Fluentd, GCS, Kafka, Kinesis Stream, LogDNA, LogZ, Loki, New Relic, Splunk, SumoLogic, Syslog. Неподдерживаемые плагины можно подключить через паттерн «custom output» (см. практику).
*   **Flow / ClusterFlow**: Определяют фильтры (парсинг JSON, добавление меток, исключение строк) и связывают источники логов с `Output`. Поле `match` позволяет выбирать/исключать логи по меткам Kubernetes, именам контейнеров и хостов; правила оцениваются по порядку до первого совпадения (`select` или `exclude`). Ссылки на `Output` — через `localOutputRefs` (внутри namespace) и `globalOutputRefs` (глобальные, из `controlNamespace`).

**Типы фильтров в Flow:**
*   `parser` — разбор структурированных сообщений (JSON, nginx, и т.п.), удаление ключа `kubernetes`/`log` исходного сообщения.
*   `tag_normaliser` — нормализация `tag` в удобный формат `${namespace_name}.${pod_name}.${container_name}`.
*   `dedot` — разворачивание вложенных ключей с разделителем (полезно для Elasticsearch, где точки в именах полей недопустимы).
*   `prometheus`-фильтры — вычисление метрик на основе логов.

### Мульти-тенантность (Multi-tenancy)

Начиная с Logging Operator **4.5**, поддерживается модель мульти-тенантности: отдельный ресурс `syslogNGConfig` (namespaced) позволяет владельцам «арендаторов» управлять собственным агрегатором внутри `controlNamespace`, в то время как центральная команда владеет ресурсом `Logging`. Это даёт:
*   Разделение RBAC: разные роли могут управлять `Logging` и `syslogNGConfig` отдельно.
*   Изоляцию агрегаторов и маршрутизацию логов по namespace к индивидуальным агрегаторам.
*   Уменьшение размера `Logging`-ресурса (маршрутизация потоков уже не раздувается до предела аннотаций `kubectl apply`).

### Разграничение прав доступа (RBAC)

Интеграция с ролевой моделью Rancher позволяет делегировать управление логированием владельцам приложений. Rancher Logging определяет две служебные роли: `logging-admin` и `logging-view` (ClusterRoles, агрегируемые в стандартные роли Kubernetes).

| Роль в Rancher | ClusterFlow / ClusterOutput | Flow / Output |
| :--- | :--- | :--- |
| **Cluster Admin / Cluster Owner** | Полный доступ | Полный доступ |
| **Cluster Member** | Нет доступа | Нет доступа |
| **Project Owner** | Только чтение (`logging-view`) | Полный доступ (создание/редактирование `Flow`/`Output` в namespace проекта) |
| **Project Member** | Нет доступа (только просмотр через `logging-view`) | Только чтение |

**Ключевая деталь политики:** редактирование `ClusterFlow`/`ClusterOutput` — привилегия, равнозначная праву на доступ ко **всем** логам кластера. Поэтому такие права выдаются только администратору кластера. `logging-admin` даёт полный доступ к namespaced `Flow`/`Output`; `logging-view` — просмотр `Flow`/`Output`, а также `ClusterFlow`/`ClusterOutput`.

**Требование для работы с логированием:** и Project Owner, и Project Member должны иметь хотя бы один Namespace в своём проекте, иначе кнопка Logging в верхнем меню не отображается.

**Известная проблема (v2.9.x):** из-за того, что роль `project-member` наследует Kubernetes-роль `edit`, участники проекта могли создавать/изменять/удалять `Flow`/`Output` в namespace проекта (bug rancher/rancher#50538). Исправлено в Rancher **2.12.0-alpha9+**. Если по соображениям безопасности нужно жёстко ограничить права на logging-CRD у Project Members в версиях < 2.12, требуется правка/замена кастомной роли с наследованием от `edit`.

## Практические сценарии

### Установка и управление Logging app (Rancher)

1.  В UI Rancher перейдите на нужный кластер → **Apps** → установите приложение **Rancher Logging**.
2.  Приложение разворачивается в namespace `cattle-logging-system` (это и есть `controlNamespace`).
3.  После установки настройте `Logging`-ресурс (выбор агрегатора, лимиты), затем `ClusterOutput`/`Output` и `Flow`/`ClusterFlow`.

**Ключевые параметры Helm-чарта `rancher-logging`:**
- `global.cattle.windows.enabled` — включить сбор логов с Windows-узлов.
- `global.seLinux.enabled: true` — для кластеров с SELinux.
- `systemdLogPath` — путь к journald для сбора логов control plane (см. ниже).
- `additionalLoggingSources` — включение дополнительных источников: `rke`, `rke2`, `k3s` (движок контейнеров `systemd`), `aks`, `eks`, `gke`, а также `kubeAudit` (sбор логов аудита kube-apiserver).
- `disablePvc` / `bufferStorageVolume` — управление дисковым буфером агрегатора.
- `dockerRootDirectory` — переопределение пути к каталогу Docker, если изменён.

### Настройка Fluentd / syslog-ng как основного агрегатора

Исторически в инсталляциях Rancher использовался Fluentd. Для высоконагруженных сред рекомендуется перейти на **syslog-ng** (многопоточная обработка) — он является официально поддерживаемым forwarder'ом Logging Operator.

**Выбор агрегатора в ресурсе `Logging` (для syslog-ng):**

```yaml
apiVersion: logging.banzaicloud.io/v1beta1
kind: Logging
metadata:
  name: rancher-logging
  namespace: cattle-logging-system
spec:
  controlNamespace: cattle-logging-system
  syslogNG:
    statefulsetDefaults:
      replicas: 2
      resources:
        limits:
          cpu: "2000m"
          memory: "2Gi"
  fluentbit:
    resources:
      limits:
        memory: "256Mi"
```

### Включение syslogNGConfig для мульти-тенантности (4.5+)

```yaml
apiVersion: logging.banzaicloud.io/v1beta1
kind: SyslogNGConfig
metadata:
  name: team-a
  namespace: cattle-logging-system
spec:
  config:
    # конфигурация агрегатора syslog-ng для арендатора team-a
  fluentd: {}
```

### Сбор логов control plane (K3s / RKE2 / journald)

K3s и RKE2 логируют компоненты control plane в **journald** (системный журнал systemd). Для их сбора необходимо правильно задать `systemdLogPath`:

- По умолчанию используется `/run/log/journal`, однако некоторые дистрибутивы (например, Ubuntu) используют `/var/log/journal`.
- Проверка на узле:
  ```bash
  # Если вывод 'volatile' → система пишет в /run/log/journal
  systemd-analyze cat-config systemd-journald.service 2>/dev/null | grep -i storage || true
  ```
- Если выбранный путь не существует, Rancher не сможет собирать логи control plane. Решение:
  1.  Установить `Storage=volatile` в `journald.conf`.
  2.  Перезагрузить машину.
  3.  Задать `systemdLogPath: "/run/log/journal"` в конфигурации Logging.

### Отправка логов в OpenTelemetry (OTLP)

В современной архитектуре наблюдаемости логи часто направляются в OTel Collector для дальнейшей обработки:

```yaml
apiVersion: logging.banzaicloud.io/v1beta1
kind: ClusterOutput
metadata:
  name: otel-collector
  namespace: cattle-logging-system
spec:
  otlp:
    endpoint: "otel-collector.monitoring.svc:4317"
    protocol: grpc
    tls:
      enabled: true
      insecure: false
```

### Совместимость с OpenSearch 3.x

Для OpenSearch актуальных версий необходимо учитывать изменения в API и форматах данных:

```yaml
spec:
  opensearch:
    host: opensearch.example.com
    port: 9200
    scheme: https
    suppress_type_name: true  # Обязательно для совместимости с OS 2.x/3.x
    index_name: "k8s-logs-%Y.%m.%d"
    allow_self_signed_cert: false
```

### Настройка маршрутизации всех логов (без правил включения/исключения)

Для сбора **всех** логов кластера (обычно нужно security-команде) создайте `ClusterOutput` и `ClusterFlow` без ограничений:

```yaml
apiVersion: logging.banzaicloud.io/v1beta1
kind: ClusterOutput
metadata:
  name: all-logs-security
  namespace: cattle-logging-system
spec:
  elasticsearch:
    host: security-es.example.com
    port: 9200
    scheme: http
    index_name: all-container-logs
---
apiVersion: logging.banzaicloud.io/v1beta1
kind: ClusterFlow
metadata:
  name: all-logs
  namespace: cattle-logging-system
spec:
  globalOutputRefs:
    - all-logs-security
```

**Рекомендация логирования всей кластерной инфраструктуры:** если нужно собирать все логи всех контейнеров, создайте как минимум **два `ClusterOutput`** — один для security-команды и один для администраторов кластера — и маршрутизируйте поток в оба. При этом выбирайте output-эндпоинт, способный выдержать полный объём трафика кластера, и продумайте раздельные индексы.

> **Важно про Flow и компонентные логи:** `ClusterFlow` собирает логи всех контейнеров всех хостов. На 2026 год компонентные логи (kubelet, kube-apiserver и т.п.) также могут быть отфильтрованы по имени исходного контейнера, когда появляется эта возможность; по умолчанию они попадают в общий поток.

### Сбор логов файловых приложений через sidecar

Rancher Logging собирает только `stdout`/`stderr` контейнеров. Если приложение пишет логи в файл на диске, используйте **log streaming sidecar**:

```yaml
spec:
  containers:
    - name: app
      image: myapp:1.0
      # приложение пишет в /var/log/app.log
    - name: log-streamer
      image: busybox
      command: ["sh", "-c", "tail -F /shared/app.log"]
      volumeMounts:
        - name: shared
          mountPath: /shared
```

Sidecar дампит содержимое `/shared/app.log` в `stdout`, после чего логи автоматически подхватываются Fluent Bit и направляются согласно настроенным `Flow`/`ClusterFlow`. Для точной маршрутизации создайте отдельный `Flow`, нацеленный на имя этого контейнера.

### Пересылка Rancher Audit Log в Logging app

Rancher имеет собственный API Audit Log (журнал действий пользователей в управляющем кластере). Его можно пересылать в Rancher Logging:

1.  Убедитесь, что аудит включён (`auditLog.enabled=true`, уровни `AUDIT_LEVEL` 0–3). Выход аудита — sidecar-контейнер `rancher-audit-log` в поде Rancher (`cattle-system`).
2.  Создайте `ClusterOutput` (например, Elasticsearch или Loki).
3.  Создайте `ClusterFlow`, выбирающий логи аудита:
    ```yaml
    apiVersion: logging.banzaicloud.io/v1beta1
    kind: ClusterFlow
    metadata:
      name: audit-flow
      namespace: cattle-logging-system
    spec:
      match:
        - select:
            namespaces: [cattle-system]
            container_names: [rancher-audit-log]
      globalOutputRefs:
        - audit-elasticsearch
    ```

> Отдельно от Rancher Audit Log существует **Kubernetes Audit Log** (kube-apiserver). Его сбор включается через `additionalLoggingSources.kubeAudit.enabled` и обычно требует настройки `--audit-policy-file` на уровне кластера. Подробнее — в [Архитектуре наблюдаемости](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md).

### Custom Output для неподдерживаемых плагинов

Если нужного плагина Output нет в списке поддерживаемых, используется паттерн «custom forwarder»: собственный Fluent Bit/Fluentd с нужным плагином, развернутый как Deployment, и `ClusterOutput` с `spec.forward`, указывающим на него.

```yaml
apiVersion: logging.banzaicloud.io/v1beta1
kind: ClusterOutput
metadata:
  name: syslog
  namespace: cattle-logging-system
spec:
  forward:
    servers:
      - host: "syslog-forwarder.cattle-logging-system"
    require_ack_response: false
```

Агрегатор будет пересылать поток в deployment `syslog-forwarder`, который уже пишет в необходимую систему.

### Тюнинг буферизации для высоконагруженных сред

Чтобы избежать потери логов при недоступности хранилища, необходимо настроить буфер для агрегатора.

**Способ 1 — дисковый буфер (PVC) для Fluentd:**

```yaml
spec:
  fluentd:
    bufferStorageVolume:
      pvc:
        spec:
          accessModes: [ "ReadWriteOnce" ]
          resources:
            requests:
              storage: 50Gi
          storageClassName: premium-rwo
```

**Способ 2 — настройка параметров ввода Fluent Bit** (для снижения потребления памяти и обработки больших линий):

```yaml
spec:
  fluentbit:
    inputTail:
      Mem_Buf_Limit: "64MB"       # лимит памяти на один input (backpressure)
      Buffer_Chunk_Size: "32KB"
      Buffer_Max_Size: "128KB"
      Skip_Long_Lines: "Off"      # если включить, длинные строки будут пропускаться
      Multiline_Flush: "3000"
```

**Способ 3 — тюнинг flow control агрегатора:**
- Уменьшите **flush interval** (интервал сброса буфера), чтобы лог не переполнял буфер.
- Добавьте **flush threads** (потоки сброса) для ситуаций, когда много логов поступает одновременно.
- Отключите `disablePvc` (включите persistent volume), если приоритет — отсутствие потерь, а не экономия диска.

**Метрики контроля буфера:** `buffer_usage` и `failed_outputs` (выводятся на Grafana-дашборде «Logging Operator Overview»). Рост `buffer_usage` без сброса свидетельствует о недоступности/медлительности endpoint-а хранилища.

## Диагностика и отладка

Если логи не доходят до хранилища, используйте следующую последовательность:

1.  **Проверка статуса агентов**: Убедитесь, что поды `fluent-bit` запущены и не находятся в состоянии `CrashLoopBackOff` из-за нехватки памяти (проверьте `OOMKilled`).
2.  **Валидация конфигурации**: Logging Operator генерирует итоговый конфиг. Проверьте Secret `rancher-logging-fluentd-config` (или аналогичный для Vector / syslog-ng) на наличие синтаксических ошибок. В идеале делегируйте валидацию флагом конфигурации оператора (configuration validation — встроенная возможность Logging Operator).
3.  **Логи агрегатора**: Просмотрите детальный вывод агрегатора для поиска ошибок авторизации в Output:
    ```bash
    kubectl logs -n cattle-logging-system -l app.kubernetes.io/name=fluentd # или syslog-ng, vector
    ```
4.  **Метрики**: Используйте Grafana-дашборд "Logging Operator Overview" для отслеживания `failed_outputs` и `buffer_usage`.
5.  **Проверка controlNamespace**: Убедитесь, что `ClusterFlow`/`ClusterOutput` созданы точно в `cattle-logging-system` (или включён `allowClusterResourcesFromAllNamespaces`). Частая причина отсутствия маршрутизации — создание ресурсов в другом namespace.
6.  **Проверка прав (RBAC)**: Если у пользователя нет кнопки Logging или нет доступа к просмотру — проверьте наличие хотя бы одного Namespace в проекте и привязку к `logging-view`/`logging-admin`.
7.  **Проверка пути systemd для control plane**: Если собираются только логи приложений, но не логи компонентов K3s/RKE2 — сверьте `systemdLogPath` (см. раздел выше).

### Известные проблемы

- **`cattle-logging` namespace пересоздаётся (legacy global view):** если ранее логирование разворачивалось из глобального вида в legacy UI, namespace `cattle-logging` может бесконечно пересоздаваться. Решение — удалить ресурсы `clusterloggings.management.cattle.io` и `projectloggings.management.cattle.io` из namespace, соответствующего кластеру в management-кластере, поскольку их наличие заставляет Rancher создавать `cattle-logging` в downstream-кластере:
  ```bash
  kubectl delete -n <cluster-id> clusterloggings.management.cattle.io --all
  kubectl delete -n <cluster-id> projectloggings.management.cattle.io --all
  ```
  Предупреждение: выполняйте, только если legacy logging не используется.
- **Project Member может редактировать logging-CRD (v2.9.x–2.11.x):** известный bug rancher/rancher#50538 из-за наследования роли `edit`. Исправлено в 2.12.0-alpha9+. Для старых версий — создайте кастомную роль вместо наследования от `edit`.
- **Default buffer слишком большой → падение подов:** уменьшите flush interval или добавьте flush threads; либо уменьшите `Mem_Buf_Limit` в `inputTail`.

## Дополнительная информация

### Статус компонентов (2026)

| Компонент | Состояние | Рекомендация |
| :--- | :--- | :--- |
| **Logging Operator** | Актуально (CNCF Sandbox, v5.4/6.x) | Основной стандарт для всех типов кластеров (RKE2, K3s, Import). |
| **Flows / Outputs (Fluentd + syslog-ng)** | Stable | Рекомендуется для новых инсталляций syslog-ng вместо чисто Fluentd (высокая производительность). |
| **Vector Support** | Альтернатива (не официальный forwarder) | Используйте, только если нужен собственный высокопроизводительный пайплайн за пределами Logging Operator. |
| **OTel Integration** | GA | Используйте OTLP для унификации с метриками и трассировками. |
| **Мульти-тенантность (syslogNGConfig)** | Стабильно (4.5+) | Для моделей, где арендаторы владеют своими агрегаторами. |

### Статус версий Logging Operator (2026)

- Версия **6.0.0** планировалась к июлю 2026; **5.4.0** оставалась официально поддерживаемой до октября 2026.
- Изменения/депрекации: `hostTailer` (ед. число) переименован в `hostTailers` (мн.) — мигрируйте конфигурацию; поддержка Pod Security Policies (PSP) полностью удалена (в K8s удалены с v1.25).
- Рекомендуется следить за [What's new](https://kube-logging.dev/6.3/docs/whats-new/) перед крупными апгрейдами.

### Рекомендации и лучшие практики (2026)

*   **Если строгие требования сбора всех логов** — создайте не менее двух `ClusterOutput` (security/админ) и отдельный безусловный `ClusterFlow`, не определяя Include/Exclude (иначе логи могут потеряться).
*   **Точная нацеленность Flow:** для каждой команды/приложения создавайте отдельный `Flow` с узким `match` (один Deployment, или даже один контейнер в Podе). Это упрощает отладку и не смешивает логи в агрегаторе.
*   **Структурированный вывод:** по возможности пишите логи в структурированном виде (JSON/syslog) — для них уже есть готовые парсеры; добавляйте `request_id`/`trace_id` для сквозной трассировки.
*   **Уровень verbosity:** держите уровень логов приложений низким (кроме времени отладки), иначе шум перегрузит инфраструктуру логирования и затопит значимые события.
*   **RBAC:** право редактирования `ClusterFlow`/`ClusterOutput` давайте только администраторам; управление logging делегируйте владельцам проектов через настроенные `logging-admin`.
*   **Слежение за выходом из строя буфера:** настройте алертинг по `buffer_usage` и `failed_outputs`, чтобы узнать о недоступности хранилища до фактической потери логов.

**Связанные разделы:**

* [Архитектура наблюдаемости в Kubernetes](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md) — общие принципы.
* [rancher_overview](./rancher_overview.md) — обзор платформы Rancher.
* [Конфигурация Fluent Bit](../MonitoringLogging/EFK/fluentbit/fluentbit_configuration.md) — детальный тюнинг агента.

**Внешние ресурсы:**

* [Kube-Logging (Logging Operator) Documentation](https://kube-logging.dev/docs/)
* [Rancher Logging Integration](https://ranchermanager.docs.rancher.com/integrations-in-rancher/logging)
* [Rancher RBAC for Logging](https://ranchermanager.docs.rancher.com/integrations-in-rancher/logging/rbac-for-logging)
