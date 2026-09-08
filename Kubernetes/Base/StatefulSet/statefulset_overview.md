# StatefulSet: Обзор

## Определения

**StatefulSet** — специализированный контроллер Kubernetes для управления приложениями с состоянием (stateful), которым требуется сохранение уникальности и «личности» каждого экземпляра. В отличие от **[Deployment](../Deployment/index.md)**, где поды (Pods) являются взаимозаменяемыми и эфемерными, StatefulSet гарантирует стабильную идентичность, сетевое имя и привязку к конкретному хранилищу для каждой реплики.

Данный контроллер необходим приложениям, которым требуются:
*   **Стабильные сетевые идентификаторы:** DNS-имена подов сохраняются при перезапусках, перепланировании на другие узлы и масштабировании.
*   **Стабильное хранилище (Persistent Storage):** каждый под привязан к конкретному диску через **[PersistentVolumeClaim (PVC)](../../Storage/pv_and_pvc.md)**, который «переезжает» вместе с подом.
*   **Упорядоченность операций:** строгий порядок развертывания, масштабирования (от 0 до N-1) и обновления.

Теоретические основы архитектур см. в разделе **[Stateful vs Stateless](../../../Concepts/stateful_vs_stateless.md)**.

## Предварительные требования

Для практической работы с StatefulSet необходимо наличие:

1.  **Рабочего кластера Kubernetes и kubectl** с корректно настроенным контекстом. Рекомендуемые стабильные релизы — v1.35–v1.37: часть описанных ниже возможностей (политика удержания PVC, `maxUnavailable`, стратегия `Recreate`) доступна только в новых версиях.
2.  **RBAC-прав** на ресурсы: `apps/statefulsets`, `apps/controllerrevisions`, `pods`, `persistentvolumeclaims`, а для отладки — `pods/log`, `events`. Типовое развертывание выполняется от имени ServiceAccount с правами на указанные объекты в целевом Namespace.
3.  **StorageClass с динамическим провижинингом** для работы `volumeClaimTemplates`. Без него создаваемые PVC останутся в статусе `Pending`. Подробнее: [StorageClass (классы хранения)](../../Storage/storageclass.md) и [PV и PVC](../../Storage/pv_and_pvc.md).
4.  **Headless Service**, созданного до (или вместе с) StatefulSet — его имя указывается в поле `serviceName`. Без него поды не получат персональные DNS-записи. Подробнее: [Тип Service — Headless](../../Networking/Service/service_type_headless.md).
5.  Понимания базовых объектов: [Pod](../Pod/pod_overview.md), Service, PVC, ConfigMap/Secret.

## Основные концепции

### Архитектурные компоненты

Для полноценного функционирования StatefulSet требует взаимодействия следующих объектов:

1.  **StatefulSet Controller:** Контроллер в `kube-controller-manager`, который управляет жизненным циклом подов на основе шаблона, поддерживает желаемое количество реплик и ведет историю ревизий (ControllerRevision).
2.  **Headless Service:** Сервис без IP-адреса кластера (`clusterIP: None`), обеспечивающий создание индивидуальных DNS-записей для каждого пода. Подробнее: **[Headless Service](../../Networking/Service/service_type_headless.md)**.
3.  **VolumeClaimTemplates:** Шаблон внутри спецификации StatefulSet, по которому контроллер автоматически создает уникальный PVC для каждого индекса пода.
4.  **PersistentVolume (PV):** Реальные дисковые ресурсы, которые подключаются к PVC.

### Ключевые поля спецификации (`.spec`)

| Поле | Назначение | Примечания |
| :--- | :--- | :--- |
| `serviceName` | Имя Headless Service, обеспечивающего DNS-записи подов | Обязательно для сетевой идентификации |
| `replicas` | Желаемое количество реплик | По умолчанию `1`; не задавайте вручную, если масштабирует HPA |
| `selector.matchLabels` | Селектор подов | Обязателен; **иммутабелен** после создания |
| `template` | Шаблон пода (синтаксис как в Deployment) | Изменение шаблона инициирует rollout |
| `volumeClaimTemplates` | Шаблон создания PVC для каждого пода | Иммутабелен; изменение размера — отдельная процедура |
| `podManagementPolicy` | Порядок создания/удаления: `OrderedReady` (по умолчанию) или `Parallel` | Влияет на скорость запуска и упорядоченность |
| `updateStrategy` | Стратегия обновления: `RollingUpdate` (по умолчанию), `OnDelete`, `Recreate` (Alpha v1.37) | Подробнее в подразделе ниже |
| `revisionHistoryLimit` | Сколько ревизий хранить для отката | По умолчанию `10`; `0` отключает откат |
| `minReadySeconds` | Минимальное время, которое под должен оставаться `Ready` перед переходом к следующей реплике | По умолчанию `0`; стабильно с v1.25 |
| `persistentVolumeClaimRetentionPolicy` | Политика удержания PVC при удалении и масштабировании | GA v1.32; по умолчанию `Retain`/`Retain` |
| `ordinals.start` | Начальный индекс нумерации подов | GA v1.31 |
| `template.spec.terminationGracePeriodSeconds` | Время на graceful-завершение пода (SIGTERM → SIGKILL) | Задается в шаблоне пода |

Детальный разбор механизмов (идентификация, доставка тома, порядок операций) — в документе **[Ключевые концепции](./statefulset_core_concepts.md)**.

### Сетевая идентификация и DNS

Каждый под в StatefulSet получает предсказуемое имя формата `<имя-StatefulSet>-<индекс>` (например, `web-0`, `web-1`). При наличии Headless Service каждый экземпляр становится доступен по полному доменному имени (FQDN):

`$(podname).$(service_name).$(namespace).svc.cluster.local`

**Пример:** под `db-0` в StatefulSet `postgres`, использующий сервис `pg-service` в неймспейсе `prod`, будет иметь DNS-имя `db-0.pg-service.prod.svc.cluster.local`.

Полезные метки, которые контроллер добавляет к каждому поду:

*   `statefulset.kubernetes.io/pod-name` — имя пода (`web-0`). Позволяет нацелить Service или NetworkPolicy на конкретный экземпляр (например, только на мастера).
*   `apps.kubernetes.io/pod-index` — порядковый индекс пода (`0`, `1`, ...). GA c v1.32. Удобна для фильтрации в мониторинге, при выборе подов в Service и при миграциях.

Приложениям, которым на старте нужно обнаружить друг друга до прохождения Readiness Probe (бутстрап кворума ZooKeeper, Cassandra, Elasticsearch), требуется `spec.publishNotReadyAddresses: true` в Headless Service — иначе они не попадут в DNS, пока не стали `Ready` (проблема «курицы и яйца»). Подробнее: [Headless Service — publishNotReadyAddresses](../../Networking/Service/service_type_headless.md).

### Стабильное хранилище через VolumeClaimTemplates

В отличие от Deployment, где все поды используют общий набор томов, StatefulSet создает **отдельный PVC для каждого индекса** автоматически:

*   **Именование:** `data-<имя-пода>` по шаблону `<имя-шаблона>-<pod-name>` (например, PVC `data-mysql-0` для пода `mysql-0`).
*   **Привязка (Sticky Storage):** после удаления пода-реплики новый под с тем же индексом монтирует тот же самый PVC. Данные «следуют» за идентификатором.
*   **Жизненный цикл:** по умолчанию PVC **не удаляются** ни при уменьшении реплик, ни при удалении StatefulSet. Это защита от случайной потери данных. Управляется политикой `persistentVolumeClaimRetentionPolicy` (`whenDeleted` / `whenScaled`, значения `Retain` или `Delete`, GA v1.32).

Пример: для пода `web-1` с шаблоном `data` контроллер создаст PVC `data-web-1` и смонтирует его в путь из `volumeClaimTemplates[0].mountPath`. Механизм выделения и связывания томов описан в [PV и PVC](../../Storage/pv_and_pvc.md).

### Стратегии обновления и управления

| Параметр | Варианты | Описание |
| :--- | :--- | :--- |
| **updateStrategy** | `RollingUpdate` | (По умолчанию). Удаляет и пересоздает поды один за другим в обратном порядке (от N-1 до 0), ожидая перехода каждой реплики в `Running` и `Ready` (плюс `minReadySeconds`, если задан). |
| | `OnDelete` | Контроллер не обновляет поды автоматически. Обновление происходит только после ручного удаления пода пользователем. Идеально для критических СУБД с плановым окном обслуживания. |
| | `Recreate` | (Alpha v1.37, feature gate `StatefulSetRecreateStrategy`). Удаляет **все** поды сразу и только после полного завершения создает новые. Есть даунтайм, но старые и новые ревизии никогда не работают одновременно. |
| **rollingUpdate.partition** | число | Обновляются только поды с индексом `>= partition`; поды с меньшим индексом остаются на старой ревизии и пересоздаются на ней же. Основной механизм канареечных (Canary) обновлений. |
| **rollingUpdate.maxUnavailable** | число или % | Позволяет обновлять несколько подов одновременно (Beta v1.35, включено по умолчанию). **Не может быть `0`**. Ускоряет обновление больших кластеров, но может нарушить строгий порядок готовности. |
| **podManagementPolicy** | `OrderedReady` | (По умолчанию). Поды запускаются/удаляются строго последовательно (0 → N-1 при создании, N-1 → 0 при удалении). Следующий под не создается, пока предыдущий не перейдет в состояние `Running` и `Ready`. |
| | `Parallel` | Поды создаются и удаляются параллельно, без ожидания готовности соседей. Полезно для ускорения запуска, когда упорядоченность не требуется. |

**Порядок жизненного цикла:**

1.  **Создание:** пода `0`, затем после его `Ready` — пода `1` и так далее (в режиме `OrderedReady`).
2.  **Обновление:** от максимального индекса к минимальному (N-1 → 0), по одному (или группами при `maxUnavailable > 1`). Историю ведет объект **ControllerRevision**.
3.  **Масштабирование вниз:** удаляются поды с наибольшими индексами (N-1 → 0).
4.  **Завершение:** на отправляемый `SIGTERM` приложение должно успеть сохранить состояние в течение `terminationGracePeriodSeconds`; затем пода завершает обработку `SIGKILL`.

### Минимальный манифест

Ниже — рабочий минимальный пример: Headless Service + StatefulSet из трех реплик Nginx с томом 1 GiB.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web-headless
spec:
  clusterIP: None          # Headless: нет виртуального IP
  selector:
    app: web
  ports:
  - port: 80
    name: http
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: web
spec:
  serviceName: "web-headless"   # совпадает с Headless Service
  replicas: 3
  selector:
    matchLabels:
      app: web                  # обязателен и иммутабелен
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
      - name: nginx
        image: nginx:1.27
        ports:
        - containerPort: 80
          name: http
        volumeMounts:
        - name: data
          mountPath: /usr/share/nginx/html
  volumeClaimTemplates:         # иммутабельный шаблон PVC
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 1Gi
```

Ключевые моменты:

*   Поле `serviceName` должно указывать на реально существующий Headless Service с теми же labels, иначе DNS-идентификация не работает.
*   Каждая реплика получит собственный PVC: `data-web-0`, `data-web-1`, `data-web-2`.
*   Без указания `storageClassName` будет использован StorageClass по умолчанию (должен поддерживать динамический провижининг).

Пошаговые сценарии (персистентность, MySQL, миграция, изменение размера тома) — в **[Практическом руководстве](./statefulset_practical_guide.md)**.

## Практические сценарии

### Когда выбирать StatefulSet

1.  **Распределенные СУБД:** PostgreSQL (в связке с Patroni/Stolon), MySQL (Galera), MongoDB (Replica Sets), Cassandra.
2.  **Брокеры сообщений и очереди:** Kafka, RabbitMQ, ActiveMQ (требуют стабильных ID для идентификации в кластере).
3.  **Системы консенсуса и координации:** ZooKeeper, etcd, Consul.
4.  **Специфические нагрузки:** Приложения, использующие механизмы кворума или требующие привязки лицензий к статичному имени хоста.

**Когда StatefulSet НЕ нужен:**

*   **Stateless-микросервисы** и веб-API: хватит Deployment + Service (см. [StatefulSet vs Deployment](./statefulset_vs_deployment.md)).
*   **Приложения с общим томом (RWX):** если все реплики читают одну директорию (CMS, файловое хранилище) и стабильные имена не важны — Deployment с одним PVC проще.
*   **Критичные большие СУБД:** операторы (CloudNativePG, Strimzi, MongoDB Operator) поверх StatefulSet автоматизируют бэкапы и failover; часто разумнее вынести базу за пределы кластера. Рекомендации — в разделе [PV и PVC — запуск баз данных](../../Storage/pv_and_pvc.md).

### Базовые операции управления

```bash
# Применение манифеста (создание или обновление)
kubectl apply -f statefulset.yaml
# → statefulset.apps/web created

# Просмотр списка, широкий вывод и детали
kubectl get statefulset
kubectl get statefulset web -o wide
# → NAME   READY   AGE
# → web    3/3     2m
kubectl describe statefulset web

# Наблюдение за последовательным созданием подов и PVC
kubectl get pods -w -l app=web
# → web-0   0/1     Pending             0          0s
# → web-0   0/1     ContainerCreating   0          0s
# → web-0   1/1     Running             0          5s
# → web-1   0/1     Pending             0          0s
kubectl get pvc
# → data-web-0   Bound   pvc-xxx   1Gi   RWO

# Получение FQDN и роли реплик (метки)
kubectl get pods -l app=web -L apps.kubernetes.io/pod-index
```

Проверка прогресса и валидация (`kubectl rollout status`) разобрана в подразделе обновления ниже.

### Обновление и откат версии приложения

```bash
# Обновление образа (родственная команда для patch)
kubectl set image statefulset/web web=nginx:1.27
# → statefulset.apps/web image updated

# Отслеживание прогресса вращения (обновление идет от N-1 к 0)
kubectl rollout status statefulset/web --timeout=180s
# → waiting for statefulset rolling update to complete 0 pods at revision 2...
# → statefulset rolling update complete

# История ревизий
kubectl rollout history statefulset/web
# → statefulset.apps/web
# → REVISION  CHANGE-CAUSE
# → 1         <none>
# → 2         kubectl set image statefulset/web web=nginx:1.27

# Откат к предыдущей ревизии
kubectl rollout undo statefulset/web
# → statefulset.apps/web rolled back

# Откат к конкретной ревизии
kubectl rollout undo statefulset/web --to-revision=1
# → statefulset.apps/web rolled back

# Список ControllerRevision'ов (объекты истории)
kubectl get controllerrevisions
```

**Меры предосторожности при обновлении:**

*   Используйте **Startup Probe** для приложений с длительной инициализацией (WAL replay), иначе Liveness-проба перезапустит под, а `RollingUpdate` застрянет на недоступной ревизии.
*   Следите за `revisionHistoryLimit` (по умолчанию 10): при слишком частых деплоях старые ревизии вытесняются и откат «глубоко в историю» станет невозможен.

**Канареечное обновление через `partition`:** сначала зафиксируйте обновление границей, раскатайте образ и проверьте единственный обновленный под, затем снимите границу:

```bash
# Заморозить обновление: применятся только индексы >= 2
kubectl patch statefulset web -p '{"spec":{"updateStrategy":{"type":"RollingUpdate","rollingUpdate":{"partition":2}}}}'
# → statefulset.apps/web patched

kubectl set image statefulset/web web=nginx:1.28
# → обновится только web-2

# Проверка образов по репликам
kubectl get pods -l app=web -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[0].image}{"\n"}{end}'

# Снять ограничение — продолжить обновление всех
kubectl patch statefulset web -p '{"spec":{"updateStrategy":{"type":"RollingUpdate","rollingUpdate":{"partition":0}}}}'
```

Подробнее о стратегии и известных проблемах: **[Ключевые концепции](./statefulset_core_concepts.md)** и [Partition в Rolling Update StatefulSet](../../../CI-CD/Deployment_Strategies/rolling_update.md).

### Масштабирование

```bash
# Увеличение/уменьшение количества реплик
kubectl scale statefulset web --replicas=5
# → statefulset.apps/web scaled

# Проверка актуального числа готовых реплик
kubectl get statefulset web -o jsonpath='{.status.readyReplicas}/{.spec.replicas}{"\n"}'
```

Нюансы:

*   При масштабировании вниз удаляются реплики с наибольшими индексами; их PVC при политике по умолчанию `Retain` **сохраняются** (данные можно вернуть при подъеме).
*   Для автоматической очистки дисков ненужных реплик задайте `persistentVolumeClaimRetentionPolicy.whenScaled: Delete` (например, для Elasticsearch).
*   Если масштабирование управляется **HPA**, не задавайте `replicas` вручную в манифесте: повторный `kubectl apply -f statefulset.yaml` с фиксированным `replicas` перезапишет масштабирование, сделанное контроллером.

### Плановая замена узла (Drain)

Плановое обслуживание узла (обновление ядра, замена оборудования) выполняется командой `kubectl drain`:

```bash
kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data --timeout=5m
```

Поведение StatefulSet при drain:

1.  Поды выселяются через Eviction API с уважением к **PodDisruptionBudget** (при `minAvailable` из 3 реплик 2, drain заблокируется и будет ждать).
2.  Контроллер пересоздает под на другом доступном узле с **тем же PVC**.
3.  Для RWO-томов (блочные диски) новый под ждет, пока старый узел выполнит detach — задержка может достигать нескольких минут (в облачных средах 2–5 минут, локально меньше).
4.  После работ узел возвращается через `kubectl uncordon node-1`.

Детали команд, флагов и ограничений: **[Обслуживание узлов (Cordon/Drain)](../../Operations/node_maintenance.md)**, **[PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md)**.

### Отказ узла (неплановый)

При внезапном отказе узла Kubernetes **не переносит под StatefulSet автоматически** на другой узел. Это осознанная защита от разделения мозга (Split-brain): под `db-0` не должен запуститься в двух местах одновременно и писать в один диск.

**Порядок действий для SRE:**

```bash
# 1. Диагностика: узел NotReady, под застрял в Terminating/Unknown
kubectl get nodes
kubectl get pod web-0 -o wide

# 2. Если узел уже восстановился — под вернется сам, PVC не пострадал.
#    Проверьте статус и события.
kubectl get events --field-selector involvedObject.name=web-0

# 3. Если узел не вернется в кластер — безопасно подтвердите его недоступность
#    (Non-Graceful Node Shutdown, GA v1.28).
kubectl patch node node-1 -p '{"metadata":{"labels":{"node.kubernetes.io/out-of-service":"nodeshutdown"}}}'
# → Контроллер безопасно отмонтирует тома и пересоздаст под на другом узле
```

**Принудительное удаление — крайняя мера:**

```bash
# НЕ использовать без понимания последствий: может привести к Multi-Attach
# и повреждению данных, если старый узел все еще жив.
kubectl delete pod web-0 --force --grace-period=0
```

`--force` допустим только когда узел гарантированно не вернется и отмонтирование подтверждено. Подробнее о безопасном force-delete и разборе `Terminating`: **[Практическое руководство](./statefulset_practical_guide.md)**, **[Высокая доступность](../high_availability.md)**.

### Очистка и удаление

```bash
# Удаление StatefulSet: поды удаляются, PVC по умолчанию СОХРАНЯЮТСЯ.
kubectl delete statefulset web
# → statefulset.apps "web" deleted

# Удаление «осиротевшего» контроллера с сохранением работающих подов:
kubectl delete statefulset web --cascade=orphan

# Удаление отдельного пода: контроллер пересоздаст его с тем же именем и PVC
kubectl delete pod web-0

# Удаление PVC (данные уничтожаются вместе с PV при reclaimPolicy: Delete)
kubectl delete pvc data-web-0
```

Рекомендации для Production:

*   Перед удалением StatefulSet всегда проверяйте политику `persistentVolumeClaimRetentionPolicy.whenDeleted` (по умолчанию `Retain` — диски останутся).
*   Для полной очистки окружения удаляйте в порядке «StatefulSet → PVC» и, при необходимости, снапшоты и PV.
*   При GitOps-подходе удаление выполняется через CR по намерению репозитория, а не ручными командами.

### Резервное копирование и аварийное восстановление

Состояние StatefulSet-приложения лежит в PVC, поэтому резервное копирование должно сочетать **данные и метаданные**:

*   **Метаданные кластера:** бэкап etcd или декларативное состояние в Git (GitOps). StatefulSet, PVC, CDR и политики восстанавливаются из кода.
*   **Данные PVC:** CSI-снапшоты (`VolumeSnapshot`), логические дампы (`pg_dump`, `mysqldump`) или Velero/Kasten с хуками консистентности (pre/post-backup).
*   **Кросс-кластерная миграция:** поле `spec.ordinals.start` позволяет переносить тяжелые БД частями — сначала реплики 3–5, затем 0–2, чтобы не поднимать весь кластер разом.

Полная методология и сценарии: **[Резервное копирование и аварийное восстановление в Kubernetes](../../Operations/backup-strategies.md)** и **[Внутренние механизмы и снапшоты PV/PVC](../../Storage/pv_and_pvc.md)**.

### Мониторинг и алертинг

Для контроля доступности и хода обновлений через `kube-state-metrics` отслеживайте количество готовых реплик, застрявшие обновления (`observed_generation` vs `updated_replicas`) и рост числа ControllerRevision. Набор готовых Prometheus-алертов и ServiceMonitor — в **[Лучших практиках](./statefulset_best_practices.md)**.

### Диагностика и устранение неполадок

| Симптом | Вероятная причина | Первичная проверка и решение |
| :--- | :--- | :--- |
| Под в `Pending` | PVC в `Pending` (нет StorageClass/свободного PV), не выполнены требования планировщика, уперлись в анти-аффинити | `kubectl get pvc` → `kubectl describe pvc <имя>` → `describe pod`; проверить StorageClass. Подробнее: [Проблемы с PVC](../../Troubleshooting/Common_Errors/CreateContainerConfigError/pvc_issues.md), [PV и PVC](../../Storage/pv_and_pvc.md) |
| Под в `ContainerCreating` | Долгий attach/detach RWO-тома, Multi-Attach (диск занят старым подом), сбой CSI | `kubectl describe pod <имя>` (события); убедиться, что старый под полностью удален |
| `CrashLoopBackOff` | Ошибка приложения, неверные права на том (`fsGroup`), некорректные пробы | `kubectl logs <под>`; проверить пробы: [Пробы (Probes)](../probes.md) |
| RollingUpdate застрял | Обновленный под никогда не становится `Ready` (плохой образ/конфиг) | Вернуть шаблон (`rollout undo`) **и вручную удалить** поды с плохой ревизией (`kubectl delete pod <имя>`). Известный баг #67250 |
| Под вечно в `Terminating` | Узел недоступен, том не отмонтируется | Пометка узла `out-of-service` (v1.28+) с последующим безопасным пересозданием; force-delete — только как крайняя мера (раздел «Отказ узла» выше) |
| Нет DNS-имени у пода | Headless Service не создан, неверный `serviceName`, не совпадают labels, поды не публикуются до Ready | `nslookup`/`dig` из debug-пода; проверить `publishNotReadyAddresses` для бутстрапа. Подробнее: [Headless Service](../../Networking/Service/service_type_headless.md) |
| PVC не удаляется после scale-down | Политика по умолчанию `Retain` у `whenScaled` | Это безопасное поведение; для автоочистки задать `whenScaled: Delete` |
| Ошибки `CreateContainerConfigError` | Отсутствует ConfigMap/Secret, не хватает RBAC | [ConfigMap](../../Troubleshooting/Common_Errors/CreateContainerConfigError/configmap_issues.md), [Secret](../../Troubleshooting/Common_Errors/CreateContainerConfigError/secret_issues.md), [RBAC](../../Troubleshooting/Common_Errors/CreateContainerConfigError/rbac_issues.md) |
| `kubectl apply` отклоняет манифест | Изменены иммутабельные поля: `selector`, `volumeClaimTemplates` | Пересоздать объект после переноса данных или выполнить процедуру изменения размера тома (см. [Практическое руководство](./statefulset_practical_guide.md)) |

## Дополнительная информация

### Возможности и изменения по версиям

*   **`minReadySeconds`** (стабильно v1.25): задержка между сменой подов при обновлении, позволяющая отсекать «разогревающиеся» реплики.
*   **Non-Graceful Node Shutdown** (GA v1.28): безопасное подтверждение недоступности узла через метку `node.kubernetes.io/out-of-service` — решает проблему зависших томов RWO.
*   **Произвольный старт индексов (`ordinals`)** (GA v1.31): возможность начать нумерацию подов не с 0, а с другого числа — для миграции между кластерами и частичного переноса тяжелых БД.
*   **Очистка PVC (`persistentVolumeClaimRetentionPolicy`)** (GA v1.32): автоматическое удаление дисков при удалении StatefulSet (`whenDeleted`) или уменьшении реплик (`whenScaled`). По умолчанию `Retain` (сохранять).
*   **Метка индекса пода** `apps.kubernetes.io/pod-index` (GA v1.32): автоматически добавляется к каждому поду; удобна для фильтрации конкретных экземпляров в Service, мониторинге или логах.
*   **Параллельное обновление (`rollingUpdate.maxUnavailable`)** (Beta v1.35, включено по умолчанию): позволяет RollingUpdate обновлять несколько подов одновременно, сокращая время простоя при больших масштабах. Не путать с `maxSurge` из Deployment — лишние экземпляры создавать нельзя из-за привязки к дискам.
*   **Стратегия обновления `Recreate`** (Alpha v1.37, за feature gate `StatefulSetRecreateStrategy`): одновременное удаление всех подов с последующим пересозданием — для приложений, несовместимых с двумя параллельными ревизиями.

### Ограничения и особенности

*   **Защита от повреждения данных:** При падении узла Kubernetes не переносит поды StatefulSet автоматически. Это сделано для исключения ситуации "Split-brain", когда два пода могут пытаться писать на один диск одновременно.
*   **Ручное вмешательство:** В случае отказа узла может потребоваться удаление пода вручную или использование механизма **Non-Graceful Node Shutdown** для принудительного переноса.
*   **Headless Service:** Создание StatefulSet без указания `serviceName` и наличия соответствующего Headless Service лишает его преимуществ стабильной DNS-идентификации.
*   **Иммутабельные поля:** `selector.matchLabels` и `volumeClaimTemplates` нельзя изменить после создания. Изменение размера тома выполняется каскадно (патч PVC + пересоздание контроллера) — см. [Практическое руководство](./statefulset_practical_guide.md).
*   **`maxUnavailable > 1`** ускоряет обновление, но нарушает строгую упорядоченность готовности реплик — не подходит для систем с требованием строгой очередности (синхронная репликация, каскадный bootstrap).
*   **Координатор в индексе 0:** в большинстве распределенных систем роль лидера/координатора привязана к поду с индексом 0. При масштабировании вниз он удаляется последним, но после полного останова кластера восстановление кворума начинается именно с него.
*   **HPA и `replicas`:** если масштабированием управляет HorizontalPodAutoscaler, не указывайте `replicas` в манифестах — `kubectl apply` перезапишет текущее масштабирование.
*   **ControllerRevision:** объекты истории служат только для отслеживания и отката. Не редактируйте их вручную и не используйте как бэкап; `revisionHistoryLimit: 0` полностью отключает возможность отката.
*   **StorageClass:** для `volumeClaimTemplates` требуется динамический провижининг; для больших OLTP-нагрузок предпочтительны локальные диски и `volumeBindingMode: WaitForFirstConsumer` (см. [Лучшие практики](./statefulset_best_practices.md)).

### См. также

*   **[Ключевые концепции](./statefulset_core_concepts.md)** — глубокий разбор механизмов идентификации, хранения и стратегий обновления.
*   **[StatefulSet vs Deployment](./statefulset_vs_deployment.md)** — подробная таблица сравнения и критерии выбора контроллера.
*   **[Лучшие практики](./statefulset_best_practices.md)** — рекомендации по настройке HA, безопасности и мониторинга.
*   **[Практическое руководство](./statefulset_practical_guide.md)** — пошаговое развертывание с примерами YAML и устранением неполадок.
*   **[Local PV vs CSI](./statefulset_local_pv_vs_csi.md)** — выбор хранилища для БД.
*   **[Exporter Sidecar](./statefulset_exporter_sidecar.md)** — мониторинг БД через Prometheus.

### Чек-лист понимания StatefulSet

Перед работой с StatefulSet в production убедитесь, что вы можете:

1.  **Объяснить разницу** Deployment vs StatefulSet конкретными примерами
2.  **Нарисовать архитектуру**: StatefulSet + Headless Service + PVC + StorageClass
3.  **Описать жизненный цикл** пода: создание → Ready → обновление → завершение
4.  **Объяснить, почему** StatefulSet не делает automatic failover (защита от Split-brain)
5.  **Назвать 3 стратегии** обновления и их trade-offs (RollingUpdate, OnDelete, Recreate)
6.  **Описать процедуру** безопасного обновления PostgreSQL
7.  **Объяснить роль** PDB и anti-affinity в HA
8.  **Настроить Canary-обновление** через `partition`
9.  **Описать процедуру** восстановления после падения узла (taint `out-of-service`)
10. **Назвать отличия** `maxSurge` (Deployment) и `maxUnavailable` (StatefulSet)
11. **Объяснить, когда** нужен Operator, а когда достаточно голого StatefulSet
12. **Описать, как** интегрировать StatefulSet с GitOps (ArgoCD/Flux) без потери данных