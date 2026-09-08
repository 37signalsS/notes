# StatefulSet: Лучшие практики

## Определения

**StatefulSet: Лучшие практики** — экспертный свод рекомендаций по проектированию, настройке и эксплуатации приложений с состоянием в Kubernetes. Цель данных практик — обеспечить целостность данных, высокую доступность и предсказуемость поведения системы при пиковых нагрузках и сбоях.

## Предварительные требования

1.  **Версия кластера:** часть рекомендаций требует современных релизов — **v1.35–v1.37**. В частности: политика удержания PVC (`persistentVolumeClaimRetentionPolicy` — GA v1.32), Non-Graceful Node Shutdown (GA v1.28), параллельное обновление через `maxUnavailable` (Beta v1.35), стратегия `Recreate` (Alpha v1.37). Проверка: `kubectl version`.
2.  **Базовые знания:** объекты [Pod](../Pod/pod_overview.md), PVC/PV ([PV и PVC](../../Storage/pv_and_pvc.md)), [Headless Service](../../Networking/Service/service_type_headless.md), пробы ([Probes](../probes.md)).
3.  **Теория контроллера:** архитектура и механизмы описаны в **[Обзоре](./statefulset_overview.md)** и **[Ключевых концепциях](./statefulset_core_concepts.md)** — настоящий документ рассматривает *рекомендации*, а не устройство.
4.  **RBAC:** права на `statefulsets`, `pods`, `persistentvolumeclaims`, `poddisruptionbudgets` (policy API), события.

## Основные концепции

### Обеспечение высокой доступности (HA)

Для распределенных систем (СУБД, кворумные приложения) критически важно предотвратить одновременный выход из строя большинства узлов:

1.  **Pod Disruption Budget (PDB):** Гарантирует минимальное количество доступных реплик при добровольном выселении подов (например, при обновлении узлов).
    *   Рекомендация: Для кластера из 3 узлов используйте `minAvailable: 2`. Для больших кластеров предпочтительнее `maxUnavailable: 1`.
    *   **Кворумная формула:** для нечетного числа реплик `N` устанавливайте `minAvailable: ⌈N/2⌉` (для 3 → 2, для 5 → 3). Ниже кворума распределенная БД полностью неработоспособна, поэтому «бюджет» должен быть не ниже размера кворума.
    *   **Взаимодействие с autoscaler/обслуживанием:** PDB блокирует только *добровольные* прерывания (drain, eviction), но не сбои узлов и не taint `out-of-service`. Слишком жесткий PDB (`minAvailable: 100%`) делает узлы «неудаляемыми» для Cluster Autoscaler и полностью блокирует `kubectl drain`. Детали: [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md).
    *   При наличии `initContainers` или долгого запуска следите за эвристикой «unhealthy pods»: по умолчанию (`IfHealthyBudget`) PDB не считает больные поды как прерывание. При необходимости переопределить поведение используйте `spec.unhealthyPodEvictionPolicy: AlwaysAllow`.
2.  **Pod Anti-Affinity:** Используйте жесткие правила (`requiredDuringSchedulingIgnoredDuringExecution`), чтобы поды одной базы данных не оказывались на одном физическом узле.
    *   Топологический ключ: `topology.kubernetes.io/zone` для распределения по дата-центрам (AZ).
    *   **Риск жесткого правила:** при числе узлов меньше числа реплик (или при 1 узле в зоне) лишние поды останутся в `Pending` — планирование невозможно. Для больших парков предпочтительнее `topologySpreadConstraints` (см. ниже) или комбинация «жесткое по hostname + мягкое (`preferred`) по зоне».
    *   Пример анти-аффинитивности (использовать `maxSkew` там, где это применимо):
        ```yaml
        spec:
          affinity:
            podAntiAffinity:
              requiredDuringSchedulingIgnoredDuringExecution:
              - labelSelector:
                  matchLabels:
                    app: postgres
                topologyKey: kubernetes.io/hostname
        ```
3.  **Топологические ограничения (`topologySpreadConstraints`)** — современная альтернатива анти-аффинити для равномерного «растекания» реплик по зонам/узлам. Позволяет избежать ситуации, когда все реплики БД оказались в одной AZ, но без жёсткого запрета (можно задать `whenUnsatisfiable: ScheduleAnyway`):
    ```yaml
    spec:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: postgres
    ```
    Подробнее: [Affinity и Anti-Affinity](../../Scheduling/affinity.md).
4.  **Стабильность запуска (`minReadySeconds`):** Устанавливайте задержку (30–120с), чтобы Kubernetes не переходил к обновлению следующего пода, пока текущий не проработает стабильно некоторое время после прохождения пробы готовности. Это отсекает «разогревающиеся» реплики (выполнившие readiness, но ещё не зарегистрировавшиеся в кворуме).
5.  **Проектирование количества реплик:** для кворумных систем выбирайте **нечетное** число реплик (3, 5) — это исключает «вилку голосования» (tie) и даёт запас одной реплики на потерю узла без потери кворума: (N-1)/2 одновременных отказов допустимы.
6.  **Защита критичных индексов приоритетом:** для индекса 0 (лидер/координатор в большинстве распределенных систем) настройте `priorityClassName` — в условиях дефицита ресурсов на узле системные поды (kube-system) и критичные БД выживают первыми. Подробнее: [PriorityClass](../../Concepts/priorityclass.md).

### Управление хранилищем и данными

Ошибки в настройке CSI могут привести к потере данных или невозможности запуска подов:

*   **Динамический провижининг:** Всегда используйте `volumeBindingMode: WaitForFirstConsumer` в StorageClass. Это гарантирует, что диск будет создан в той же зоне доступности (AZ), куда планировщик определил под. При `Immediate` диск может оказаться в другой зоне, чем под (AZ mismatch), и под вечно останется в `Pending`.
*   **Выбор класса хранения под нагрузку:** для OLTP-БД используйте локальные/SSD-классы (`local-path`, CSI с `storageClass` без репликации на уровне блока) — сетевые классы с удалённой репликацией дают меньшую латентность? (фактически наоборот — локальные диски быстрее; сетевые — надёжнее). Ориентир: локальные для перфоманса + снапшоты для защиты, сетевые (например, NFS-классы) — для мультизонального отказа. Подробнее: [StorageClass](../../Storage/storageclass.md).
*   **Безопасность прав доступа (`fsGroup`):** В `securityContext` пода всегда указывайте `fsGroup`. Это автоматически изменяет владельца примонтированного тома на указанный GID, решая проблемы с правами записи (`Permission Denied`).
    *   В высоконагруженных системах установите `fsGroupChangePolicy: OnRootMismatch` — kubelet пропустит рекурсивную смену владельца, если корень тома уже принадлежит нужному GID (ускоряет старт подов с большими томами).
*   **Политика удержания PVC (GA v1.32):** Настраивайте параметр `persistentVolumeClaimRetentionPolicy`:
    *   `whenDeleted: Retain` — критично для Production, чтобы диск не удалился при случайном удалении StatefulSet.
    *   `whenScaled: Delete` — полезно для горизонтально масштабируемых систем, где данные лишних реплик не имеют ценности (например, Elasticsearch-горячие данные). **Предупреждение:** с `whenScaled: Delete` потеря данных при ошибочном `kubectl scale` необратима; применяйте только там, где реплики действительно не хранят уникальных данных.
*   **Расширение томов:** Включайте `allowVolumeExpansion: true` в StorageClass для онлайн-увеличения объема дисков. Процедура изменения размера в StatefulSet каскадная — см. [Практическое руководство](./statefulset_practical_guide.md).
*   **Не подключайте общий RWX-том к нескольким репликам StatefulSet:** это ломает смысл «личности» (данные не пер-подовые) и создаёт конкуренцию за один диск. Общий том — удел Deployment.
*   **Резервное копирование:** состояние StatefulSet — это PVC + метаданные. Назначьте регулярные снапшоты (`VolumeSnapshot`) с Pre/Post-хуками консистентности (заморозка записи), либо логические дампы (`pg_dump`, `mysqldump`). Регулярно тестируйте восстановление (RTO). Полная методология: [Резервное копирование и DR](../../Operations/backup-strategies.md).
*   **Зачистка осиротевших PVC:** после масштабирования вниз или удаления StatefulSet (политика `Retain`) диски остаются в кластере. Ведите инвентаризацию и удаляйте их целенаправленно:
    ```bash
    kubectl get pvc -l app=postgres
    kubectl delete pvc data-postgres-2   # только после подтверждения, что данные не нужны
    ```

### Ресурсы и планирование (QoS)

Для приложений с состоянием рекомендуется использовать класс обслуживания **Guaranteed**:

*   **Лимиты и запросы:** Устанавливайте `requests` равными `limits` для CPU и Memory. Это предотвращает вытеснение (eviction) пода при нехватке ресурсов на узле и гарантирует предсказуемую производительность.
*   **Настройка памяти:** Если приложение (например, PostgreSQL или Java) использует кэши, лимит памяти в Kubernetes должен быть на 10-20% выше, чем внутренние лимиты приложения, чтобы избежать OOM Killer. Для JVM задавайте heap через `JAVA_OPTS` с запасом на metaspace/нативные структуры.
*   **Точность запросов:** Не завышайте `requests` без необходимости — это расходует ёмкость кластера и может оставить несмонтированные узлы. Для аудита запросов используйте [Goldilocks](../../ToolsUtilities/goldilocks.md) (для БД ориентируйтесь на p90–p99 фактического потребления), подробно разбор — [QoS и управление ресурсами](../../Scheduling/qos_limit_and_requests.md).

### Сетевая идентификация и DNS

*   **Headless Service:** Является обязательным. Проверьте, что имя сервиса в поле `serviceName` совпадает с именем Headless-объекта.
*   **Публикация до readiness (`publishNotReadyAddresses: true`):** для систем, которым нужно обнаружить друг друга до готовности (bootstrap кворума ZooKeeper, Cassandra, Elasticsearch), задавайте этот флаг в Headless Service — иначе «курица и яйцо»: поды не попадают в DNS, пока не готовы. Подробнее: [Headless Service](../../Networking/Service/service_type_headless.md).
*   **Передача идентификации приложению:** пробрасывайте в контейнер имя пода и индекс через Downward API (`metadata.name`) или метку `apps.kubernetes.io/pod-index` (GA v1.32):
    ```yaml
    env:
    - name: POD_NAME
      valueFrom:
        fieldRef:
          fieldPath: metadata.name
    ```
    Это позволяет каждому экземпляру знать свой адрес в репликационном наборе без хардкода.
*   **NodeLocal DNSCache:** Для высоконагруженных баз данных используйте локальное кэширование DNS на узлах, чтобы снизить нагрузку на CoreDNS и избежать задержек при резолвинге имен соседей по кластеру. Причина: агрессивный FQDN-обмен между репликами упирается в UDP conntrack race (задержки 1–5с). Подробнее: [DNS deep dive](../../Networking/dns_deep_dive.md).
*   **Завершение работы:** Устанавливайте `terminationGracePeriodSeconds` (например, 120-300с) в зависимости от объема данных. Приложению нужно время на сброс буферов и передачу роли лидера (Leader Election). Синхронизируйте это окно с `preStop`-хуком (см. сценарий ниже).
*   **Сетевые политики:** для БД создавайте [NetworkPolicy](../../Security/network_policies.md), разрешающий входящий трафик только со sidecar-ов своего приложения — защита от горизонтального перемещения при компрометации stateless-слоя. По умолчанию поды "all-allow".

### Безопасность

*   **RunAsNonRoot:** Всегда запускайте stateful-процессы от не привилегированного пользователя. В сочетании с `runAsUser` переопределяйте UID образа; для образов с root по умолчанию используйте `kubectl`-валидацию (PSA/`restricted`) — [Pod Security Context](../../Security/pod_security_context.md).
*   **ReadOnlyRootFilesystem:** По возможности делайте корневую ФС контейнера доступной только для чтения, монтируя записываемые данные только в выделенные тома (монтируйте `emptyDir` под `/tmp` при необходимости).
*   **ServiceAccount:** Используйте выделенный ServiceAccount с минимально необходимыми правами (RBAC). Если приложение не ходит в API Kubernetes, отключите автомонтирование токена: `automountServiceAccountToken: false` в `spec`.
*   **Секреты:** храните пароли (root-пароль БД, репликационные ключи) в объектах **Secret** и монтируйте тома в режиме `readOnly: true`. Не выносите секреты в config в виде открытых строк — [Безопасность Secret](../../Security/application_secrets_management.md) и [Практическое руководство](./statefulset_practical_guide.md).
*   **Пинайте версии образов:** для критичных СУБД указывайте тег с точной версией (или digest). Избегайте `:latest` — образ может «уехать» при повторном применении манифеста.
*   **Управление конфигурацией:** версионируйте конфиг как immutable [ConfigMap](../../Base/ConfigMap/update_and_rollout.md)/Secret и сменяйте версию явным обновлением шаблона (это даёт чистый rollout через ControllerRevision вместо «горячей» подмены файлов внутри работающего пода).

## Мониторинг и эксплуатация

### Ключевые метрики для алертинга

При эксплуатации StatefulSet через `kube-state-metrics` необходимо отслеживать:

1.  `kube_statefulset_status_replicas_ready < kube_statefulset_replicas`: Сигнализирует о частичной недоступности кластера.
2.  `kube_statefulset_status_observed_generation != kube_statefulset_status_replicas_updated`: Обновление StatefulSet зависло.
3.  `kube_statefulset_status_replicas_current`: Количество реплик на старой версии во время RollingUpdate.

Дополнение к базовому набору (готовые PromQL и пороги для Promotion):

| Сигнал | PromQL (пример тревоги) | Комментарий |
| :--- | :--- | :--- |
| Недоступная часть реплик | `kube_statefulset_status_replicas_ready != kube_statefulset_status_replicas` | «for: 5m» — дать время на восстановление |
| Возможный застрявший rollout | `kube_statefulset_status_observed_generation != kube_statefulset_metadata_generation` | Контроллер ещё не обработал спецификацию |
| Зависшее обновление | `kube_statefulset_status_replicas_updated < kube_statefulset_status_replicas` + `observed_generation == metadata_generation` | Откат застрял между ревизиями — проверяйте лог пода и Partition |
| Ревизии расходятся | `kube_statefulset_status_current_revision != kube_statefulset_status_update_revision` | Во время канареечного rollout это ожидаемо; алерт — `for: 15m` |
| PVC в `Pending` | `kube_persistentvolumeclaim_status_phase{phase="Pending"} == 1` | Отсутствие StorageClass / AZ mismatch |
| Занятость диска (kubelet) | `(1 - kubelet_volume_stats_available_bytes / kubelet_volume_stats_capacity_bytes) * 100 > 85` | Метрики kubelet, реализация в kube-prometheus-stack |

Набор готовых Kubernetes-алертов и ServiceMonitor — в **[Grafana: алерты Kubernetes](../../../Grafana/alerting/kubernetes_alerts.md)**; архитектура сбора метрик — [Мониторинг Kubernetes](../../MonitoringLogging/kubernetes-monitoring-logging-architecture.md).

### Плановое обслуживание узлов (Node Maintenance)

Скрипт безопасного обслуживания узла с кворумной БД:

```bash
# 1. Убедиться, что PDB допускает прерывание (кворум сохранится)
kubectl get pdb
kubectl get pdb <pdb-name> -o jsonpath='{.status.currentHealthy}/{.status.desiredHealthy}{"\n"}'

# 2. Дренировать ОДИН узел за раз (см. --ignore-daemonsets)
kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data --timeout=5m

# 3. Дождаться восстановления реплик контроллером (под вернётся на другой узел с тем же PVC)
kubectl rollout status statefulset/postgres --timeout=300s

# 4. После работ вернуть узел в планирование
kubectl uncordon node-1
```

Правила для кворума: **никогда не дренировать два узла одновременно** (потеря кворума = полный отказ БД) и не оставлять выселенные поды дольше размера бюджета PDB. Детали и ограничения drain: [Обслуживание узлов](../../Operations/node_maintenance.md).

### Отказ узла и плановое переключение (Failover)

*   **Неплановый отказ узла:** контроллер не переносит под StatefulSet автоматически (защита от split-brain). При недоступности узла подтверждайте его выход из кластера меткой `node.kubernetes.io/out-of-service=nodeshutdown` (Non-Graceful Node Shutdown, v1.28+) — тогда тома безопасно отмонтируются и под пересоздастся на другом узле. Процедура и предостережения — в [Обзоре](./statefulset_overview.md) и [Практическом руководстве](./statefulset_practical_guide.md).
*   **Тренировка восстановления:** регулярно выполняйте «пожарные учения» — `kubectl delete pod <leader>` и `kubectl cordon/uncordon` узла, убеждайтесь, что лидерство переходит корректно (какой индекс становится мастером, подхватывается ли репликой). Это единственный способ проверить готовность к реальному сбою.
*   **RPO/RTO:** определите и документируйте целевые показатели (сколько минут простоя допустимо, сколько данных можно потерять). Подстройте частоту снапшотов/дамлов под RPO; проверьте, что восстановление укладывается в RTO. Основа процесса — [Резервное копирование](../../Operations/backup-strategies.md).

### Масштабирование и авто-скейлинг

*   **HPA поддерживается** для StatefulSet (в отличие от DaemonSet). Ограничения контейнера не меняются, поэтому масштабирование зависит от capacity кластера.
*   **Не совмещайте ручной `replicas` и HPA:** `kubectl apply -f` с фиксированным `replicas` перезапишет значение, выставленное контроллером HPA. Если HPA управляет масштабированием — не указывайте `replicas` в манифестах.
*   **Канареечный `partition` + HPA — конфликт:** при выставленном `partition` HPA может добавлять поды, которые останутся на старой ревизии; корректно совмещайте только после снятия границы. Подробнее: [HPA — продвинутое](../../Autoscaling/HPA/hpa_advanced.md).
*   **Вручную масштабировать только после готовности предыдущих:** при `OrderedReady` контроллер сам ждёт; не «подгоняйте» параллельным скейлом — получите менее предсказуемый порядок.
*   **Нижняя граница:** для кворумной БД `minReplicas` в HPA не должен опускаться ниже кворума (обычно 3). Скейл вниз ниже кворума = потеря доступности.

## Практические сценарии

### Сценарий: Обновление с минимальным риском (Canary)

Для критических баз данных используйте стратегию **Partition**:
1.  Установите `updateStrategy.rollingUpdate.partition` равным `N-1` (где N — число реплик).
2.  Обновится только последний под (например, `db-2`).
3.  Проведите нагрузочное тестирование и проверку логов на обновленном экземпляре.
4.  Если всё успешно, уменьшите `partition` до 0 для полного обновления кластера.

Команды, чтобы это сделать декларативно и с проверкой:

```bash
# Ограничить обновление подом db-2
kubectl patch statefulset postgres -p '{"spec":{"updateStrategy":{"type":"RollingUpdate","rollingUpdate":{"partition":2}}}}'

# Запустить новый образ (обновится только db-2)
kubectl set image statefulset/postgres postgres=postgres:16.3

# Проверка: один под на новой ревизии
kubectl get pods -l app=postgres -o jsonpath='{range .items[*]}{.metadata.name}{" → "}{.metadata.labels.statefulset\.kubernetes\.io/pod-name}{"\n"}{end}'
kubectl rollout status statefulset/postgres --timeout=60s

# Снять границу и докатить остальные
kubectl patch statefulset postgres -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":0}}}}'
kubectl rollout status statefulset/postgres --timeout=300s
```

Механика `partition` разобрана в [Ключевых концепциях](./statefulset_core_concepts.md).

### Сценарий: Защита от OOM при восстановлении

После падения базе данных часто требуется много ресурсов на восстановление (WAL replay). Используйте **Startup Probe**, чтобы Liveness-проба не убила под во время длительного процесса инициализации, но при этом сохранялась защита от зависаний в штатном режиме.

Рекомендуемая конфигурация (окно на холодный старт до 300с):

```yaml
startupProbe:
  exec:
    command: ["pg_isready", "-h", "127.0.0.1", "-U", "app"]
  initialDelaySeconds: 5
  periodSeconds: 10
  failureThreshold: 30     # 5с + 29*10с ≈ 295с на инициализацию
readinessProbe:
  exec:
    command: ["pg_isready", "-h", "127.0.0.1", "-U", "app"]
  initialDelaySeconds: 5
  periodSeconds: 5
livenessProbe:
  tcpSocket:
    port: 5432
  initialDelaySeconds: 90  # отложить проверку до прохождения startupProbe
  periodSeconds: 10
failureThreshold: 3
```

Пока `startupProbe` не пройдена, `liveness`/`readiness` не выполняются — под «доживает» до готовности. Правильный расчёт окон и ошибки настройки проб описаны в **[Probes](../probes.md)**.

### Сценарий: Graceful Shutdown с передачей роли (preStop)

Чтобы реплика успела выйти из репликационного набора/передать лидерство до `SIGTERM`, добавим `preStop`-хук и синхронизируем `terminationGracePeriodSeconds`:

```yaml
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 300
      containers:
      - name: postgres
        lifecycle:
          preStop:
            exec:
              command:
              - sh
              - -c
              - >
                psql -h 127.0.0.1 -U app -d postgres -c "SELECT pgpromote();" >/dev/null 2>&1 ||
                sleep 10
```

Порядок завершения: `SIGTERM` → `preStop` (подача команды на демоушен/передачу лидера) → собственно сигнал приложению → окно `terminationGracePeriodSeconds` на сброс буферов и WAL. Если узел выжил, но БД не успела, `delete pod --grace-period=X` должен покрывать весь цикл.

### Сценарий: Масштабирование кворумной БД без потери данных

1.  Проверьте, что текущее число реплик — в пределах кворума и все `Ready` (выше — проверка через `kubectl rollout status`).
2.  Добавить реплику: `kubectl scale statefulset/postgres --replicas=4`; контроллер создаст `postgres-3` и дождётся её готовности (при `whenScaled: Retain` её PVC будет создан как `data-postgres-3`).
3.  Установить PDB под новое число (`maxUnavailable: 1` или `minAvailable: ⌈N/2⌉`).
4.  Удалить реплику: `kubectl scale statefulset/postgres --replicas=3`; при `whenScaled: Delete` PVC реплики удалится сам, иначе — освободите его вручную (см. «Зачистка осиротевших PVC»).

Никогда не скейльте вниз ниже кворума даже на минуту: лидерство и записи потеряются.

### Сетевые политики (NetworkPolicy) для БД

По умолчанию поды в Kubernetes имеют «all-allow» сетевую политику — любой под может обращаться к БД. Для production необходимо изолировать трафик:

**Базовая изоляция — Default Deny:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: postgres-deny-all
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: postgres
  policyTypes:
  - Ingress
  - Egress
```

**Разрешение трафика только от backend-подов:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: postgres-allow-backend
spec:
  podSelector:
    matchLabels:
      app: postgres
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: backend  # Только backend-поды могут обращаться к БД
    ports:
    - port: 5432
      protocol: TCP
```

**Разрешение трафика между репликами (для кворумных систем):**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: postgres-allow-replicas
spec:
  podSelector:
    matchLabels:
      app: postgres
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: postgres  # Реплики могут общаться друг с другом
    ports:
    - port: 5432
      protocol: TCP
  - from:
    - podSelector:
        matchLabels:
          app: backend
    ports:
    - port: 5432
      protocol: TCP
```

**Ограничение DNS-доступа (egress):**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: postgres-restrict-egress
spec:
  podSelector:
    matchLabels:
      app: postgres
  policyTypes:
  - Egress
  egress:
  - to:  # Разрешить DNS
    - namespaceSelector: {}
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
  - to:  # Разрешить трафик к другим репликам
    - podSelector:
        matchLabels:
          app: postgres
    ports:
    - port: 5432
      protocol: TCP
```

Подробнее: [NetworkPolicy](../../Security/network_policies.md), [Multi-tenancy](../../Concepts/multi-tenancy.md).

### Взаимодействие с ResourceQuota и LimitRange

При масштабировании StatefulSet в namespace с ResourceQuota могут возникнуть проблемы:

**Типичные ошибки:**

1. **`exceeded quota`** — при масштабировании вверх контроллер не может создать PVC, потому что лимит на количество PVC исчерпан.
2. **`insufficient cpu/memory`** — под не планируется, потому что requests превышают доступный бюджет.
3. **`exceeded object count`** — слишком много ControllerRevision (при частых обновлениях).

**Решения:**

```yaml
# ResourceQuota с учётом StatefulSet
apiVersion: v1
kind: ResourceQuota
metadata:
  name: statefulset-quota
  namespace: production
spec:
  hard:
    # Лимиты ресурсов
    requests.cpu: "20"
    requests.memory: "40Gi"
    limits.cpu: "40"
    limits.memory: "80Gi"
    # Лимиты объектов
    persistentvolumeclaims: "20"  # Достаточно для StatefulSet из 5 реплик с 2 томами
    pods: "50"
    services: "10"
    # Селектор для выделения бюджета под stateful workload
    count/statefulsets.apps: "10"
```

```yaml
# LimitRange для значений по умолчанию (если под не задаёт resources)
apiVersion: v1
kind: LimitRange
metadata:
  name: statefulset-limits
  namespace: production
spec:
  limits:
  - type: Container
    default:
      cpu: "500m"
      memory: "1Gi"
    defaultRequest:
      cpu: "250m"
      memory: "512Mi"
    max:
      cpu: "4"
      memory: "16Gi"
    min:
      cpu: "100m"
      memory: "256Mi"
```

**Важно:** Terminating-поды по-прежнему учитываются в ResourceQuota. При массовом обновлении StatefulSet (удаление + пересоздание подов) квота может быть временно исчерпана старыми подами в статусе `Terminating`. Решение: увеличить缓冲 или использовать `优雅ное завершение` с коротким `terminationGracePeriodSeconds`.

Подробнее: [ResourceQuota и LimitRange](../../Troubleshooting/Common_Errors/pod_pending/definitions_and_concepts.md).

### Chaos Engineering и тестирование отказов StatefulSet

Регулярное тестирование отказов (Chaos Engineering) критично для production-БД в Kubernetes. Цель — убедиться, что система восстанавливается после сбоев без потери данных.

**Типовые эксперименты:**

| Эксперимент | Инструмент | Ожидаемый результат |
|:---|:---|:---|
| Удаление пода БД | `kubectl delete pod db-0` | Контроллер пересоздаёт под с тем же PVC, данные сохраняются |
| Падение узла | Chaos Mesh: `PodChaos` (node failure) | При `out-of-service` taint под пересоздаётся на другом узле |
| Задержка сети между репликами | Chaos Mesh: `NetworkChaos` (delay 500ms) | Кворум сохраняется, replication lag растёт, но запись продолжается |
| Потеря диска | LitmusChaos: `DiskFill` | Алерт на заполнение диска, при критическом уровне — failover |
| Ограничение CPU | Chaos Mesh: `CPUChaos` | Под не убивается ( Guaranteed QoS), но латентность растёт |

**Пример эксперимента с Chaos Mesh:**

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: postgres-pod-delete
  namespace: production
spec:
  action: pod-chaos
  mode: one
  selector:
    labelSelectors:
      app: postgres
  duration: "5m"
  scheduler:
    cron: "@weekly"  # Раз в неделю
```

**Чек-лист для «пожарных учений»:**

1.  Удалить под `db-0` (лидер) → проверить, что лидерство перешло на другой под
2.  Заблокировать сетевой трафик между репликами на 30 секунд → проверить, что кворум сохраняется
3.  Заполнить диск на 90% → проверить, что алерт срабатывает за 5 минут
4.  Выполнить `kubectl drain` на узле с master-репликой → проверить, что под пересоздаётся
5.  Проверить RPO/RTO: время восстановления после каждого эксперимента

Подробнее: [Chaos Engineering Overview](../../../Chaos_Engineering/chaos_engineering_overview.md), [Chaos Engineering Tools](../../../Chaos_Engineering/chaos_engineering_tools.md).

## Дополнительная информация

### Ограничения

*   **Zone awareness:** При использовании RWO-дисков под привязан к зоне. Миграция в другую зону требует ручного копирования данных или использования мультизональных хранилищ.
*   **Manual recovery:** При сбое узла (Node Failure) может потребоваться ручное удаление пода или подтверждение `out-of-service`, так как контроллер не переносит поды автоматически из соображений целостности данных.
*   **Нет `maxSurge`:** StatefulSet не может создать "лишние" реплики до удаления старых (в отличие от Deployment) — каждая реплика жёстко привязана к своему PVC. Планируйте окна простоя/бюджет обновления через `maxUnavailable` (Beta v1.35+).
*   **Нет `pause/resume` rollout:** пауза обновления выполняется только через `partition`; откат — только `rollout undo`.
*   **Иммутабельность:** `selector.matchLabels` и `volumeClaimTemplates` неизменяемы после создания. Изменение размера тома — каскадная процедура (см. [Практическое руководство](./statefulset_practical_guide.md)).
*   **Индекс 0 как критическая точка:** лидер/координатор обычно привязан к `*-0`; при его длительном простое кворум может быть утрачен. Назначайте `priorityClassName` и контролируйте его через PDB/алерты.
*   **Взаимодействие `partition` и HPA:** при активном канареечном обновлении не полагайтесь на HPA — добавленные реплики могут остаться на старой ревизии.
*   **Известные проблемы:** застревание RollingUpdate при плохой ревизии (см. [Обзор — диагностика](./statefulset_overview.md#диагностика-и-устранение-неполадок)); при `OnDelete` обновление не начнётся, пока поды не будут удалены вручную.

### См. также

*   **[Обзор StatefulSet](./statefulset_overview.md)** — архитектура и базовые понятия.
*   **[Ключевые концепции](./statefulset_core_concepts.md)** — детальный разбор механизмов идентификации.
*   **[Практическое руководство](./statefulset_practical_guide.md)** — примеры реализации манифестов.
*   **[Local PV vs CSI](./statefulset_local_pv_vs_csi.md)** — выбор хранилища для БД.
*   **[Exporter Sidecar](./statefulset_exporter_sidecar.md)** — мониторинг БД через Prometheus.

### Когда выбирать StatefulSet, а когда — Operator

StatefulSet — базовый строительный блок для приложений с состоянием. Operator — автоматизация поверх StatefulSet, добавляющая CRD, консольную логику и интеграцию с DCS (etcd/Consul).

**StatefulSet достаточен для:**
- Простой репликации (master-slave) без автоматического failover
- Тестовых и dev-окружений
- Приложений, где failover выполняется на уровне приложения (Kafka, Cassandra)
- БД с одной репликой (单点写)

**Operator необходим для:**
- Автоматического failover (Patroni, CloudNativePG)
- Онлайн-бэкапов и восстановления (pgBackRest, Velero)
- Автоматического масштабирования реплик
- Управления репликацией (GTID, streaming replication)
- Обновления мажорных версий БД без даунтайма

**Популярные операторы:**

| БД | Оператор | Управляет |
|:---|:---|:---|
| PostgreSQL | CloudNativePG, Zalando Operator (Patroni) | StatefulSet, репликация, failover, бэкапы |
| Kafka | Strimzi | StatefulSet, KafkaTopic, KafkaUser, Entity Operator |
| MongoDB | MongoDB Community Operator | ReplicaSet, аутентификация, TLS |
| MySQL | MySQL Operator for Kubernetes | InnoDB Cluster, репликация |
| RabbitMQ | RabbitMQ Cluster Operator | Quorum Queues, clustering |
| Cassandra | CassKop | StatefulSet, racks, reconciliation |

**Паттерн:** Operator управляет StatefulSet, но добавляет CRD, консольную логику, интеграцию с DCS. Не изобретайте велосипед — используйте проверенные операторы для production-БД.