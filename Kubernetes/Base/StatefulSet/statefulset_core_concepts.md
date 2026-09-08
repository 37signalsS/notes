# StatefulSet: Ключевые концепции

## Определения

**StatefulSet** — специализированный контроллер Kubernetes для управления приложениями с состоянием (stateful), которым требуются стабильные идентификаторы, сохранение данных между перезапусками и строгий порядок выполнения операций. В отличие от **[Deployment](../Deployment/index.md)**, где поды (Pods) являются взаимозаменяемыми и эфемерными, StatefulSet гарантирует уникальность и «личность» каждого экземпляра.

Данный контроллер является стандартом для развертывания распределенных систем:
*   **Базы данных:** PostgreSQL, MySQL, MongoDB, Cassandra.
*   **Брокеры сообщений:** Kafka, RabbitMQ, Pulsar.
*   **Кластерные хранилища:** Ceph, Rook, MinIO.
*   **Системы координации:** ZooKeeper, etcd, Consul.

Базовые концепции архитектур описаны в разделе **[Stateful vs Stateless](../../../Concepts/stateful_vs_stateless.md)**.

Документ является «глубоким погружением» в механизмы работы контроллера. Операционный справочник (развертывание, обновление, обслуживание узлов, бэкапы) — в **[Обзоре](./statefulset_overview.md)** и **[Практическом руководстве](./statefulset_practical_guide.md)**.

## Предварительные требования

Для воспроизведения практических сценариев из этого документа необходимо:

1.  **Рабочий кластер Kubernetes и kubectl** с корректно настроенным контекстом. Часть описываемых механизмов (`persistentVolumeClaimRetentionPolicy`, `ordinals`, метка `apps.kubernetes.io/pod-index`, `maxUnavailable`) доступна только в современных версиях — рекомендуется v1.35+.
2.  **RBAC-права** на ресурсы: `apps/statefulsets`, `apps/controllerrevisions`, `pods`, `persistentvolumeclaims`, а для отладки — `pods/log` и `events`.
3.  **StorageClass с динамическим провижинингом** для работы `volumeClaimTemplates`. Без него создаваемые PVC останутся в статусе `Pending`. Подробнее: **[StorageClass](../../Storage/storageclass.md)** и **[PV и PVC](../../Storage/pv_and_pvc.md)**.
4.  **Headless Service**, созданный до (или вместе с) StatefulSet, — его имя указывается в поле `serviceName`. Без него поды не получат персональные DNS-записи. Подробнее: **[Тип Service — Headless](../../Networking/Service/service_type_headless.md)**.
5.  Понимание базовых объектов: **[Pod](../Pod/pod_overview.md)**, Service, PVC, ConfigMap/Secret.

## Основные концепции

### Механизм стабильной сетевой идентификации

StatefulSet обеспечивает каждому поду уникальное DNS-имя, которое сохраняется даже при перемещении пода между узлами. Это реализуется через связку контроллера и **Headless Service**.

**Алгоритм формирования идентификаторов:**
1.  **Имя пода:** Фиксируется как `$(statefulset-name)-$(index)`. Индексы начинаются с `0` (если не настроены `ordinals`).
2.  **Hostname:** Внутри контейнера `hostname` совпадает с именем пода. Контроллер явно выставляет у каждого создаваемого пода `spec.hostname = имя пода` и `spec.subdomain = значение serviceName` — именно поэтому DNS-имя «складывается» из имени пода и имени сервиса.
3.  **DNS-субдомен:** StatefulSet требует наличия Headless Service (с полем `clusterIP: None`). Имя этого сервиса указывается в поле `serviceName` спецификации StatefulSet.
4.  **FQDN пода:** Формируется как `$(pod-name).$(service-name).$(namespace).svc.cluster.local`.

**Преимущество:** Приложения могут обращаться к конкретным узлам кластера (например, `db-0` для записи, `db-1` для чтения), не полагаясь на динамические IP-адреса. При пересоздании пода на другом узле IP меняется, но FQDN и hostname остаются неизменными.

**Типы DNS-записей, создаваемых Headless Service:**
*   **A/AAAA-запись** `$(pod-name).$(service-name).$(namespace).svc.cluster.local` → текущий IP пода. Обновляется при каждом пересоздании пода.
*   **SRV-запись** `_$(port-name)._$(protocol).$(service-name).$(namespace).svc.cluster.local` → список A-записей подов. Создается только для **именованных портов** сервиса и активно используется системами координации (etcd, ZooKeeper, Cassandra) и gRPC-обнаружением.

**Особенность публикации:** по умолчанию Headless Service публикует в DNS только поды в состоянии `Ready`. Приложениям, которым нужно обнаружить друг друга **до** прохождения Readiness Probe (бутстрап кворума ZooKeeper, Cassandra, Elasticsearch), требуется `spec.publishNotReadyAddresses: true` — иначе возникает проблема «курицы и яйца»: под не становится Ready, пока не найдет соседей, но соседи не публикуются в DNS до Ready.

**Полезные метки пода:**
*   `statefulset.kubernetes.io/pod-name` — имя пода (например, `web-0`). Позволяет направить Service или NetworkPolicy только на конкретный экземпляр.
*   `apps.kubernetes.io/pod-index` — порядковый индекс пода (`0`, `1`, ...). GA c v1.32. Удобна для фильтрации в мониторинге, в Service и при миграциях.

### Управление персистентным хранилищем через шаблоны

В отличие от Deployment, где все поды используют один и тот же шаблон тома, StatefulSet использует **VolumeClaimTemplates**.

**Как это работает:**
*   **Автоматическая генерация:** Для каждого индекса пода контроллер создает индивидуальный объект **[PersistentVolumeClaim (PVC)](../../Storage/pv_and_pvc.md)**.
*   **Именование PVC:** `<имя-шаблона>-<имя-пода>` (например, `data-mysql-0`). Полное правило — `<имя-шаблона>-<имя-StatefulSet>-<ordinal>`.
*   **Порядок создания:** PVC (и связанный с ним PV через динамический провижининг) создается **до** пода. При масштабировании вверх контроллер не создаст под, пока его PVC не перейдет в статус `Bound`. Это гарантирует, что под «стартует» уже с готовым диском.
*   **Приоритет:** если шаблон тома имеет то же имя, что и том, объявленный в `spec.template`, приоритет у claim из `volumeClaimTemplates`.
*   **Привязка (Sticky Storage):** Если под `mysql-0` удаляется и создается заново, он автоматически подключается к тому же самому PVC `data-mysql-0`. Это гарантирует, что данные «следуют» за идентификатором пода.
*   **Жизненный цикл:** По умолчанию PVC **не удаляются** при удалении StatefulSet или уменьшении количества реплик. Это механизм защиты от случайной потери данных. Управляется политикой `persistentVolumeClaimRetentionPolicy`.

**Нюансы эксплуатации:**
*   Для `volumeClaimTemplates` типичен режим доступа `ReadWriteOnce` (RWO) — диск монтируется к одному узлу, что исключает конфликт Multi-Attach внутри кластера.
*   Для корректной записи на том при запуске от не привилегированного пользователя задавайте `securityContext.fsGroup` — kubelet автоматически установит владельца тома в указанный GID.
*   Шаблон `volumeClaimTemplates` иммутабелен: изменить его уже после создания нельзя. Увеличение размера диска выполняется по каскадной процедуре (патч PVC + пересоздание контроллера), подробно описанной в **[Практическом руководстве](./statefulset_practical_guide.md)**.

### Новые возможности управления индексами (v1.31+)

*   **Произвольный старт индексов (`.spec.ordinals.start`):** Стала GA в v1.31. Позволяет задать начальный номер (например, для миграции между кластерами). При `ordinals.start: 3` и `replicas: 3` поды получат имена `web-3`, `web-4`, `web-5` (соответственно сдвинутся и их FQDN).
*   **Стабильная метка индекса:** Метка `apps.kubernetes.io/pod-index` стала GA в v1.32. Она позволяет Service или мониторингу (Prometheus) легко идентифицировать роль пода на основе его порядкового номера. Включена по умолчанию (feature gate `PodIndexLabel`); отключить можно только на серверной эмуляции версии v1.31.

### Политика удержания PVC (GA v1.32)

Поле `.spec.persistentVolumeClaimRetentionPolicy` позволяет гибко настроить автоматическую очистку хранилища:

*   **`whenDeleted`:** Определяет судьбу PVC при полном удалении StatefulSet (`Retain` или `Delete`).
*   **`whenScaled`:** Определяет, удалять ли PVC при уменьшении реплик (Scale down). Это критично для временных шардов, данные которых не нужны после масштабирования вниз.

**По умолчанию** обе политики равны `Retain` (сохранять). Значения:
*   `Retain` — PVC (и PV) переживают операцию; при последующем увеличении реплик под «подхватит» сохраненный диск, что удобно для временного scale-down БД.
*   `Delete` — PVC удаляется автоматически в момент соответствующей операции.

**Важные ограничения политики:**
*   Политика влияет **только** на PVC, созданные через `volumeClaimTemplates`. На PVC, созданные вручную и указанные в `spec.template.volumes`, она не распространяется.
*   `whenScaled` срабатывает при масштабировании реплик, но **не** при ручном удалении отдельного пода (`kubectl delete pod web-2`) — в этом случае под пересоздается с тем же PVC.
*   При `Delete` удаляется и сам PVC, и PV (в зависимости от `reclaimPolicy` StorageClass возможно удаление и реальных данных на диске — для critical данных комбинируйте со снапшотами).

## Жизненный цикл и стратегии обновления

### Порядок управления подами (`podManagementPolicy`)

1.  **OrderedReady (по умолчанию):**
    *   Создание: 0 → 1 → 2. Следующий под не создается, пока предыдущий не станет `Ready`.
    *   Удаление: 2 → 1 → 0. Гарантирует безопасное завершение транзакций в кластере.
2.  **Parallel:** Все поды создаются/удаляются одновременно. Используется, когда порядок не важен (например, Stateless приложения, которым нужны стабильные имена).

**Две строгие гарантии контроллера** (вне зависимости от политики соблюдаются для операций масштабирования):
*   Перед применением операции масштабирования к поду все его **предшественники** (predecessors) должны быть `Running` и `Ready` (а при заданном `minReadySeconds` — «available», т.е. Ready в течение указанного времени).
*   Перед завершением пода все его **преемники** (successors) должны быть полностью остановлены.

Эти гарантии важны при работе с кворумными системами: реплика не может быть остановлена, пока ее преемник еще не завершился, и не может быть создана/изменена, пока ее предшественник не стал полностью готов.

### Стратегии обновления (`updateStrategy`)

#### RollingUpdate (по умолчанию)

Обновление идет от максимального индекса к минимальному (N-1 → 0). Контроллер ждет, пока обновленный под перейдет в `Running` и `Ready`, перед обновлением его предшественника (при `minReadySeconds` — дополнительно ждет указанное время после готовности).

*   **Partition (Разделение):** Если указано `partition: 2` в StatefulSet с 5 репликами, обновятся только поды 4, 3 и 2. Поды 0 и 1 останутся на старой версии. Это базовый механизм для Canary-деплоев.
    *   Поды с индексом `< partition` не только не обновляются, но и при случайном удалении **пересоздаются на старой ревизии**.
    *   Если `partition >= replicas`, обновление шаблона **не применяется ни к одному поду** (шаблон «замораживается»). Снижая `partition` до 0, мы «размораживаем» полный rollout.
*   **`maxUnavailable`:** Позволяет обновлять несколько подов одновременно.
    *   Этикетка версий: поле стало Beta в v1.35. **Важная оговорка о свежести:** в v1.35.0 фича поставлялась включенной по умолчанию, однако из-за бага [kubernetes/kubernetes#137409](https://github.com/kubernetes/kubernetes/issues/137409) (rollout-deadlock при `podManagementPolicy: Parallel`, когда недоступные поды на устаревшей ревизии учитывались в лимит) feature gate `MaxUnavailableStatefulSet` был **отключен по умолчанию** в v1.35.x и v1.36.x; исправление попало в v1.37. Поэтому фактическое поведение зависит от версии кластера и установки гейта — проверяйте командой ниже.
    *   Значение — число или процент от желаемого числа подов (процент округляется вверх), **не может быть `0`**, по умолчанию `1` (т.е. обновление по одному поду).
    *   **Важно:** ускоряя rollout, параметр нарушает строгую упорядоченность готовности реплик — готовность может наступать не по порядку, что неприемлемо для нагрузок с требованием строгой очередности (например, синхронная репликация).
    *   **Кворумная математика:** для систем на базе кворума безопасный максимум недоступных реплик равен `ceil(N/2) - 1`. Для классических 3 реплик (кворум = 2) безопасное значение — `1`, то есть выигрыша нет; реальный эффект появляется только на больших числах реплик (N=5 → безопасно `2`, N=9 → `4`).
    *   Проверка гейта на кластере:
        ```bash
        kubectl get pod -n kube-system kube-controller-manager-$(hostname) -o jsonpath='{.spec.containers[0].command}{"\n"}'
        # → наличие --feature-gates=MaxUnavailableStatefulSet=true включает фичу;
        #   отсутствие флага при v1.35.x/v1.36.x означает отключено (default)
        ```
*   **OnDelete:** Контроллер обновит под только после того, как он будет удален вручную. Идеально для критических СУБД, где время обслуживания (maintenance window) должно контролироваться человеком.

#### Recreate (Alpha v1.37)

За feature gate `StatefulSetRecreateStrategy`. Стратегия удаляет **все** поды сразу и только после полного завершения создает новые в соответствии с `podManagementPolicy`. Старые и новые ревизии никогда не работают одновременно, но есть полный даунтайм — применимо для приложений, несовместимых с одновременным сосуществованием двух ревизий.

### ControllerRevision и откат

Каждый раз, когда изменяется `spec.template` пода, контроллер создает новый объект **ControllerRevision**:
1.  Создается новый ControllerRevision — снапшот шаблона пода и метаданных.
2.  Назначается инкрементальный номер ревизии.
3.  Обновляются поля статуса StatefulSet: `currentRevision` (ревизия, на которой работают поды) и `updateRevision` (целевая ревизия).

Отслеживание ревизий через kubectl:
```bash
# История ревизий (CHANGE-CAUSE заполняется, если образ меняли через set image)
kubectl rollout history statefulset/web

# Текущая и целевая ревизии
kubectl get statefulset web -o jsonpath='{.status.currentRevision}{"\t"}{.status.updateRevision}{"\n"}'

# Список объектов истории
kubectl get controllerrevisions

# Откат к предыдущей / к конкретной ревизии
kubectl rollout undo statefulset/web
kubectl rollout undo statefulset/web --to-revision=1
```

**Нюансы:**
*   Количество хранимых ревизий ограничено `revisionHistoryLimit` (по умолчанию `10`). При слишком частых деплоях старые ревизии вытесняются, и откат «глубоко в историю» становится невозможен.
*   `revisionHistoryLimit: 0` полностью отключает историю, а значит и возможность отката.
*   Объекты ControllerRevision — служебные; не редактируйте их вручную и не используйте как бэкап.

### Завершение работы (Graceful Termination)

При удалении пода StatefulSet отправляет `SIGTERM`.
1.  Если задан **preStop-хук**, он выполняется первым (например, для graceful-передачи роли лидера или закрытия соединений).
2.  Kubernetes ожидает `terminationGracePeriodSeconds` (по умолчанию 30с).
3.  Приложение должно успеть завершить открытые соединения, сбросить буферы на диск и корректно выйти из кворума кластера.
4.  Если время истекло, отправляется `SIGKILL`.

**Порядок в связке с удалением:** в режиме `OrderedReady` преемник полностью завершается раньше предшественника — успешное завершение пода `web-1` является предусловием для удаления `web-0`. Для БД с большим объемом данных задавайте `terminationGracePeriodSeconds` в диапазоне 120–300с (сброс WAL, передача роли лидера).

## Обработка сбоев и надежность

### Защита от повреждения данных (Split-brain)

StatefulSet реализует семантику «at most one» (максимум один экземпляр с данным именем). Если узел с подом `db-0` стал `NotReady`, контроллер **не пересоздаст** под на другом узле автоматически.
*   **Почему:** Старый узел может быть жив (проблема сети), и если запустить `db-0` в другом месте, два процесса могут одновременно писать в один и тот же сетевой диск (Corruption).
*   **Механизм:** контроллер не начинает пересоздание, пока старый объект пода (застрявший в `Terminating`) не будет удален из API. Пока объем тома привязан к недоступному узлу, его нельзя смонтировать в другом месте — повторный `Multi-Attach` заблокирован.

**Правильный порядок восстановления SRE:**
1.  **Диагностика:** `kubectl get nodes`, `kubectl get pod db-0 -o wide`, события пода.
2.  **Узел вернулся** — под завершится сам, PVC не пострадал, контроллер пересоздаст под.
3.  **Узел не вернется** — используйте механизм **Non-Graceful Node Shutdown** (GA v1.28): подтвердите, что узел действительно выключен (не перезагружается), и добавьте taint `node.kubernetes.io/out-of-service=nodeshutdown:NoExecute`:
    ```bash
    kubectl taint nodes node-1 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
    # → узел помечен как выведенный из строя; поды принудительно удаляются,
    #   тома немедленно отсоединяются, контроллер пересоздает под на живом узле
    ```
    После восстановления узла taint снимается явно: `kubectl taint nodes node-1 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute-`.
    *   Примечание: часть операционных скриптов отмечает узел эквивалентной меткой `node.kubernetes.io/out-of-service`, однако документированный способ — именно taint. Полный SRE-ранбук: **[Обзор — Отказ узла](./statefulset_overview.md)** и **[Недоступность узла: Taints и выселение](../../Troubleshooting/Common_Errors/NodeUnavailability/taints_and_eviction.md)**.
4.  **Крайняя мера** — принудительное удаление пода `kubectl delete pod db-0 --force --grace-period=0`. Допустимо **только** если узел гарантированно не вернется в кластер и отмонтирование подтверждено, иначе возможен Multi-Attach и повреждение данных (старый узел может все еще писать в диск).

**PDB и добровольные прерывания:** при плановых операциях (обновление узлов, `kubectl drain`) выселение подов StatefulSet уважает **PodDisruptionBudget** (`minAvailable` / `maxUnavailable`). Это не распространяется на вынужденные прерывания (падение узла, taint `out-of-service`) — PDB не блокирует такие случаи. Подробнее: **[PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md)**.

## Практические сценарии

Для большинства сценариев используется единый демонстрационный стенд: Headless Service + StatefulSet из трех реплик Nginx с томом 1 GiB.

**Подготовка стенда:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web
spec:
  clusterIP: None
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
  serviceName: "web"
  replicas: 3
  selector:
    matchLabels:
      app: web
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
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 1Gi
```

```bash
kubectl apply -f statefulset.yaml
# → service/web created
# → statefulset.apps/web created
```

### Наблюдение за механизмом Sticky Storage

```bash
# 1. Проверка созданных PVC
kubectl get pvc
# → data-web-0   Bound   pvc-xxx   1Gi   RWO
# → data-web-1   Bound   pvc-yyy   1Gi   RWO
# → data-web-2   Bound   pvc-zzz   1Gi   RWO

# 2. Запись данных и удаление пода
kubectl exec web-0 -- sh -c 'echo "identity-marker" > /usr/share/nginx/html/index.html'
kubectl delete pod web-0
# → pod "web-0" deleted

# 3. Новый под web-0 примонтирует прежний PVC data-web-0
kubectl describe pod web-0 | grep -A2 -i volumes
# → Volumes:
# →   data:
# →     Type:       PersistentVolumeClaim
# →     ClaimName:  data-web-0

# 4. Данные сохранились
kubectl exec web-0 -- cat /usr/share/nginx/html/index.html
# → identity-marker
```

### Использование Partition для Canary-обновления

```yaml
spec:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 2 # Обновятся только индексы >= 2
```

```bash
# Применение изменений в образе
kubectl patch statefulset web --type='json' -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/image", "value":"nginx:1.28"}]'

# Проверка: поды 0 и 1 остались на старом образе, 2+ обновились
kubectl get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[0].image}{"\n"}{end}'
# → web-0   nginx:1.27
# → web-1   nginx:1.27
# → web-2   nginx:1.28

# Снять ограничение — продолжить полный rollout
kubectl patch statefulset web -p '{"spec":{"updateStrategy":{"type":"RollingUpdate","rollingUpdate":{"partition":0}}}}'
```

### Проверка сетевой идентификации и DNS

```bash
# Hostname внутри контейнера равен имени пода
kubectl exec web-0 -- hostname
# → web-0

# Разрешение FQDN пода (A-запись) из debug-пода
kubectl run dns-busybox --rm -it --restart=Never --image=busybox:1.28 -- nslookup web-1.web
# → Server:    10.96.0.10
# → Address:   10.96.0.10#53
# → Name:      web-1.web.default.svc.cluster.local
# → Address:   10.244.1.7

# SRV-записи для именованного порта http (требуется dig)
kubectl run dnsutils --rm -it --restart=Never --image=registry.k8s.io/e2e-test-images/jessie-dnsutils:1.3 -- dig +short SRV _http._tcp.web.default.svc.cluster.local
# → 0 50 80 web-0.web.default.svc.cluster.local.
# → 0 50 80 web-1.web.default.svc.cluster.local.
# → 0 50 80 web-2.web.default.svc.cluster.local.

# Метки идентичности
kubectl get pods -l app=web -L apps.kubernetes.io/pod-index,statefulset.kubernetes.io/pod-name
# → NAME    READY   STATUS    RESTARTS   AGE   POD-INDEX   POD-NAME
# → web-0   1/1     Running   0          2m    0           web-0
```

### Наблюдение за порядком создания и масштабирования

```bash
# Последовательное создание: web-0, затем web-1, затем web-2
kubectl get pods -w -l app=web
# → web-0   0/1     Pending   0          0s
# → web-0   1/1     Running   0          5s
# → web-1   0/1     Pending   0          0s     # только после Ready web-0
# → web-1   1/1     Running   0          5s
# → web-2   0/1     Pending   0          0s     # только после Ready web-1

# Масштабирование вверх: добавляются новые индексы
kubectl scale statefulset web --replicas=5
# → statefulset.apps/web scaled
# (наблюдаем создание web-3, затем web-4)

# Масштабирование вниз: удаление в обратном порядке 4 → 3
kubectl scale statefulset web --replicas=3
# (удаляются web-4, затем web-3; PVC сохраняются — политика по умолчанию)
kubectl get pvc
# → data-web-0   Bound   ...   # все 5 PVC на месте, включая data-web-3, data-web-4
```

### Проверка политики удержания PVC

```bash
# Настроить автоочистку дисков при уменьшении реплик
kubectl patch statefulset web -p '{"spec":{"persistentVolumeClaimRetentionPolicy":{"whenScaled":"Delete"}}}'

# Масштабирование вниз
kubectl scale statefulset web --replicas=1

# PVC выбывших реплик удалены автоматически
kubectl get pvc
# → data-web-0   Bound   ...    # единственный сохраненный диск

# Вернуть реплики — когда политика Retain, под "подхватит" сохраненный диск
kubectl scale statefulset web --replicas=3
```

### Наблюдение за обновлением: порядок и ревизии

```bash
# Начать rollout (обновление идет от старшего индекса к младшему)
kubectl set image statefulset/web web=nginx:1.28
# → statefulset.apps/web image updated

kubectl get pods -w -l app=web
# → web-2   Terminating    ...   # сначала обновляется максимальный индекс
# → web-2   1/1  Running   ...   # затем web-1, затем web-0

# Контроль прогресса
kubectl rollout status statefulset/web --timeout=180s
# → statefulset rolling update complete

# Текущая (current) и целевая (update) ревизии после завершения совпадают
kubectl get statefulset web -o jsonpath='{.status.currentRevision}{"\t"}{.status.updateRevision}{"\n"}'
# → web-6c7d99b5d6   web-6c7d99b5d6

# История и откат
kubectl rollout history statefulset/web
kubectl rollout undo statefulset/web
# → statefulset.apps/web rolled back
```

### Наблюдение за graceful-завершением

```bash
# Контейнер логирует получение SIGTERM (запускается sh -c с trap)
kubectl exec web-0 -- sh -c 'trap "echo RECEIVED-SIGTERM; exit 0" TERM; while true; do sleep 1; done' &

# Удалить под и посмотреть на логи предыдущей копии (после пересоздания)
kubectl delete pod web-0
kubectl logs web-0 --previous
# → RECEIVED-SIGTERM

# События удаления пода
kubectl get events --field-selector involvedObject.name=web-0
```

Если приложение не завершится до истечения `terminationGracePeriodSeconds` (по умолчанию 30с), будет отправлен `SIGKILL` — для длинных операций (сброс WAL, передача лидерства) период задается в явном виде:

```yaml
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 120
```

### Очистка окружения

```bash
# Удаление StatefulSet: поды удаляются, PVC по умолчанию СОХРАНЯЮТСЯ
kubectl delete statefulset web
# → statefulset.apps "web" deleted

# Доводка: удалить PVC (и, в зависимости от reclaimPolicy, данные на PV)
kubectl delete pvc data-web-0 data-web-1 data-web-2

# Headless Service
kubectl delete svc web
```

Полные сценарии (MySQL, ординалы, изменение размера диска, безопасный force-delete) — в **[Практическом руководстве](./statefulset_practical_guide.md)**; операционные процедуры (drain, неплановый отказ узла, бэкапы, мониторинг) — в **[Обзоре](./statefulset_overview.md)**.

## Дополнительная информация

### Диагностика и устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| Под в `Pending`, PVC в `Pending` | Нет StorageClass с динамическим провижинингом или `volumeBindingMode` не позволяет связать том | `kubectl get pvc` → `kubectl describe pvc <имя>`; проверить StorageClass и события планировщика |
| Под долго в `ContainerCreating` | Attach/Detach RWO-тома, Multi-Attach (диск занят прежним подом/узлом) | `kubectl describe pod <имя>` (события); убедиться, что старый под полностью удален и том отсоединен |
| RollingUpdate застрял | Обновленный под никогда не становится `Ready` (плохой образ/конфиг); известный баг — ручной откат без удаления пода | Вернуть шаблон (`rollout undo`) **и вручную удалить** поды с плохой ревизией (`kubectl delete pod <имя>`). Либо использовать `partition` для «заморозки» |
| FQDN пода не резолвится | Нет Headless Service / неверен `serviceName` / не совпадают labels; поды не публикуются до `Ready` | `nslookup` из debug-пода; проверить `publishNotReadyAddresses` для кворумного бутстрапа. Подробнее: [Headless Service](../../Networking/Service/service_type_headless.md) |
| Под вечно в `Terminating` на недоступном узле | Узел не вернулся, том привязан к нему | taint `node.kubernetes.io/out-of-service=nodeshutdown:NoExecute` (v1.28+); force-delete — только как крайняя мера. Подробнее: [Недоступность узла: поды в Terminating](../../Troubleshooting/Common_Errors/PodTerminating/node_unavailable_issues.md) |
| `kubectl apply` отклоняет манифест | Изменены иммутабельные поля (`selector.matchLabels`, `volumeClaimTemplates`) | Пересоздать объект после переноса данных или выполнить каскадную процедуру изменения размера (см. [Практическое руководство](./statefulset_practical_guide.md)) |
| PVC не удаляется после scale-down | Политика по умолчанию `whenScaled: Retain` | Это безопасное поведение; для автоочистки задать `whenScaled: Delete` |
| Ранний старт реплик при обновлении | `minReadySeconds` не задан, либо `maxUnavailable > 1` нарушает упорядоченность готовности | Задать `minReadySeconds` (например, 60) и не использовать параллельное обновление для кворумных нагрузок |

### Ограничения и известные проблемы

*   **StorageClass:** Требуется поддержка динамического провижининга для работы `volumeClaimTemplates`.
*   **Headless Service:** Его отсутствие ломает сетевую связность между репликами.
*   **Масштабирование:** Большие кластеры (100+ узлов) в режиме `OrderedReady` масштабируются очень долго из-за последовательного ожидания готовности.
*   **Автоматический failover отсутствует:** при отказе узла под пересоздается только после вмешательства человека (ручное удаление пода или taint `out-of-service`) — это осознанная защита от Split-brain.
*   **Иммутабельные поля:** `selector.matchLabels` и `volumeClaimTemplates` нельзя изменить после создания.
*   **Привязка к узлу/зоне:** RWO-диск «привязан» к зоне/узлу (узлу потребления). При `volumeBindingMode: WaitForFirstConsumer` под и диск создаются в одной зоне; миграция в другую зону требует копирования данных.
*   **ControllerRevision:** не редактировать вручную; `revisionHistoryLimit: 0` отключает откат.
*   **HPA и `replicas`:** при управлении масштабированием через HPA не задавайте `replicas` вручную в манифесте — повторный `kubectl apply` перезапишет масштабирование.
*   **`maxUnavailable` на кворумных системах:** для 3 реплик безопасное значение равно `1` (выигрыша нет), а увеличение значения нарушает последовательную готовность (см. раздел выше).
*   **Политика удержания PVC** не распространяется на PVC, созданные вручную (вне `volumeClaimTemplates`).

### Рекомендации

*   Для кворумных систем: PDB (`minAvailable`), pod anti-affinity по зонам и `minReadySeconds` — подробный разбор в **[Лучших практиках](./statefulset_best_practices.md)**, взаимодействие с прерываниями — в **[PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md)**.
*   Для БД с длительным восстановлением (WAL replay) используйте Startup Probe, чтобы Liveness-проба не убила под во время инициализации.
*   Для прав записи на том задавайте `securityContext.fsGroup`; для зональной локальности — `volumeBindingMode: WaitForFirstConsumer` в StorageClass.
*   Для безопасности задавайте `persistentVolumeClaimRetentionPolicy.whenDeleted: Retain` в Production (защита от случайного удаления дисков) и при необходимости `whenScaled: Delete` для горизонтально масштабируемых систем.

### См. также

*   **[Обзор StatefulSet](./statefulset_overview.md)** — архитектура, ключевые поля и операционные сценарии.
*   **[Практическое руководство](./statefulset_practical_guide.md)** — пошаговое развертывание с примерами манифестов.
*   **[StatefulSet vs Deployment](./statefulset_vs_deployment.md)** — сравнительная таблица и критерии выбора контроллера.
*   **[Local PV vs CSI](./statefulset_local_pv_vs_csi.md)** — выбор хранилища для БД.
*   **[Exporter Sidecar](./statefulset_exporter_sidecar.md)** — мониторинг БД через Prometheus.

### Ключевые Takeaways

Ниже — сводка ключевых моментов, которые необходимо знать для понимания и эксплуатации StatefulSet:

**Фундаментальные отличия от Deployment:**
- StatefulSet гарантирует стабильное имя (`name-0`, `name-1`), стабильный DNS через Headless Service и привязку к уникальному PVC через `volumeClaimTemplates`. Deployment создаёт взаимозаменяемые поды без постоянной идентичности.
- Порядок создания/удаления подов строго последовательный (0→N-1), а не параллельный — это критично для кворумных систем.
- `volumeClaimTemplates` иммутабелен после создания — изменение размера требует каскадной процедуры (патч PVC → `--cascade=orphan` → пересоздание).

**Зачем нужен Headless Service:**
- Контроллер устанавливает каждому поду `spec.hostname = pod-name` и `spec.subdomain = serviceName`, формируя стабильный FQDN: `$(pod-name).$(service-name).$(namespace).svc.cluster.local`.
- Без этого распределённые системы (Kafka, ZooKeeper, PostgreSQL) не могут обнаружить друг друга по именам.

**Защита от Split-brain:**
- При отказе узла контроллер **не пересоздаёт** под StatefulSet автоматически — это осознанная защита от ситуации, когда два процесса одновременно пишут в один диск.
- Безопасное восстановление: тейнт `node.kubernetes.io/out-of-service=nodeshutdown:NoExecute` (GA v1.28).
- `kubectl delete pod --force --grace-period=0` — крайняя мера, допустима только если узел гарантированно мёртв.

**Стратегии обновления:**
- **RollingUpdate** (по умолчанию) — от старшего индекса к младшему (N-1 → 0), по одному поду. Через `partition` — Canary-обновление.
- **OnDelete** — ручное удаление пода для обновления. Идеально для критичных БД с плановым окном обслуживания.
- **Recreate** (Alpha v1.37) — удаляет все поды сразу. Полный даунтайм, но исключает сосуществование двух версий.

**maxUnavailable vs maxSurge:**
- Deployment использует `maxSurge` (создание «лишних» подов до удаления старых). StatefulSet **не поддерживает `maxSurge`** — каждый под привязан к уникальному PVC.
- `maxUnavailable` StatefulSet (Beta v1.35): не может быть `0`, для 3 реплик безопасное значение = `1` (выигрыша нет, кворум = 2).
- Известный баг: в v1.35.0–v1.35.3 при `podManagementPolicy: Parallel` гейт `MaxUnavailableStatefulSet` вызывал deadlock (kubernetes/kubernetes#137409). Исправлен в v1.37.

**publishNotReadyAddresses:**
- По умолчанию Headless Service публикует в DNS только `Ready` поды. Кворумные системы (ZooKeeper, Cassandra) при бутстрапе должны найти соседей до готовности — «курица и яйца».
- Решение: `spec.publishNotReadyAddresses: true` в Headless Service.

**PDB и drain:**
- При `kubectl drain` поды выселяются с уважением к PDB. Для кворумных систем: `minAvailable = ⌈N/2⌉` (3 реплики → 2).
- PDB защищает только добровольные прерывания (drain), но не отказы узлов и не taint `out-of-service`.
- Слишком жёсткий PDB (`100%`) делает узлы «неудаляемыми» для Cluster Autoscaler.