# StatefulSet: Лучшие практики

**Актуально для:** Kubernetes 1.30–1.37+ (Bare-Metal / On-Premise)

## Определения

**StatefulSet: Лучшие практики** — экспертный свод рекомендаций и инженерных стандартов по проектированию, конфигурированию, обеспечению безопасности и эксплуатации приложений с состоянием в Kubernetes для инженеров DevOps, SRE и системных администраторов. Основная цель — гарантировать целостность данных, предотвратить ситуации расщепления кворума (split-brain), обеспечить максимальную доступность (HA) и предсказуемость поведения системы при пиковых нагрузках, плановом обслуживании узлов и аппаратных сбоях.

## Предварительные требования

1. **Версия кластера:** Базовые механизмы стабильны в релизах **v1.30–v1.37+**. В частности:
   * Политика удержания PVC (`persistentVolumeClaimRetentionPolicy`) — GA с v1.32.
   * Аварийное восстановление узла (Non-Graceful Node Shutdown / taint `node.kubernetes.io/out-of-service`) — GA с v1.28.
   * Метка индекса пода (`apps.kubernetes.io/pod-index`) — GA с v1.32.
   * Задержка готовности (`minReadySeconds`) — GA с v1.25.
   * Динамическое изменение ресурсов без перезапуска (In-Place Pod Resize) — GA с v1.35.
   * Параллельное обновление с лимитом недоступности (`rollingUpdate.maxUnavailable`) — Beta v1.35+ (в v1.35–v1.36 требовалась осторожность из-за deadlock-бага kubernetes/kubernetes#137409 при `Parallel`, исправлено в v1.37).
   Проверка версии кластера: `kubectl version -o yaml`.
2. **Базовые знания:** Устройство подов ([Pod](../Pod/pod_overview.md)), хранилища ([PV и PVC](../../Storage/pv_and_pvc.md)), безадресного сервиса ([Headless Service](../../Networking/Service/service_type_headless.md)), зондов готовности и жизнеспособности ([Probes](../probes.md)).
3. **Архитектурная база:** Механика контроллера, контроллер ревизий (ControllerRevision) и жизненный цикл подробно описаны в **[Обзоре](./statefulset_overview.md)** и **[Ключевых концепциях](./statefulset_core_concepts.md)**; в данном документе фокус сосредоточен на правилах эксплуатации, отказоустойчивости и практических сценариях SRE.
4. **RBAC:** Права на управление объектами `statefulsets`, `pods`, `persistentvolumeclaims`, `poddisruptionbudgets`, `nodes`, `events`.

## Основные концепции

### Обеспечение высокой доступности (HA)

Для распределенных систем (СУБД, кворумные хранилища, брокеры сообщений) критически важно предотвратить одновременный выход из строя большинства реплик:

1. **Pod Disruption Budget (PDB):** Гарантирует минимальное количество доступных реплик при добровольном выселении подов (например, при выполнении `kubectl drain` перед обновлением ядра ОС узла).
   * **Кворумная формула:** Для нечетного числа реплик `N` устанавливайте `minAvailable: ⌈N/2⌉` (для 3 реплик `minAvailable: 2`, для 5 реплик `minAvailable: 3`). Падение ниже строгого кворума `(N/2)+1` приводит к переходу СУБД в режим Read-Only или полному отказу на запись, поэтому бюджет прерываний обязан защищать кворум.
   * Для кластеров с 3 репликами используйте `minAvailable: 2` (или `maxUnavailable: 1`).
   * **Политика нездоровых подов (`spec.unhealthyPodEvictionPolicy: AlwaysAllow`):** По умолчанию в Kubernetes действует политика `IfHealthyBudget`. Если одна реплика StatefulSet уже упала или не проходит readiness-пробу, PDB блокирует выселение любых подов в кластере, парализуя автоматический дренаж узлов. Установка флага `AlwaysAllow` (GA с v1.27) разрешает выселение уже неисправного пода, что позволяет планировщику быстрее пересоздать его на здоровом оборудовании.
   * **Взаимодействие с обслуживанием:** PDB защищает только от *добровольных* прерываний (API Eviction). Аппаратный сбой узла (kernel panic, отключение питания) или ручной taint `node.kubernetes.io/out-of-service` не блокируются PDB. Слишком жесткий PDB (`minAvailable: 100%`) делает узлы неудаляемыми для автоматизации и полностью блокирует плановые работы. Детали: [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md).
2. **Pod Anti-Affinity:** Используйте жесткие правила взаимного исключения (`requiredDuringSchedulingIgnoredDuringExecution`), чтобы поды одного кластера не оказывались на одном физическом сервере.
   * Топологический ключ для физических хостов: `kubernetes.io/hostname`.
   * Топологический ключ для стойки или машинного зала в On-Premise инфраструктуре: `topology.kubernetes.io/zone` или пользовательские метки узлов (например, `topology.kubernetes.io/rack`).
   * **Риск жесткого правила:** Если число доступных физических узлов (или серверных стоек) меньше числа реплик StatefulSet, лишние поды навсегда зависнут в статусе `Pending`. При нехватке узлов для вторичных зон используйте комбинацию: жесткое разделение по `kubernetes.io/hostname` и мягкое (`preferredDuringSchedulingIgnoredDuringExecution`) по стойкам/зонам.
   * Пример манифеста анти-аффинити:
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
3. **Топологические ограничения (`topologySpreadConstraints`):** Современный стандарт распределения подов по узлам и стойкам. В отличие от бинарного Anti-Affinity, механизм `maxSkew` распределяет реплики равномерно. Для On-Premise инфраструктуры со стойками:
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
4. **Стабильность запуска (`minReadySeconds`):** Устанавливайте паузу (например, `30–120` секунд) в спецификации StatefulSet. Это гарантирует, что контроллер не начнет обновление или запуск следующего по порядку пода (`N+1` или `N-1`), пока текущий экземпляр не проработает без сбоев указанное время после успешного прохождения readiness-пробы. Это предотвращает ложную готовность, когда сервис открыл сетевой сокет, но еще не завершил синхронизацию репликационного журнала или кворумного соглашения.
5. **Проектирование количества реплик:** Для всех кворумных систем (Raft, Paxos, Zab) всегда выбирайте **нечетное** количество реплик (3, 5). Кластер из 4 узлов выдерживает падение только 1 узла (кворум 3 из 4), как и кластер из 3 узлов, но создает повышенную нагрузку на сеть синхронизации.
6. **Защита критичных подов приоритетом (`priorityClassName`):** Базы данных и брокеры сообщений должны иметь более высокий приоритет, чем фоновые stateless-воркеры. В условиях жесткого дефицита ресурсов на bare-metal узлах системный планировщик вытесняет (preempt) поды с низким приоритетом, сохраняя работу критичных stateful-сервисов. Подробнее: [PriorityClass](../../Concepts/priorityclass.md).

### Управление хранилищем и данными

Ошибки в настройке CSI-драйверов и блочных устройств приводят к повреждению баз данных, аварийным перезапускам или вечному статусу `Pending`:

* **Отложенное связывание (`volumeBindingMode: WaitForFirstConsumer`):** Единственно допустимый режим StorageClass для StatefulSet. Он запрещает динамическое выделение диска до тех пор, пока планировщик Kubernetes не выберет конкретный узел для пода с учетом всех правил affinity, tolerations и доступных ресурсов CPU/RAM. Режим `Immediate` приводит к тому, что том выделяется на случайном узле или в произвольной стойке, после чего под не может запуститься из-за топологического конфликта (`volume node affinity conflict`).
* **Выбор класса хранения под нагрузку (Bare-Metal / On-Premise):**
  * *Локальные диски (NVMe/SATA SSD через Local PV, TopoLVM, OpenEBS LocalPV):* Обеспечивают минимальную задержку (sub-millisecond latency), максимальный IOPS и полное отсутствие сетевых накладных расходов. Рекомендуются для высоконагруженных СУБД (PostgreSQL, MySQL, ClickHouse, etcd), где отказоустойчивость и репликация реализованы на уровне самого приложения. Недостаток — под жестко привязан к конкретному серверу; при физической гибели сервера требуется инициализация новой реплики с нуля.
  * *Сетевые распределенные блочные хранилища (Ceph RBD, Longhorn, SAN iSCSI):* Предоставляют отказоустойчивость на уровне дисковой подсистемы, поддержку снапшотов и возможность миграции пода на другой рабочий узел без перекачки данных. Плата за это — накладные расходы сети, повышение latency дисковых операций и зависимость от стабильности сети хранения данных. Подробнее: [StorageClass](../../Storage/storageclass.md) и [Local PV vs CSI](./statefulset_local_pv_vs_csi.md).
* **Безопасность прав доступа и производительность монтирования (`fsGroup`):**
  * Всегда явно указывайте `fsGroup` в `pod.spec.securityContext`, чтобы монтируемые блочные устройства автоматически получали корректный GID доступа для непривилегированного процесса.
  * **Оптимизация старта (`fsGroupChangePolicy: OnRootMismatch`):** По умолчанию kubelet при каждом старте пода выполняет рекурсивный `chown` и `chmod` для всех файлов на томе. На базах данных с миллионами файлов и терабайтными объемами это приводит к зависанию пода в `ContainerCreating` на 10–30 минут и падению по тайм-ауту. Флаг `OnRootMismatch` (GA с v1.23) указывает kubelet выполнять рекурсивную смену прав только в том случае, если права корневой директории тома не совпадают с целевым GID.
* **Политика удержания PVC (`persistentVolumeClaimRetentionPolicy` — GA v1.32):**
  * `whenDeleted: Retain` — обязательный стандарт для Production. Гарантирует, что при случайном или преднамеренном удалении манифеста StatefulSet (`kubectl delete statefulset`) тома PVC с данными останутся в кластере невредимыми.
  * `whenScaled: Retain` — стандарт для баз данных. Защищает от потери данных при ошибочном уменьшении масштаба (`kubectl scale --replicas=N`).
  * `whenScaled: Delete` — применяется исключительно для горизонтально масштабируемых кэшей или узлов обработки очередей, где каждый индекс не содержит уникального состояния и может быть безопасно отброшен.
* **Расширение томов в онлайне:** Включайте `allowVolumeExpansion: true` в StorageClass. Это позволяет увеличивать размер диска без удаления PVC. Для StatefulSet процедура расширения выполняется декларативно путем правки каждого существующего PVC и последующего обновления шаблона `volumeClaimTemplates` (или через каскадное пересоздание StatefulSet без удаления подов). Подробная инструкция: [Практическое руководство](./statefulset_practical_guide.md).
* **Запрет общего RWX-хранилища:** Подключение одного и того же NFS/CephFS тома в режиме `ReadWriteMany` ко всем репликам StatefulSet нарушает архитектурный контракт контроллера. Каждая реплика обязана иметь собственный независимый PVC. Общие тома допустимы только в Deployment.
* **Резервное копирование и консистентность:** Состояние StatefulSet складывается из физических томов PVC и метаданных Kubernetes. Настройте создание регулярных аппаратных/CSI-снимков (`VolumeSnapshot`) с вызовом Pre/Post-хуков (например, `fsfreeze` или `pg_backup_start() / pg_backup_stop()`) для обеспечения crash-consistent или application-consistent снимков, либо логические дампы с непрерывной архивацией WAL. Регулярно тестируйте процедуру Disaster Recovery (восстановление из бэкапа по таймеру RTO). Методология: [Резервное копирование и DR](../../Operations/backup-strategies.md).
* **Инвентаризация и очистка осиротевших PVC:** При масштабировании вниз удаленный под не удаляет свой PVC. Со временем неиспользуемые тома накапливаются и расходуют дисковый пул кластера:
  ```bash
  kubectl get pvc -l app=postgres
  # Удаление только после валидации и вывода реплики из топологии кластера СУБД:
  kubectl delete pvc data-postgres-2
  ```

### Ресурсы и планирование (QoS)

Для критических приложений с состоянием единственным допустимым классом обслуживания в Production является **Guaranteed**:

* **Симметрия запросов и лимитов:** Задавайте `requests` строго равными `limits` по CPU и Memory:
  ```yaml
  resources:
    requests:
      cpu: "4000m"
      memory: "16Gi"
    limits:
      cpu: "4000m"
      memory: "16Gi"
  ```
  Это присваивает поду класс обслуживания `Guaranteed`, устанавливает значение `oom_score_adj` в `-997` и защищает под от выселения планировщиком при возникновении `NodeAllocatableMemoryPressure` на узле.
* **Расчет памяти и защита от OOM Killer:** Лимит памяти контейнера в манифесте должен превышать рабочую память СУБД на 20–30%. Внутренние пулы СУБД (например, `shared_buffers + work_mem * max_connections` в PostgreSQL или `-Xmx` в JVM) резервируют память под данные, однако процессу требуются ресурсы на обслуживание сетевых сокетов, форки процессов, динамические библиотеки и дисковый кэш. Превышение лимита вызывает мгновенное завершение процесса ядром Linux (`OOMKilled`, exit code 137).
* **Изоляция ядер процессора (CPU Manager):** На bare-metal узлах под управлением kubelet активируйте флаг `--cpu-manager-policy=static`. Для подов класса `Guaranteed` с целочисленными запросами CPU (например, `4000m` или `8`) kubelet выделяет выделенные физические процессорные ядра (exclusive CPU pinning), отключая переключение контекста и исключая деградацию латентности из-за других процессов.
* **HugePages для тяжелых СУБД:** В bare-metal окружениях базы данных (PostgreSQL, Oracle, Java) тратят значительную часть ресурсов CPU на поддержание таблиц страниц памяти TLB. Запрашивайте выделенные страницы памяти через ресурсы пода:
  ```yaml
  resources:
    requests:
      memory: "16Gi"
      hugepages-2Mi: "8Gi"
    limits:
      memory: "16Gi"
      hugepages-2Mi: "8Gi"
  ```
* **Динамическое изменение ресурсов (In-Place Pod Resize — GA v1.35):** Позволяет менять CPU и память работающего пода без его перезапуска. Это устраняет необходимость пересоздания подов StatefulSet при вертикальном масштабировании. Подробнее: [In-Place Pod Resize](../../Autoscaling/in_place_pod_resize.md).

### Сетевая идентификация и DNS

* **Обязательность Headless Service:** Поле `.spec.serviceName` в StatefulSet должно строго совпадать с именем сервиса с `clusterIP: None`. Только в этом случае CoreDNS формирует детерминированные A/AAAA-записи вида `<pod-name>.<service-name>.<namespace>.svc.cluster.local`.
* **Публикация адресов до готовности (`publishNotReadyAddresses: true`):** Для распределенных систем с кворумным бутстрапом (etcd, ZooKeeper, Cassandra, Patroni) реплики обязаны связаться друг с другом по сети до того, как они будут признаны `Ready`. Без этого флага в Headless Service возникает взаимная блокировка («курица и яйцо»): поды не получают DNS-имена соседей, пока не пройдут пробу готовности, а пробу готовности они не могут пройти, пока не соберут кворум. Детали: [Headless Service](../../Networking/Service/service_type_headless.md).
* **Инъекция идентификаторов через Downward API:** Не зашивайте сетевые имена в конфигурационные файлы приложения. Передавайте имя пода и его индекс напрямую из метаданных:
  ```yaml
  env:
  - name: POD_NAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.name
  - name: POD_INDEX
    valueFrom:
      fieldRef:
        fieldPath: metadata.labels['apps.kubernetes.io/pod-index']
  ```
* **Локальный DNS-кэш на узлах (NodeLocal DNSCache):** Высоконагруженные кластеры баз данных генерируют сотни запросов к DNS в секунду при межрепликационном обмене. В Linux это приводит к гонкам в таблице трансляции сетевых адресов (`conntrack UDP race`) и случайным задержкам ответов до 5 секунд. Развертывание `NodeLocal DNSCache` в виде DaemonSet на локальном IP `169.254.20.10` устраняет задержки и снижает нагрузку на CoreDNS. Подробнее: [DNS deep dive](../../Networking/dns_deep_dive.md).
* **Синхронизация тайм-аута остановки (`terminationGracePeriodSeconds`):** Для баз данных устанавливайте интервал завершения в диапазоне `120–300` секунд. Процессу требуется время на сброс грязных страниц из буферного кэша на диск (`fsync`), фиксацию контрольной точки (checkpoint) и передачу полномочий мастера здоровой реплике.
* **Сетевая изоляция (NetworkPolicy):** По умолчанию внутри namespace разрешен любой трафик. Для защиты данных СУБД изолируйте порт базы данных, разрешив входящие подключения только со стороны доверенных подов бэкенда и соседних реплик кластера.

### Безопасность

* **Непривилегированный пользователь (`runAsNonRoot: true`):** Процессы СУБД никогда не должны выполняться от пользователя `root`. Явно фиксируйте `runAsUser` и `runAsGroup` (например, `999` для PostgreSQL).
* **Изолированная файловая система (`readOnlyRootFilesystem: true`):** Монтируйте корень контейнера только для чтения. Все изменяемые каталоги (каталог данных, логи, временные файлы) должны быть вынесены на смонтированные тома (`persistentVolumeClaim` под данные, `emptyDir` под `/tmp` и `/run`).
* **Ограничение прав ServiceAccount:** Отключайте автоматическое монтирование API-токена в под, если база данных не взаимодействует с Kubernetes API:
  ```yaml
  spec:
    template:
      spec:
        automountServiceAccountToken: false
  ```
* **Защита секретов:** Пароли репликации и сертификаты TLS передавайте через монтирование объектов `Secret` в режиме `readOnly: true`. Запретите использование открытых строк в переменных окружения манифестов.
* **Иммутабельность конфигураций (`immutable: true`):** Отмечайте ConfigMap и Secret как неизменяемые. Это предотвращает случайное повреждение конфигурации СУБД «на лету» и гарантирует, что любое изменение конфига будет выполняться предсказуемо через создание новой ревизии и rolling update подов.
* **Фиксация образов:** Запретите использование тега `:latest`. Указывайте точную версию образа или его неизменяемый sha256-дайджест (`image@sha256:...`), чтобы избежать неконтролируемого обновления минорных версий при пересоздании пода.

## Мониторинг и эксплуатация

### Ключевые метрики для алертинга

Для надежного наблюдения за StatefulSet через Prometheus и `kube-state-metrics` системный администратор и SRE обязаны отслеживать следующие критические сигналы:

| Сигнал SRE | PromQL-выражение | Порог срабатывания | Инженерный смысл и действие |
| :--- | :--- | :--- | :--- |
| **Деградация кворума** | `kube_statefulset_status_replicas_ready != kube_statefulset_replicas` | `for: 5m` | Часть реплик не готова. Риск потери кворума при следующем сбое. Проверить события пода. |
| **Зависшее обновление** | `kube_statefulset_status_observed_generation == kube_statefulset_metadata_generation and kube_statefulset_status_replicas_updated < kube_statefulset_replicas` | `for: 15m` | Раскатка новой версии остановилась. Проверить readiness-пробу, логи пода и параметр `partition`. |
| **Застревание PVC** | `kube_persistentvolumeclaim_status_phase{phase!="Bound"} == 1` | `for: 5m` | Диск не может выделиться из-за нехватки емкости пула, сбоя CSI или конфликта топологии узла. |
| **Заполнение тома СУБД** | `(1 - (kubelet_volume_stats_available_bytes / kubelet_volume_stats_capacity_bytes)) * 100 > 85` | `for: 10m` | Опасность аварийной остановки СУБД (PostgreSQL переходит в аварийный panic/read-only при заполнении диска). |
| **Превышение лимита памяти** | `(container_memory_working_set_bytes{container!="POD"} / container_spec_memory_limit_bytes) * 100 > 90` | `for: 3m` | Риск мгновенного OOMKill процесса базы данных ядром Linux. |
| **Зависание в Terminating** | `kube_pod_status_phase{phase="Terminating"} == 1` | `for: 10m` | Блокировка отмонтирования тома RWO контроллером CSI на недоступном узле. |

Подробнее о мониторинге инфраструктуры: **[Grafana: алерты Kubernetes](../../../Grafana/alerting/kubernetes_alerts.md)** и **[Архитектура мониторинга](../../MonitoringLogging/kubernetes-monitoring-logging-architecture.md)**.

### Плановое обслуживание узлов (Node Maintenance)

Регламент безопасного вывода физического сервера из эксплуатации для проведения аппаратных работ или обновления ОС:

```bash
# 1. Проверить статус бюджета PDB для всех stateful-нагрузок
kubectl get pdb -A
# → NAME           MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → postgres-pdb   2               N/A               1                     45d

# 2. Перевести узел в режим обслуживания (запрет новых подов)
kubectl cordon node-1
# → node/node-1 cordoned

# 3. Безопасно дренировать узел (выселение с учетом PDB)
kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data --timeout=10m
# → evicting pod production/postgres-2
# → pod/postgres-2 evicted
# → node/node-1 drained

# 4. Проверить, что выселенный под успешно поднялся на другом сервере
kubectl rollout status statefulset/postgres -n production --timeout=300s
# → Waiting for 1 pods to be ready...
# → statefulset rolling update complete 3 pods at revision postgres-64b4c...

# 5. После завершения работ вернуть сервер в строй
kubectl uncordon node-1
# → node/node-1 uncordoned
```

*SRE-правило:* Никогда не дренируйте два сервера одновременно при работе с 3-узловыми кворумными СУБД. Выселение второй реплики до полного восстановления первой гарантированно разрушит кворум. Подробнее: [Обслуживание узлов](../../Operations/node_maintenance.md).

### Аварийный отказ узла (Non-Graceful Node Shutdown)

Если физический сервер внезапно завис, потерял сетевую связность или сгорел блок питания, контроллер Kubernetes **не имеет права** автоматически пересоздать под StatefulSet на другом сервере. Поскольку диск имеет режим доступа `ReadWriteOnce` (RWO), запуск двух экземпляров пода с одним и тем же томом приведет к одновременной записи и непоправимому повреждению файловой системы (split-brain). Под зависнет в статусе `Terminating` или `Unknown`.

**Регламент восстановления (Non-Graceful Node Shutdown — GA v1.28):**

1. Через интерфейс удаленного управления сервером (IPMI, iLO, iDRAC) администратор обязан на 100% убедиться, что физический сервер полностью обесточен или изолирован от сети хранения данных.
2. Наложить на упавший узел специализированный taint `out-of-service`:
   ```bash
   kubectl taint nodes node-crash-1 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
   # → node/node-crash-1 tainted
   ```
3. Контроллер Kubernetes зафиксирует гарантированную недоступность хоста, снимет блокировку `VolumeAttachment` в CSI-драйвере, принудительно удалит зависший под и запустит новую реплику StatefulSet на здоровом сервере с повторным подключением существующего PVC.
4. После физического ремонта сервера и его включения **обязательно** удалите наложенный taint:
   ```bash
   kubectl taint nodes node-crash-1 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute-
   # → node/node-crash-1 untainted
   ```

*Предостережение:* Категорически запрещено выполнять `kubectl delete pod <name> --force --grace-period=0` без предварительной изоляции узла или наложения таинта `out-of-service`. Принудительное удаление метаданных пода из etcd не отсоединяет диск от гипервизора или дисковой подсистемы, что приводит к ошибке `Multi-Attach error for volume` на новом узле.

### Автомасштабирование (HPA) и его ограничения

* **Совместимость с HPA:** Horizontal Pod Autoscaler поддерживается для StatefulSet (начиная с API `autoscaling/v2`).
* **Конфликт со статическим манифестом:** Если скейлингом управляет HPA, в манифесте StatefulSet поле `.spec.replicas` должно быть исключено либо настроено игнорирование через GitOps (например, `ignoreDifferences` в ArgoCD). Иначе каждый `kubectl apply` будет сбрасывать количество реплик к фиксированному значению.
* **Нижняя граница (`minReplicas`):** Для любых кворумных систем значение `minReplicas` в HPA обязано быть не меньше размера кворума (обычно не менее 3). Скейлинг вниз до 1–2 реплик приведет к деградации и невозможности выбора лидера.
* **Конфликт HPA и канареечного `partition`:** При активном канареечном обновлении (когда `partition > 0`) масштабирование вверх через HPA добавит новые реплики, которые останутся на старой ревизии, искажая логику тестирования.

## Практические сценарии

### Сценарий 1: Канареечное обновление через Partition

Для критических баз данных используйте стратегию поэтапного обновления с фиксацией границы `partition`:

```bash
# 1. Зафиксировать partition на уровне N-1 (для 3 реплик: partition=2).
# Это указывает контроллеру обновить только последний под postgres-2.
kubectl patch statefulset postgres -n production -p '{"spec":{"updateStrategy":{"type":"RollingUpdate","rollingUpdate":{"partition":2}}}}'
# → statefulset.apps/postgres patched

# 2. Применить новый образ контейнера
kubectl set image statefulset/postgres postgres=postgres:16.4 -n production
# → statefulset.apps/postgres image updated

# 3. Убедиться, что обновился ТОЛЬКО под с индексом 2, а поды 0 и 1 остались на старой версии
kubectl get pods -l app=postgres -n production -o custom-columns=NAME:.metadata.name,IMAGE:.spec.containers[0].image
# → NAME         IMAGE
# → postgres-0   postgres:16.3
# → postgres-1   postgres:16.3
# → postgres-2   postgres:16.4

# 4. Провести аудит логов и мониторинг метрик пода postgres-2
kubectl logs postgres-2 -n production --tail=50

# 5. При отсутствии ошибок снять границу (partition=0) для последовательного обновления остальных подов
kubectl patch statefulset postgres -n production -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":0}}}}'
# → statefulset.apps/postgres patched

# 6. Дождаться успешного завершения всего обновления
kubectl rollout status statefulset/postgres -n production --timeout=600s
# → statefulset rolling update complete 3 pods at revision postgres-78c5d...
```

### Сценарий 2: Защита от аварийного перезапуска при долгом восстановлении (WAL Replay)

После нештатной перезагрузки серверу СУБД требуется значительное время на проверку целостности таблиц и проигрывание журнала транзакций (WAL replay). Если в этот момент сработает стандартная `livenessProbe`, kubelet принудительно убьет процесс, вызвав каскадное повреждение данных.

Используйте **Startup Probe** для предоставления расширенного временного окна на холодный старт:

```yaml
spec:
  template:
    spec:
      containers:
      - name: postgres
        image: postgres:16.4
        startupProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - pg_isready -h 127.0.0.1 -U postgres
          initialDelaySeconds: 10
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 30       # 10с + 30 * 10с = до 310 секунд на восстановление базы
        readinessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - pg_isready -h 127.0.0.1 -U postgres
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 3
        livenessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - pg_isready -h 127.0.0.1 -U postgres
          initialDelaySeconds: 10
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
```

*Механика:* Пока `startupProbe` не завершится успехом, проверки `livenessProbe` и `readinessProbe` полностью заблокированы и не опрашивают контейнер. Это исключает цикличный перезапуск (`CrashLoopBackOff`) во время долгого старта. Подробнее: [Probes](../probes.md).

### Сценарий 3: Корректное завершение работы с синхронизацией буферов (preStop)

Чтобы предотвратить повреждение данных при плановой остановке пода, необходимо предоставить СУБД возможность сбросить грязные буферы на диск и корректно разорвать клиентские соединения:

```yaml
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 180
      containers:
      - name: postgres
        image: postgres:16.4
        lifecycle:
          preStop:
            exec:
              command:
              - /bin/sh
              - -c
              - |
                # Запуск принудительного сброса буферов на диск перед получением SIGTERM
                psql -h 127.0.0.1 -U postgres -c "CHECKPOINT;" >/dev/null 2>&1 || true
                # Ожидание завершения активных пишущих транзакций
                sleep 5
```

*Последовательность выключения:* Kubelet исключает под из EndpointSlice сервиса → параллельно вызывается хук `preStop` → после завершения хука контейнеру посылается сигнал `SIGTERM` → если процесс не завершился в течение `terminationGracePeriodSeconds`, посылается сигнал принудительного уничтожения `SIGKILL`.

### Сценарий 4: Масштабирование кворумного кластера без деградации

Порядок безопасного изменения количества узлов:

1. **Проверка текущей доступности:** Убедитесь, что все существующие реплики находятся в статусе `Ready`:
   ```bash
   kubectl get pods -l app=postgres -n production
   # → NAME         READY   STATUS    RESTARTS   AGE
   # → postgres-0   1/1     Running   0          12d
   # → postgres-1   1/1     Running   0          12d
   # → postgres-2   1/1     Running   0          12d
   ```
2. **Масштабирование вверх:** Выполните добавление узлов до нечетного числа (например, с 3 до 5):
   ```bash
   kubectl scale statefulset postgres --replicas=5 -n production
   # → statefulset.apps/postgres scaled
   ```
   Контроллер последовательно создаст поды `postgres-3`, затем `postgres-4`, дожидаясь готовности каждого.
3. **Обновление PDB:** Пересчитайте бюджет прерываний под новое число реплик:
   ```bash
   kubectl patch pdb postgres-pdb -n production -p '{"spec":{"minAvailable":3}}'
   # → poddisruptionbudget.policy/postgres-pdb patched
   ```
4. **Масштабирование вниз:** Уменьшение масштаба всегда удаляет поды с максимальным индексом (`postgres-4`, затем `postgres-3`). Перед уменьшением масштаба убедитесь, что распределенная СУБД (Kafka, Cassandra, Elasticsearch) вывела данные с удаляемых узлов на оставшиеся.

### Сценарий 5: Сетевая изоляция (NetworkPolicy) для базы данных

Пример строгой изоляции базы данных в On-Premise кластере (Default Deny с точечным разрешением):

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: postgres-network-policy
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: postgres
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # 1. Разрешить входящий трафик от бэкенд-сервисов на порт БД
  - from:
    - podSelector:
        matchLabels:
          app: backend
      namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: production
    ports:
    - protocol: TCP
      port: 5432
  # 2. Разрешить трафик между репликами базы данных (межрепликационная синхронизация)
  - from:
    - podSelector:
        matchLabels:
          app: postgres
    ports:
    - protocol: TCP
      port: 5432
  egress:
  # 1. Разрешить исходящий DNS-трафик к CoreDNS / NodeLocal DNSCache
  - to:
    - namespaceSelector: {}
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  # 2. Разрешить исходящий трафик к другим репликам для передачи WAL
  - to:
    - podSelector:
        matchLabels:
          app: postgres
    ports:
    - protocol: TCP
      port: 5432
```

Подробнее: [NetworkPolicy](../../Security/network_policies.md) и [Многоарендность](../../Concepts/multi-tenancy.md).

### Сценарий 6: Управление квотами ресурсов (ResourceQuota)

При планировании ресурсов в namespace со StatefulSet необходимо учитывать буфер под создаваемые тома и ControllerRevision:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: stateful-quota
  namespace: production
spec:
  hard:
    requests.cpu: "32"
    requests.memory: "64Gi"
    limits.cpu: "32"
    limits.memory: "64Gi"
    persistentvolumeclaims: "10"
    pods: "20"
    count/statefulsets.apps: "5"
```

*Важное замечание SRE:* Во время выполнения Rolling Update старый под некоторое время находится в статусе `Terminating`, пока новый под уже создается. В этот переходный момент оба пода потребляют квоту namespace по CPU, памяти и количеству подов. Если квота рассчитана «впритирку», создание нового пода завершится ошибкой `exceeded quota`. Всегда закладывайте буфер квоты минимум на 1–2 дополнительных пода и PVC на каждый StatefulSet.

### Сценарий 7: Тестирование отказоустойчивости (Chaos Engineering)

Регулярное тестирование сценариев сбоев позволяет верифицировать поведение кластера до наступления реальной аварии:

| Сценарий теста | Метод симуляции | Ожидаемый результат SRE |
| :--- | :--- | :--- |
| **Падение процесса** | `kubectl exec postgres-0 -- kill -9 1` | Kubelet перезапускает контейнер на том же узле, данные не повреждены. |
| **Внезапное выключение сервера** | Выключение питания через IPMI хоста | Под переходит в `Unknown`/`Terminating`, после наложения `out-of-service` taint пересоздается на другом сервере. |
| **Изоляция сети (Network Partition)** | Дроп пакетов между узлами через iptables | Кворум сохраняется на узлах большинства, изолированное меньшинство переходит в Read-Only. Split-brain исключен. |
| **Имитация задержек ввода-вывода** | Внесение дисковой задержки через Chaos-инструменты | СУБД детектирует лаг репликации, алерты мониторинга срабатывают до падения сервиса. |

Подробнее: [Обзор Chaos Engineering](../../../Chaos_Engineering/chaos_engineering_overview.md).

## Операции и команды

Сводка типовых операционных команд системного администратора и инженера SRE для диагностики и управления StatefulSet:

| Операция | Команда CLI | Ожидаемый результат / Проверка |
| :--- | :--- | :--- |
| **Статус выкатки** | `kubectl rollout status statefulset/postgres -n production` | `# → statefulset rolling update complete 3 pods at revision postgres-64b4c...` |
| **История ревизий** | `kubectl rollout history statefulset/postgres -n production` | `# → REVISION  CHANGE-CAUSE`<br>`# → 1         initial deploy`<br>`# → 2         upgrade to 16.4` |
| **Откат к ревизии** | `kubectl rollout undo statefulset/postgres --to-revision=1 -n production` | `# → statefulset.apps/postgres rolled back` |
| **Безопасный перезапуск** | `kubectl rollout restart statefulset/postgres -n production` | `# → statefulset.apps/postgres restarted` (поочередный перезапуск с конца к 0) |
| **Проверка PDB** | `kubectl get pdb -n production` | `# → NAME          MIN AVAILABLE   ALLOWED DISRUPTIONS`<br>`# → postgres-pdb  2               1` |
| **Инспекция томов PVC** | `kubectl get pvc -l app=postgres -n production -o wide` | `# → NAME            STATUS   VOLUME       CAPACITY   STORAGECLASS`<br>`# → data-postgres-0 Bound    pvc-123...   100Gi      local-nvme` |
| **Аварийный таинт узла** | `kubectl taint nodes node-2 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute` | `# → node/node-2 tainted` (разрешает перенос RWO томов на другой узел) |
| **Снятие аварийного таинта**| `kubectl taint nodes node-2 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute-` | `# → node/node-2 untainted` |
| **Инспекция контроллера** | `kubectl get controllerrevisions -l app=postgres -n production` | `# → NAME               CONTROLLER            REVISION   AGE`<br>`# → postgres-64b4c6...  statefulset/postgres  1          30d` |

## Диагностика и устранение неполадок

Типичные проблемы при эксплуатации StatefulSet и алгоритмы их устранения:

### 1. Ошибка Multi-Attach error for volume при переносе пода

* **Симптомы:** Под на новом узле завис в `ContainerCreating`. В выводе `kubectl describe pod` ошибка: `Multi-Attach error for volume "pvc-xxx" Volume is already exclusively attached to one node and can't be attached to another`.
* **Причина:** Старый узел аварийно завис или потерял сеть. Том RWO примонтирован к старому хосту, и CSI-драйвер защищает диск от одновременной записи.
* **Решение:**
  1. Убедиться через IPMI, что старый сервер выключен.
  2. Наложить на старый узел таинт:
     ```bash
     kubectl taint nodes old-node node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
     # → node/old-node tainted
     ```
  3. Контроллер автоматически удалит старый объект `VolumeAttachment`, после чего диск смонтируется на новом узле.

### 2. Под завис в статусе Pending при наличии свободных узлов

* **Симптомы:** Новый под StatefulSet не планируется. В `kubectl describe pod` сообщение: `0/5 nodes are available: 1 node(s) had volume node affinity conflict, 4 node(s) had pod anti-affinity rules`.
* **Причина:**
  1. Том PVC привязан к конкретному узлу (Local PV или WaitForFirstConsumer в другой зоне/стойке), и планировщик не может поместить под на другой хост.
  2. Правило `podAntiAffinity` запрещает запуск на узле, где уже работает соседняя реплика.
* **Решение:** Проверить доступность узла, к которому привязан диск. При аппаратной гибели хоста с Local PV требуется создать новый PVC и запустить реплику заново с синхронизацией данных по сети.

### 3. Ошибка прав доступа Permission Denied на смонтированном диске

* **Симптомы:** Контейнер падает с ошибкой `initdb: could not access directory "/var/lib/postgresql/data": Permission denied`.
* **Причина:** Корневая директория тома принадлежит пользователю `root (UID 0)`, а контейнер запускается под непривилегированным пользователем (например, `UID 999`).
* **Решение:**
  Указать `fsGroup` в контексте безопасности пода:
  ```yaml
  spec:
    securityContext:
      fsGroup: 999
      fsGroupChangePolicy: OnRootMismatch
  ```

### 4. Ошибка при расширении тома PersistentVolumeClaim

* **Симптомы:** Емкость PVC увеличена в манифесте, но в статусе пода объем остается прежним, либо появляется ошибка `volume expansion failed`.
* **Причина:** StorageClass не имеет флага `allowVolumeExpansion: true`, либо файловая система требует перезапуска пода для применения нового размера (`FileSystemResizePending`).
* **Решение:**
  1. Проверить StorageClass: `kubectl get sc <name> -o yaml | grep allowVolumeExpansion`.
  2. Если статус `FileSystemResizePending` — перезапустите под:
     ```bash
     kubectl delete pod postgres-0 -n production
     ```
     Kubelet при повторном монтировании выполнит расширение файловой системы (`resize2fs` или `xfs_growfs`).

### 5. Рассинхронизация и потеря кворума при Rolling Update

* **Симптомы:** При обновлении база данных переходит в Read-Only, клиенты получают ошибки `could not connect to primary`.
* **Причина:** Обновление выполнялось слишком быстро (`minReadySeconds` не задан, либо использовался `maxUnavailable > 1`), и новый узел был выведен на замену до того, как завершилась репликация данных.
* **Решение:**
  1. Немедленно зафиксировать границу обновления:
     ```bash
     kubectl patch statefulset postgres -n production -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":2}}}}'
     ```
  2. Восстановить работоспособность упавших реплик, дождаться завершения синхронизации и продолжить обновление только с поочередным контролем готовности.

## Рекомендации и лучшие практики

Сводный SRE-чек-лист готовности к Production (Production Readiness Checklist):

### 1. Архитектура и надежность
- [ ] Количество реплик строго нечетное (3 или 5 для кворумных систем).
- [ ] Настроен `PodDisruptionBudget` с защитой кворума (`minAvailable: ⌈N/2⌉`).
- [ ] Активирована политика `unhealthyPodEvictionPolicy: AlwaysAllow` в PDB.
- [ ] Настроено жесткое взаимное исключение подов (`podAntiAffinity` по `kubernetes.io/hostname`).
- [ ] Задано топологическое распределение по стойкам/зонам (`topologySpreadConstraints`).
- [ ] Установлен параметр `minReadySeconds: 30–120` для стабилизации сервиса перед обновлением следующего пода.
- [ ] Назначен `priorityClassName` выше уровня неприоритетных stateless-приложений.

### 2. Дисковая подсистема
- [ ] StorageClass настроен с обязательным флагом `volumeBindingMode: WaitForFirstConsumer`.
- [ ] Включен флаг `allowVolumeExpansion: true` для динамического увеличения размера дисков.
- [ ] В `securityContext` пода заданы `fsGroup` и `fsGroupChangePolicy: OnRootMismatch`.
- [ ] Политика `persistentVolumeClaimRetentionPolicy` установлена в `whenDeleted: Retain` и `whenScaled: Retain`.
- [ ] Настроено автоматизированное создание снимков томов (`VolumeSnapshot`) с проверкой RTO/RPO.
- [ ] Реализован регламент аудита и очистки осиротевших PVC после масштабирования.

### 3. Ресурсы и планирование
- [ ] Присвоен класс обслуживания `Guaranteed` (`requests == limits` по CPU и Memory).
- [ ] Лимит памяти контейнера превышает внутренние буферы СУБД минимум на 20–30%.
- [ ] Для bare-metal узлов настроен CPU Manager (`--cpu-manager-policy=static`) с целочисленными ядрами.
- [ ] При высоких требованиях к I/O настроены HugePages (`hugepages-2Mi`).

### 4. Сеть и безопасность
- [ ] Создан Headless Service (`clusterIP: None`) с именем, строго совпадающим с `.spec.serviceName`.
- [ ] Активирован флаг `publishNotReadyAddresses: true` для систем с кворумным бутстрапом.
- [ ] Развернут `NodeLocal DNSCache` на узлах кластера.
- [ ] Сконфигурирован `terminationGracePeriodSeconds: 120–300` с хуком `preStop`.
- [ ] Применен изолирующий `NetworkPolicy` (доступ к порту БД открыт только доверенным подам).
- [ ] Включен запуск от непривилегированного пользователя (`runAsNonRoot: true`).
- [ ] Корневая файловая система переведена в Read-Only (`readOnlyRootFilesystem: true`).
- [ ] Отключено монтирование токена ServiceAccount (`automountServiceAccountToken: false`).
- [ ] Конфигурационные файлы зафиксированы через неизменяемые ConfigMap (`immutable: true`).

## Дополнительная информация

### Ограничения

* **Привязка к топологии (Zone / Node Awareness):** При использовании локальных или блочных RWO-дисков под привязан к физическому серверу или стойке. Перенос пода между несовместимыми зонами требует репликации на уровне приложения.
* **Отсутствие автоматического переноса при сбое сервера:** Для защиты от повреждения данных контроллер не переносит под со сбойного узла автоматически. Требуется подтверждение аварии через наложение таинта `node.kubernetes.io/out-of-service`.
* **Отсутствие `maxSurge`:** StatefulSet принципиально не может создавать опережающие временные поды, так как каждый экземпляр жестко привязан к собственному PVC.
* **Иммутабельность шаблонов томов:** Секция `.spec.volumeClaimTemplates` неизменяема после создания StatefulSet. Любое изменение StorageClass или структуры томов требует миграции или пересоздания объекта StatefulSet с флагом `--cascade=orphan`.
* **Индекс 0 как уязвимая точка:** Во многих базовых конфигурациях под `*-0` назначается первичным узлом записи. При его выходе из строя требуется динамический выбор нового лидера на уровне приложения или оператора.

### Когда выбирать StatefulSet, а когда — Kubernetes Operator

StatefulSet является низкоуровневым строительным блоком Kubernetes. Для комплексных распределенных баз данных в Production предпочтительно использовать специализированные операторы:

| Критерий | StatefulSet («голый» манифест) | Kubernetes Operator |
| :--- | :--- | :--- |
| **Управление репликацией** | Требуются кастомные скрипты и ручная настройка | Автоматическое построение топологии и потоковой репликации |
| **Автоматический Failover** | Отсутствует (требуется ручное вмешательство или DCS) | Автоматический (интеграция с Patroni, etcd, Raft) |
| **Резервное копирование** | Внешние CronJob, ручные скрипты | Декларативное управление снимками, PITR, pgBackRest |
| **Мажорное обновление СУБД** | Остановка сервиса или сложный ручной перенос | Автоматизированное обновление без простоя (rolling upgrade) |
| **Область применения** | Простые сервисы, тестовые среды, базы с единственной репликой (single-instance / single-writer) | Критичные Production-кластеры баз данных и брокеров сообщений |

**Проверенные On-Premise операторы:**
* **PostgreSQL:** CloudNativePG, Zalando Postgres Operator (Patroni).
* **Apache Kafka:** Strimzi Kafka Operator.
* **RabbitMQ:** RabbitMQ Cluster Kubernetes Operator.
* **ClickHouse:** Altinity ClickHouse Operator.
* **Redis:** Redis Operator (OT-CONTAINER-KIT).

### См. также

* **[Обзор StatefulSet](./statefulset_overview.md)** — архитектура, основы и контроллер ревизий.
* **[Ключевые концепции](./statefulset_core_concepts.md)** — глубокий разбор сетевой идентичности, упорядоченности и хранилища.
* **[Практическое руководство](./statefulset_practical_guide.md)** — пошаговые манифесты, каскадное изменение PVC и сценарии масштабирования.
* **[Local PV vs CSI](./statefulset_local_pv_vs_csi.md)** — детальное сравнение дисковых подсистем для баз данных в Kubernetes.
* **[Exporter Sidecar](./statefulset_exporter_sidecar.md)** — организация сбора метрик СУБД через Prometheus Sidecar.
* **[Сравнение Deployment и StatefulSet](./statefulset_vs_deployment.md)** — матрица выбора контроллера для различных классов задач.