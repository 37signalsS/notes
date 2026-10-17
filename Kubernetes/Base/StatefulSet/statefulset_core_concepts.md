# StatefulSet: Ключевые концепции

**Актуально для:** Kubernetes 1.30–1.37+ (Bare-Metal / On-Premise)

## Определения

*   **StatefulSet** — специализированный контроллер рабочей нагрузки (Workload Controller) в Kubernetes, предназначенный для управления приложениями с сохранением состояния (stateful). Обеспечивает каждому экземпляру пода уникальную идентичность, неизменное сетевое имя, выделенный постоянный диск и детерминированный порядок запуска, масштабирования и обновления.
*   **Headless Service** — сервис Kubernetes с параметром `.spec.clusterIP: None`. Не выполняет балансировку через единый виртуальный IP (VIP) и kube-proxy, а напрямую возвращает DNS A/AAAA-записи отдельных подов, формируя индивидуальные FQDN для каждой реплики.
*   **VolumeClaimTemplate (VCT)** — декларативный шаблон в спецификации StatefulSet, на основе которого контроллер автоматически генерирует уникальный объект **[PersistentVolumeClaim (PVC)](../../Storage/pv_and_pvc.md)** для каждого порядкового индекса пода.
*   **Ordinal Index (Порядковый индекс)** — целочисленный идентификатор пода (от `0` до `replicas - 1`, либо со смещением через `.spec.ordinals.start`), определяющий имя пода, доменное имя, имя PVC и очередность в жизненном цикле.
*   **Sticky Storage («Липкое хранилище»)** — архитектурный принцип StatefulSet, согласно которому при пересоздании, перезапуске или переносе пода на другой физический узел он всегда повторно подключает именно свой исходный том PVC/PV, сохраняя целостность локальных данных.
*   **ControllerRevision** — версионированный объект API (`apps/v1`), представляющий собой неизменяемый снимок (снапшот) шаблона пода (`spec.template`) на момент конкретного изменения спецификации StatefulSet. Используется для отслеживания истории выкаток и выполнения команды `kubectl rollout undo`.
*   **Partition (Партиционирование обновлений)** — механизм частичного обновления реплик StatefulSet (Canary-развертывание), задаваемый через `.spec.updateStrategy.rollingUpdate.partition`. Контроллер обновляет только поды с индексом `>= partition`, оставляя остальные на старой ревизии.
*   **Split-Brain (Расщепление кворума)** — аварийное состояние распределенной системы, при котором из-за сетевой изоляции (network partition) несколько узлов одновременно считают себя лидерами и ведут параллельную запись в данные. Для предотвращения split-brain StatefulSet строго реализует семантику «at-most-one» (не более одного экземпляра с данным именем в один момент времени).
*   **Non-Graceful Node Shutdown** — встроенный механизм аварийного высвобождения ресурсов (GA с v1.28) при физическом падении рабочего узла. При наложении на узел специального тейнта `node.kubernetes.io/out-of-service=nodeshutdown:NoExecute` контроллер принудительно отсоединяет заблокированные тома и разрешает безопасное пересоздание подов StatefulSet на живых узлах.

Базовые концепции архитектур хранения описаны в разделе **[Stateful vs Stateless](../../../Concepts/stateful_vs_stateless.md)**.
Операционный справочник (развертывание, обновление, обслуживание узлов, бэкапы) — в **[Обзоре StatefulSet](./statefulset_overview.md)** и **[Практическом руководстве](./statefulset_practical_guide.md)**.

---

## Базовые концепции и архитектура

### Архитектурная модель и цикл согласования

В отличие от `Deployment`, который делегирует управление подами контроллеру `ReplicaSet` (рассматривающему поды как взаимозаменяемый пул идентичных инстансов), контроллер `StatefulSet` напрямую управляет жизненным циклом каждого пода.

Цикл согласования (Reconciliation Loop) StatefulSet проверяет:
1. Текущее количество и состояние существующих подов с префиксом контроллера.
2. Наличие соответствующих PVC для каждого порядкового номера (`ordinal`).
3. Фазу готовности предшествующих подов при последовательном управлении (`OrderedReady`).
4. Актуальность назначенной ревизии пода (`ControllerRevision`) относительно целевой спецификации.

Если контроллер обнаруживает расхождение между желаемым состоянием (`spec`) и фактическим (`status`), он выполняет точечные мутации строго по одному поду за итерацию (за исключением режима `podManagementPolicy: Parallel` или использования параметра `maxUnavailable`).

```
                    ┌──────────────────────────────────────────────┐
                    │          StatefulSet Controller              │
                    └──────────────────────┬───────────────────────┘
                                           │
             ┌─────────────────────────────┼─────────────────────────────┐
             ▼                             ▼                             ▼
   ┌───────────────────┐         ┌───────────────────┐         ┌───────────────────┐
   │       web-0       │         │       web-1       │         │       web-2       │
   │ Hostname: web-0   │         │ Hostname: web-1   │         │ Hostname: web-2   │
   │ Index: 0          │         │ Index: 1          │         │ Index: 2          │
   └─────────┬─────────┘         └─────────┬─────────┘         └─────────┬─────────┘
             │                             │                             │
             ▼                             ▼                             ▼
   ┌───────────────────┐         ┌───────────────────┐         ┌───────────────────┐
   │ PVC: data-web-0   │         │ PVC: data-web-1   │         │ PVC: data-web-2   │
   │ RWO PV (Storage)  │         │ RWO PV (Storage)  │         │ RWO PV (Storage)  │
   └───────────────────┘         └───────────────────┘         └───────────────────┘
```

---

### Механизм стабильной сетевой идентификации

StatefulSet присваивает каждому поду детерминированное сетевое имя, сохраняющееся при перезапусках контейнера, смене IP-адреса пода и миграции на другой физический узел кластера. Это достигается обязательной интеграцией с **Headless Service**.

#### Алгоритм формирования сетевых идентификаторов

1. **Имя пода:** Формируется по шаблону `$(statefulset-name)-$(ordinal)`. По умолчанию нумерация начинается с `0` (например, `web-0`, `web-1`, `web-2`).
2. **Hostname и Subdomain:** При создании пода контроллер автоматически выставляет поля спецификации:
   * `spec.hostname = $(pod-name)`
   * `spec.subdomain = $(spec.serviceName)`
3. **FQDN пода:** Плагин CoreDNS/kube-dns кластера регистрирует персональную запись Fully Qualified Domain Name для каждого пода:
   ```text
   $(pod-name).$(service-name).$(namespace).svc.$(cluster-domain)
   ```
   Пример: `web-0.web-service.default.svc.cluster.local`.

#### Типы DNS-записей Headless Service

* **A/AAAA-записи подов:** `web-0.web.default.svc.cluster.local` → возвращает текущий IP-адрес пода `web-0`. Если под перезапускается и получает новый IP-адрес, CoreDNS обновляет A-запись.
* **A-запись самого Headless Service:** `web.default.svc.cluster.local` → возвращает список IP-адресов всех готовых (`Ready`) подов StatefulSet без балансировки. Клиент получает полный список эндпоинтов (Round-Robin на уровне DNS).
* **SRV-записи именованных портов:** Для каждого порта в спецификации Service, имеющего поле `name`, CoreDNS генерирует SRV-запись вида:
  ```text
  _$(port-name)._$(protocol).$(service-name).$(namespace).svc.$(cluster-domain)
  ```
  Пример: `_tcp-client._tcp.db.default.svc.cluster.local` возвращает приоритет, вес, порт и целевые FQDN подов. Это критично для механизмов автодискавери в системах распределенной координации (etcd, ZooKeeper, Hazelcast, Cassandra).

#### Проблема бутстрапа кворума и `publishNotReadyAddresses`

По умолчанию Kubernetes Service публикует в DNS IP-адреса только тех подов, которые успешно прошли Readiness Probe (`Ready = True`). 

В распределенных кворумных системах (etcd, Cassandra, ClickHouse, Patroni/PostgreSQL, RabbitMQ) возникает классическая коллизия «курицы и яйца»:
1. Нода БД не может пройти проверку готовности (`Readiness Probe`), пока не подключится к пирам и не восстановит кворум.
2. Пиры не могут найти ноду по ее FQDN, так как Service не публикует ее адрес в DNS до перехода в статус `Ready`.

**Решение для SRE/Sysadmin:** В спецификации Headless Service обязательно включается флаг `spec.publishNotReadyAddresses: true`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: cassandra
spec:
  clusterIP: None
  publishNotReadyAddresses: true # Публиковать IP подов в DNS до прохождения Readiness Probe
  selector:
    app: cassandra
  ports:
  - port: 9042
    name: cql
```

#### Идентификационные метки пода

Kubernetes автоматически снабжает поды StatefulSet системными метками:
* `statefulset.kubernetes.io/pod-name`: имя конкретного экземпляра (например, `web-0`). Позволяет адресовать ClusterIP-сервис или NetworkPolicy на отдельную реплику.
* `apps.kubernetes.io/pod-index`: порядковый целочисленный индекс пода (`0`, `1`, `2`...). Функция переведена в статус **GA в v1.32**. Исключает необходимость парсить строку имени в Prometheus-метриках и правилах Alertmanager.

---

### Управление персистентным хранилищем через шаблоны

<a id="persistentvolumeclaim-pvc"></a>

В отличие от `Deployment`, где все поды используют ссылки на общие заранее созданные PVC или эфемерные тома, StatefulSet использует секцию `volumeClaimTemplates` (VCT).

#### Жизненный цикл и именование PVC

1. **Генерация объектов:** Для каждой реплики с порядковым индексом $i$ контроллер генерирует уникальный объект PersistentVolumeClaim по формуле:
   ```text
   $(claim-name)-$(statefulset-name)-$(ordinal)
   ```
   Пример: для `volumeClaimTemplates[0].metadata.name: data` и StatefulSet `db` формируются PVC `data-db-0`, `data-db-1`, `data-db-2`.
2. **Предварительное связывание (Binding Order):** Контроллер создает PVC **до** создания самого пода. При последовательном запуске под не начнет инициализацию контейнеров, пока его PVC не перейдет в статус `Bound` (том выделен и привязан).
3. **Механизм Sticky Storage:** Если под `db-1` завершается аварийно или выселяется на другой физический узел, вновь созданный экземпляр `db-1` повторно подключает именно `data-db-1`. Данные не мигрируют между разными индексами.

#### Особенности эксплуатации на Bare-Metal / On-Premise

* **Режим доступа ReadWriteOnce (RWO):** Для баз данных стандартно используется блочное или файловое хранилище (iSCSI, Ceph RBD, Local PV, SAN) в режиме `ReadWriteOnce`. Диск монтируется только к одному рабочему узлу одновременно.
* **Привязка к топологии узлов (`WaitForFirstConsumer`):** В on-premise кластерах StorageClass для StatefulSet **обязан** использовать параметр:
  ```yaml
  volumeBindingMode: WaitForFirstConsumer
  ```
  При режиме `Immediate` CSI-плагин создает том немедленно при появлении PVC, выбирая произвольный пул или хост. В результате PV может оказаться привязанным к гипервизору/стойке `Rack-A`, тогда как планировщик Kubernetes (`kube-scheduler`) позже попытается разместить под на узел в `Rack-B` из-за нехватки RAM/CPU. Это приводит к фатальной ошибке `VolumeNodeAffinityConflict`. Режим `WaitForFirstConsumer` откладывает связывание PV до момента, когда планировщик выберет конкретный узел для пода.
* **Права доступа к файловой системе (`fsGroup`):** Большинство баз данных (PostgreSQL, MySQL, Redis) запускаются от непривилегированного пользователя (UID != 0). Для того чтобы контейнер имел права на запись в свежеотформатированный CSI-диск, в `securityContext` пода задается `fsGroup`:
  ```yaml
  spec:
    securityContext:
      fsGroup: 999 # kubelet выполнит chown/chmod тома при монтировании
      fsGroupChangePolicy: "OnRootMismatch" # Оптимизация: не рекурсировать миллионы файлов, если root уже верен
  ```

#### Иммутабельность VCT и процедура изменения размера дисков

Секция `volumeClaimTemplates` является **иммутабельной**. Попытка изменить размер хранилища (`storage: 50Gi` вместо `20Gi`) напрямую в YAML StatefulSet и применить манифест завершится ошибкой API-сервера:
```text
The StatefulSet "db" is invalid: spec: Forbidden: updates to statefulset spec for fields other than 'replicas', 'template', 'updateStrategy', 'persistentVolumeClaimRetentionPolicy', 'minReadySeconds' and 'ordinals' are forbidden
```

В On-Prem кластерах с CSI-драйверами, поддерживающими онлайн-расширение (`allowVolumeExpansion: true`), SRE выполняет процедуру:
1. Патчинг размера в существующих объектах PVC по очереди (`kubectl patch pvc data-db-0 ...`).
2. CSI-драйвер и kubelet расширяют файловую систему тома (онлайн либо при перезапуске пода).
3. Приведение манифеста StatefulSet в Git к актуальному размеру выполняется либо через удаление объекта контроллера без удаления подов (`kubectl delete statefulset db --cascade=orphan`), либо через наложение обновленного манифеста поверх сиротских ресурсов.

---

### Управление порядковыми индексами

#### Произвольный начальный индекс (`spec.ordinals.start`)

Функция переведена в статус **GA в v1.31**. Позволяет сместить начальный порядковый номер подов.

```yaml
spec:
  replicas: 3
  ordinals:
    start: 3
```
* **Результат:** будут созданы поды `web-3`, `web-4`, `web-5` (и PVC `data-web-3`, `data-web-4`, `data-web-5`).
* **Применение в DevOps/SRE:**
  * **Шардирование:** разделение шардов одной логической БД по разным пулам нод или разным StatefulSet без коллизий в именах и томах.
  * **Бесшовный перенос между кластерами:** миграция распределенной БД частями. Новые реплики поднимаются в целевом кластере с индексами 3–5, подключаются к репликации исходного кластера (поды 0–2), после чего старый кластер гасится.

---

### Политика удержания PVC (`persistentVolumeClaimRetentionPolicy`)

Функция переведена в статус **GA в v1.32**. Решает многолетнюю проблему накопления «мусорных» дисков (Leaked PVCs).

Поле `.spec.persistentVolumeClaimRetentionPolicy` управляет удалением PVC в двух событиях:
* `whenDeleted`: поведение при полном удалении объекта StatefulSet (`kubectl delete statefulset ...`).
* `whenScaled`: поведение при уменьшении количества реплик (Scale down).

Допустимые значения:
* `Retain` (по умолчанию для обоих параметров) — PVC и PV сохраняются на дисковой подсистеме.
* `Delete` — PVC автоматически удаляется сборщиком мусора Kubernetes.

```yaml
spec:
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain  # Защита от случайного удаления базы данных
    whenScaled: Delete   # Очистка дисков временных рабочих реплик при уменьшении нагрузки
```

**Критические нюансы для администратора:**
* Политика управляет только объектами PVC, сгенерированными через `volumeClaimTemplates`. Если том был объявлен вручную в `spec.template.volumes`, политика его не затронет.
* Реальное удаление физических данных на СХД/SAN при удалении PVC зависит от параметра `reclaimPolicy` используемого `StorageClass` (`Delete` очищает диск на СХД, `Retain` переводит PV в статус `Released` без очистки блоков).
* Удаление пода вручную (`kubectl delete pod web-2`) **не считается** масштабированием (`whenScaled`). Под будет пересоздан с тем же PVC `data-web-2`.

---

### Жизненный цикл и порядок управления подами

Политика управления подами задается полем `.spec.podManagementPolicy`:

```yaml
spec:
  podManagementPolicy: OrderedReady # Значение по умолчанию
```

#### 1. Режим `OrderedReady` (Строгая последовательность)

Гарантирует детерминированное развертывание распределенных систем:
* **Запуск и масштабирование вверх:** Поды создаются строго по возрастанию: `0 → 1 → 2`. Контроллер **не начинает** создание пода $i$, пока под $i-1$ не перейдет в фазу `Running` и статус `Ready = True`.
* **Масштабирование вниз:** Поды удаляются строго в обратном порядке: `N-1 → N-2 → 0`. Контроллер дожидается полного завершения и удаления пода $i$ из API-сервера, прежде чем послать сигнал на останов пода $i-1$.
* **Задержка готовности (`minReadySeconds`):** Поле спецификации (GA v1.25), задающее минимальное количество секунд, в течение которых под должен оставаться в статусе `Ready` без падений, прежде чем он будет признан готовым, и контроллер перейдет к созданию следующей реплики. Предотвращает лавинообразный запуск неисправных нод БД.

#### 2. Режим `Parallel` (Параллельный запуск)

Все поды создаются или удаляются одновременно без ожидания готовности соседей. Используется для stateless-ворклоадов, которым требуется только уникальное имя и DNS, либо для систем с собственной независимой логикой кластеризации.

---

### Стратегии обновления (`updateStrategy`)

Поле `.spec.updateStrategy.type` определяет логику развертывания новых версий приложения:

```yaml
spec:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 0
```

#### 1. Стратегия `RollingUpdate`

Обновление выполняется в обратном порядке: от старшего индекса к младшему ($N-1 \to 0$). Контроллер удаляет под, дожидается создания новой версии, ожидает перехода в `Ready` (и истечения `minReadySeconds`), и только затем переходит к следующему.

##### Канареечные выкатки через `partition`

Поле `spec.updateStrategy.rollingUpdate.partition` задает границу индекса:
* Все поды с индексом `>= partition` будут обновлены до новой версии шаблона.
* Все поды с индексом `< partition` останутся на старой версии (даже при аварийном падении и пересоздании).
* Если задать `partition: N` (где $N$ — число реплик), выкатка будет полностью заморожена.

**Сценарий Canary для SRE:** В кластере из 5 нод (`db-0` ... `db-4`) устанавливаем `partition: 4`. Обновляется только `db-4`. Инженеры снимают метрики задержки, ошибки ввода-вывода и транзакций. Если метрики в норме — выставляется `partition: 0`, и обновляются остальные реплики.

##### Параллельное обновление через `maxUnavailable` (Beta v1.35+)

Позволяет ускорить обновление больших кластеров StatefulSet за счет одновременного обновления нескольких подов:

```yaml
spec:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 2 # Число или процент (не может быть 0)
```

**Критическая информация для SRE о статусе фичи и кворуме:**
1. **История бага (kubernetes/kubernetes#137409):** В Kubernetes 1.35.0 фича включилась по умолчанию, но приводила к взаимной блокировке (deadlock) при сочетании с `podManagementPolicy: Parallel`, когда недоступные поды старой ревизии навечно блокировали прогресс rollout. В версиях v1.35.x и v1.36.x Feature Gate `MaxUnavailableStatefulSet` был **принудительно выключен по умолчанию**. Полное исправление бага включено в **Kubernetes 1.37**.
2. **Кворумная математика:** Для систем с кворумом размера $N$ допустимое число одновременно отключенных узлов строго ограничено формулой:
   $$F_{max} = \left\lfloor \frac{N - 1}{2} \right\rfloor$$
   * При $N=3$ кворум равен 2. Максимально допустимо потерять: $\lfloor 2/2 \rfloor = 1$ узел. Установка `maxUnavailable: 2` гарантированно разрушит кворум и приведет к отказу базы данных!
   * Ускорение через `maxUnavailable > 1` безопасно применять только на больших инсталляциях ($N \ge 5$).

#### 2. Стратегия `OnDelete`

Контроллер не выполняет автоматическую замену подов при изменении шаблона `template`. Под обновится до новой версии **только тогда**, когда администратор вручную удалит его через `kubectl delete pod`. Позволяет проводить контролируемые регламентные работы (Maintenance Window) с ручным переключением ролей Master/Replica в СУБД.

#### 3. Стратегия `Recreate` (Alpha v1.37+)

Управляется feature-gate `StatefulSetRecreateStrategy`. Контроллер единовременно удаляет абсолютно все поды StatefulSet, дожидается их полного уничтожения и очистки блокировок томов, после чего создает поды заново на новой ревизии. Применяется для унаследованных систем, архитектура которых принципиально исключает сосуществование двух разных версий протокола в одной сети.

---

### Механизм ControllerRevision и откат изменений

При каждом изменении шаблона `spec.template` контроллер StatefulSet создает дочерний ресурс `apps/v1.ControllerRevision` в том же пространстве имен:
1. Вычисляется хеш-сумма шаблона.
2. Создается объект ревизии (например, `web-6c7d99b5d6`), содержащий упакованный JSON-снапшот исходной спецификации.
3. В статусе StatefulSet фиксируются поля:
   * `status.currentRevision`: ревизия, на которой в данный момент работает стабильное поколение подов.
   * `status.updateRevision`: целевая ревизия, к которой контроллер приводит поды.

Глубина сохраняемой истории определяется полем `.spec.revisionHistoryLimit` (по умолчанию `10`). Значение `0` полностью отключает сохранение ревизий и блокирует возможность отката через `kubectl rollout undo`.

---

### Завершение работы (Graceful Termination)

Корректная остановка базы данных требует сохранения буферов, завершения активных клиентских транзакций, сброса журнала упреждающей записи (WAL/fsync) и передачи роли лидера (failover).

#### Последовательность остановки пода

```
               [ Команда на удаление пода ]
                           │
                           ▼
             ┌───────────────────────────┐
             │ Вызов preStop Hook        │ (Синхронный блокирующий запуск скрипта)
             └─────────────┬─────────────┘
                           │
                           ▼
             ┌───────────────────────────┐
             │ Отправка сигнала SIGTERM  │ (Приложение начинает процедуру shutdown)
             └─────────────┬─────────────┘
                           │
                 [ Обратный отсчет таймера ]
             terminationGracePeriodSeconds (по умолчанию 30с)
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
[ Процесс завершился сам ]     [ Таймер истек, процесс жив ]
             │                           │
             │                           ▼
             │                 ┌───────────────────┐
             │                 │ Сигнал SIGKILL    │ (Принудительное убийство PID 1)
             │                 └─────────┬─────────┘
             │                           │
             └─────────────┬─────────────┘
                           ▼
             [ Отмонтирование тома (Umount) ]
                           │
                           ▼
             [ Удаление объекта Pod из etcd ]
```

**Рекомендация SRE для СУБД:** Дефолтного значения `terminationGracePeriodSeconds: 30` категорически недостаточно для нагруженных СУБД. В production задается диапазон `120-300` секунд:

```yaml
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 180
      containers:
      - name: postgres
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "pg_ctl -D $PGDATA stop -m fast"]
```

---

### Отказоустойчивость, семантика At-Most-One и защита от Split-Brain

<a id="неплановый-отказ-узла"></a>

Главная дилемма распределенных баз данных — предотвращение повреждения дисков при сетевом разделении (Network Partition). 

Если рабочий узел перестает отвечать (`NodeStatus = NotReady`), контроллер Kubernetes **не имеет права** автоматически пересоздать под `db-0` на другом узле. 

#### Почему автоматический failover запрещен («At-Most-One»)

Если старый узел не умер физически, а лишь временно потерял сетевую связность с Control Plane:
1. Процесс СУБД на старом узле продолжает работать и писать на локальный или SAN-том.
2. Если контроллер создаст второй под с именем `db-0` на новом узле и подключит тот же том — произойдет катастрофическая порча данных (Data Corruption) из-за одновременной несогласованной записи с двух хостов (Multi-Attach).

Пока старый под не завершился и не удален из etcd, контроллер блокирует создание реплики с тем же индексом.

#### Протокол действий SRE при аварии узла (Non-Graceful Node Shutdown)

Начиная с Kubernetes 1.28 (GA), разработан стандартный безопасный протокол вывода упавшего узла:

1. **Диагностика:** Администратор через Out-of-band управление (IPMI/iLO/BMC) убеждается, что сервер действительно выключен по питанию или изолирован от SAN/сети.
2. **Наложение тейнта Out-of-service:**
   ```bash
   kubectl taint nodes node-crash.internal node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
   # → node/node-crash.internal tainted
   ```
3. **Реакция контроллеров:**
   * Kubelet-эмулятор немедленно удаляет поды на узле, форсируя очистку их статуса в API.
   * `AttachDetachController` принудительно освобождает блокировки томов `VolumeAttachment`.
   * Контроллер StatefulSet видит, что старый под `db-0` удален, и безопасно создает новый `db-0` на исправном узле с подключением его исходного PVC.
4. **Снятие тейнта после ремонта узла:**
   ```bash
   kubectl taint nodes node-crash.internal node.kubernetes.io/out-of-service:NoExecute-
   # → node/node-crash.internal untainted
   ```

> [!CAUTION]
> Принудительное удаление пода через `kubectl delete pod db-0 --force --grace-period=0` без предварительной гарантии физического отключения хоста является грубым нарушением правил SRE. Если дисковый том остался смонтирован на гипервизоре старого узла, повторное подключение вызовет ошибку `Multi-Attach error for volume` либо разрушит файловую систему.

#### Защита планового обслуживания через PodDisruptionBudget (PDB)

При плановом выводе узлов на обслуживание (`kubectl drain`) планировщик выселения (Eviction API) руководствуется правилами PDB.

Для кворума из 3 нод задается бюджет:
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: db-pdb
spec:
  minAvailable: 2 # Допустимо выселять строго по 1 поду за раз
  selector:
    matchLabels:
      app: db
```
PDB предотвращает одновременный drain двух узлов с подами одной СУБД, сохраняя доступность кластера.

---

## Практические сценарии

### Предварительные требования

Для развертывания стенда необходимы:
1. Кластер Kubernetes версии v1.30–v1.37+ под управлением Linux (Bare-Metal или On-Premise виртуализация).
2. Настроенный `StorageClass` с динамическим провижинингом томов (например, Ceph-RBD, Local-Path или OpenEBS) и параметром `volumeBindingMode: WaitForFirstConsumer`.
3. Утилита `kubectl` с правами администратора в целевом пространстве имен.
4. Установленные в кластере утилиты DNS-диагностики (`nslookup`, `dig`).

---

### Подготовка тестового стенда

Создадим изолированное пространство имен и базовый манифест: Headless Service и StatefulSet с тремя репликами Nginx и шаблоном постоянного тома на 1 GiB.

```bash
kubectl create namespace sts-lab
# → namespace/sts-lab created
```

Сохраните манифест в файл `lab-statefulset.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web-service
  namespace: sts-lab
spec:
  clusterIP: None
  publishNotReadyAddresses: true
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
  namespace: sts-lab
spec:
  serviceName: "web-service"
  replicas: 3
  podManagementPolicy: OrderedReady
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      terminationGracePeriodSeconds: 60
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

Применение стенда:

```bash
kubectl apply -f lab-statefulset.yaml
# → service/web-service created
# → statefulset.apps/web created
```

---

### Сценарий 1: Наблюдение за механизмом Sticky Storage

Проверим автоматическую генерацию томов и сохранность данных при удалении пода.

```bash
# 1. Проверяем созданные объекты PVC
kubectl get pvc -n sts-lab
# → NAME         STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS
# → data-web-0   Bound    pvc-8e2b3c4d-11aa-44bb-99cc-0123456789ab   1Gi        RWO            local-storage
# → data-web-1   Bound    pvc-9f3c4d5e-22bb-55cc-00dd-123456789abc   1Gi        RWO            local-storage
# → data-web-2   Bound    pvc-0a4d5e6f-33cc-66dd-11ee-23456789abcd   1Gi        RWO            local-storage

# 2. Записываем уникальную сигнатуру на диск пода web-0
kubectl exec -n sts-lab web-0 -- sh -c 'echo "cluster-data-node-0" > /usr/share/nginx/html/index.html'

# 3. Удаляем под web-0
kubectl delete pod web-0 -n sts-lab
# → pod "web-0" deleted

# 4. Наблюдаем за пересозданием пода контроллером
kubectl get pod web-0 -n sts-lab -w
# → web-0   0/1     Pending             0          0s
# → web-0   0/1     ContainerCreating   0          2s
# → web-0   1/1     Running             0          4s

# 5. Проверяем, что под подключил тот же самый PVC data-web-0
kubectl describe pod web-0 -n sts-lab | grep -A2 -i volumes:
# → Volumes:
# →   data:
# →     Type:       PersistentVolumeClaim (a reference to a PersistentVolumeClaim in the same namespace)
# →     ClaimName:  data-web-0

# 6. Проверяем сохранность данных
kubectl exec -n sts-lab web-0 -- cat /usr/share/nginx/html/index.html
# → cluster-data-node-0
```

---

### Сценарий 2: Использование Partition для Canary-обновления

Проведем частичную канареечную выкатку новой версии образа только на старшую реплику `web-2`.

```bash
# 1. Выставляем partition = 2 (обновятся только индексы >= 2)
kubectl patch statefulset web -n sts-lab -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":2}}}}'
# → statefulset.apps/web patched

# 2. Обновляем версию образа Nginx до 1.28
kubectl set image statefulset/web nginx=nginx:1.28 -n sts-lab
# → statefulset.apps/web image updated

# 3. Проверяем версии образов по всем подам
kubectl get pods -n sts-lab -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[0].image}{"\n"}{end}'
# → web-0   nginx:1.27
# → web-1   nginx:1.27
# → web-2   nginx:1.28

# 4. Проверяем статус ревизий StatefulSet
kubectl get statefulset web -n sts-lab -o jsonpath='{"CurrentRevision: "}{.status.currentRevision}{"\nUpdateRevision:  "}{.status.updateRevision}{"\n"}'
# → CurrentRevision: web-789bf8d956
# → UpdateRevision:  web-56c6465fd7

# 5. Снимаем ограничение partition, разрешая полный rollout на весь кластер
kubectl patch statefulset web -n sts-lab -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":0}}}}'
# → statefulset.apps/web patched

# 6. Дожидаемся завершения rollout
kubectl rollout status statefulset/web -n sts-lab --timeout=120s
# → Waiting for 2 pods to be ready...
# → statefulset rolling update complete 3 pods at revision web-56c6465fd7...
```

---

### Сценарий 3: Проверка сетевой идентификации и DNS (A и SRV)

Убедимся в корректности формирования внутренних записей в CoreDNS.

```bash
# 1. Проверяем соответствие имени хоста внутри контейнера имени пода
kubectl exec -n sts-lab web-0 -- hostname
# → web-0

# 2. Запускаем диагностический под с утилитами dnsutils
kubectl run dns-test -n sts-lab --rm -it --restart=Never --image=registry.k8s.io/e2e-test-images/jessie-dnsutils:1.3 -- bash

# --- Внутри контейнера dns-test выполняем: ---

# Резолв персонального FQDN пода web-1:
nslookup web-1.web-service.sts-lab.svc.cluster.local
# → Server:    10.96.0.10
# → Address:   10.96.0.10#53
# → Name:      web-1.web-service.sts-lab.svc.cluster.local
# → Address:   10.244.2.15

# Резолв общего имени Headless Service (возвращает адреса всех подов):
nslookup web-service.sts-lab.svc.cluster.local
# → Name:      web-service.sts-lab.svc.cluster.local
# → Address:   10.244.1.12
# → Address:   10.244.2.15
# → Address:   10.244.3.18

# Проверка SRV-записи именованного порта http:
dig +short SRV _http._tcp.web-service.sts-lab.svc.cluster.local
# → 0 33 80 web-0.web-service.sts-lab.svc.cluster.local.
# → 0 33 80 web-1.web-service.sts-lab.svc.cluster.local.
# → 0 33 80 web-2.web-service.sts-lab.svc.cluster.local.

exit
```

Проверим системные метки подов:
```bash
kubectl get pods -n sts-lab -L apps.kubernetes.io/pod-index,statefulset.kubernetes.io/pod-name
# → NAME    READY   STATUS    RESTARTS   AGE   POD-INDEX   POD-NAME
# → web-0   1/1     Running   0          10m   0           web-0
# → web-1   1/1     Running   0          10m   1           web-1
# → web-2   1/1     Running   0          10m   2           web-2
```

---

### Сценарий 4: Наблюдение за порядком создания и масштабирования

Проверим работу алгоритма `OrderedReady`.

```bash
# 1. Запускаем масштабирование вверх до 5 реплик
kubectl scale statefulset web -n sts-lab --replicas=5
# → statefulset.apps/web scaled

# 2. Наблюдаем за очередностью: web-4 не создастся, пока web-3 не станет Ready
kubectl get pods -n sts-lab -l app=web -w
# → web-3   0/1     Pending   0          0s
# → web-3   1/1     Running   0          6s
# → web-4   0/1     Pending   0          0s
# → web-4   1/1     Running   0          5s

# 3. Выполняем scale-down обратно до 3 реплик
kubectl scale statefulset web -n sts-lab --replicas=3
# → statefulset.apps/web scaled

# 4. Проверяем обратный порядок удаления (сначала web-4, затем web-3)
# По умолчанию диски data-web-3 и data-web-4 сохраняются!
kubectl get pvc -n sts-lab
# → data-web-0   Bound   pvc-xxx   1Gi   RWO
# → data-web-1   Bound   pvc-yyy   1Gi   RWO
# → data-web-2   Bound   pvc-zzz   1Gi   RWO
# → data-web-3   Bound   pvc-aaa   1Gi   RWO
# → data-web-4   Bound   pvc-bbb   1Gi   RWO
```

---

### Сценарий 5: Проверка политики удержания PVC (Auto-Delete при scale-down)

Настроим автоматическую очистку дисков при масштабировании вниз.

```bash
# 1. Включаем whenScaled: Delete
kubectl patch statefulset web -n sts-lab -p '{"spec":{"persistentVolumeClaimRetentionPolicy":{"whenScaled":"Delete","whenDeleted":"Retain"}}}'
# → statefulset.apps/web patched

# 2. Масштабируем до 4 реплик (создается под web-3 и PVC data-web-3)
kubectl scale statefulset web -n sts-lab --replicas=4
# → statefulset.apps/web scaled

# Дожидаемся готовности
kubectl rollout status statefulset/web -n sts-lab

# 3. Масштабируем вниз до 3 реплик
kubectl scale statefulset web -n sts-lab --replicas=3
# → statefulset.apps/web scaled

# 4. Проверяем PVC: диск data-web-3 автоматически удален контроллером
kubectl get pvc -n sts-lab
# → data-web-0   Bound   pvc-xxx   1Gi   RWO
# → data-web-1   Bound   pvc-yyy   1Gi   RWO
# → data-web-2   Bound   pvc-zzz   1Gi   RWO
```

---

### Сценарий 6: Наблюдение за Graceful-завершением

Проверим корректность отправки сигнала `SIGTERM` и таймаут завершения.

```bash
# 1. Запускаем в поде фоновый процесс, перехватывающий сигнал SIGTERM
kubectl exec -n sts-lab web-0 -- sh -c 'trap "echo [$(date)] RECEIVED-SIGTERM-SHUTTING-DOWN; exit 0" TERM; while true; do sleep 1; done' &

# 2. В отдельном окне удаляем под web-0
kubectl delete pod web-0 -n sts-lab
# → pod "web-0" deleted

# 3. После пересоздания пода читаем логи предыдущего контейнера
kubectl logs web-0 -n sts-lab --previous
# → [Sat Oct 17 21:55:00 UTC 2026] RECEIVED-SIGTERM-SHUTTING-DOWN
```

---

### Сценарий 7: Очистка окружения

```bash
# 1. Удаление StatefulSet
kubectl delete statefulset web -n sts-lab
# → statefulset.apps "web" deleted

# 2. Удаление оставшихся PVC (поскольку whenDeleted: Retain)
kubectl delete pvc -n sts-lab -l app=web
# → persistentvolumeclaim "data-web-0" deleted
# → persistentvolumeclaim "data-web-1" deleted
# → persistentvolumeclaim "data-web-2" deleted

# 3. Удаление сервиса и пространства имен
kubectl delete service web-service -n sts-lab
kubectl delete namespace sts-lab
# → namespace "sts-lab" deleted
```

---

## Операции и команды

Сводная таблица ключевых команд CLI для администрирования StatefulSet:

| Задача / Операция | Команда kubectl | Ожидаемый результат / Примечание |
| :--- | :--- | :--- |
| **Просмотр состояния** | `kubectl get sts -o wide` | Отображает желаемое число реплик, текущее, готовое число и селекторы |
| **История ревизий** | `kubectl rollout history statefulset/<name>` | Список сохраненных `ControllerRevision` с номерами ревизий |
| **Откат на прошлую ревизию** | `kubectl rollout undo statefulset/<name>` | Откат шаблона пода к предыдущему снимку |
| **Откат на конкретную ревизию** | `kubectl rollout undo statefulset/<name> --to-revision=2` | Точечный откат к ревизии №2 |
| **Проверка статуса rollout** | `kubectl rollout status statefulset/<name> --timeout=180s` | Блокирующий мониторинг до завершения выкатки по всем подам |
| **Приостановка rollout (Canary)** | `kubectl patch sts <name> -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":1}}}}'` | Замораживает обновление для всех подов с индексом `< 1` |
| **Ручной перезапуск подов** | `kubectl rollout restart statefulset/<name>` | Поочередно пересоздает все поды в порядке $N-1 \to 0$ |
| **Масштабирование** | `kubectl scale sts <name> --replicas=5` | Запуск подов с новыми индексами в режиме `OrderedReady` |
| **Авария узла (Safe Taint)** | `kubectl taint nodes <node> node.kubernetes.io/out-of-service=nodeshutdown:NoExecute` | Форсирует отсоединение томов и пересоздание подов на живых узлах |
| **Снятие аварийного тейнта** | `kubectl taint nodes <node> node.kubernetes.io/out-of-service:NoExecute-` | Возврат узла в строй после физического ремонта |
| **Удаление без удаления подов** | `kubectl delete sts <name> --cascade=orphan` | Удаляет только объект STS; поды и PVC остаются работать (для изменения VCT) |

---

## Устранение неполадок

### Матрица типовых инцидентов и диагностика

| Симптом инцидента | Вероятная первопричина | Пошаговый ранбук решения для SRE |
| :--- | :--- | :--- |
| **Под завис в статусе `Pending`, PVC в `Pending`** | 1. Отсутствует StorageClass по умолчанию.<br>2. CSI-драйвер хранилища (Ceph, SAN) перегружен или недоступен.<br>3. `volumeBindingMode: WaitForFirstConsumer`, но ни один узел не удовлетворяет требованиям ресурсов пода (CPU/RAM/Affinity). | 1. `kubectl describe pvc <claim-name>` — изучить секцию `Events:`.<br>2. `kubectl get storageclass` — проверить наличие `(default)` и права провижинера.<br>3. `kubectl describe pod <pod-name>` — проверить события планировщика `0/N nodes available: Insufficient memory/cpu`. |
| **Под застрял в `ContainerCreating`, ошибка `Multi-Attach error for volume`** | Дисковый том RWO не был корректно отмонтирован на прежнем физическом узле (узел завис/перезагрузился), `AttachDetachController` блокирует параллельный монтаж. | 1. Проверить статус старого узла: `kubectl get node <old-node>`.<br>2. Проверить объекты привязки томов: `kubectl get volumeattachments \| grep <pv-name>`.<br>3. Если старый узел физически мертв, применить `kubectl taint nodes <old-node> node.kubernetes.io/out-of-service=nodeshutdown:NoExecute`. |
| **Под вечно висит в `Terminating` на упавшем узле** | Узел перешел в `NotReady`. Kubernetes соблюдает семантику `at-most-one` и не удаляет под из API, защищая СУБД от Split-Brain. | 1. **Категорически запрещено** сразу выполнять `delete pod --force`.<br>2. Проверить узел через IPMI/BMC.<br>3. Наложить тейнт `out-of-service` (v1.28+) на узел.<br>4. Только если узел полностью списан/утилизирован — удалить под с `--force --grace-period=0`. |
| **RollingUpdate остановился и застрял** | 1. Новый под не может пройти Readiness Probe (ошибка конфигурации, базы, падение процесса).<br>2. В спецификации установлен `partition > 0`. | 1. `kubectl rollout status sts <name>` — узнать текущий застрявший индекс.<br>2. `kubectl logs <pod-name>` и `kubectl describe pod <pod-name>` — определить причину отказа проб.<br>3. Выполнить `kubectl rollout undo sts <name>` для отката ревизии. При необходимости вручную удалить неисправный под. |
| **FQDN пода не резолвится внутри кластера** | 1. Не создан Headless Service или опечатка в поле `.spec.serviceName`.<br>2. Селекторы Service не совпадают с labels пода.<br>3. Поды не перешли в `Ready`, а параметр `publishNotReadyAddresses` не включен. | 1. `kubectl get svc <serviceName>` — убедиться в наличии `CLUSTER-IP: None`.<br>2. Проверить endpoints: `kubectl get endpoints <serviceName>` или `kubectl get endpointslices`.<br>3. Добавить `publishNotReadyAddresses: true` в манифест Headless Service. |
| **Ошибка API: `spec: Forbidden: updates to statefulset spec... are forbidden`** | Попытка изменить иммутабельные поля (`volumeClaimTemplates`, `serviceName`, `selector.matchLabels`) через `kubectl apply`. | 1. Не пытаться форсировать через обычный apply.<br>2. Для изменения шаблона дисков выполнить каскадное удаление контроллера: `kubectl delete sts <name> --cascade=orphan`, изменить манифест в Git и выполнить `kubectl apply -f ...`. |
| **PVC не удаляются после `kubectl scale --replicas=...`** | По умолчанию действует безопасная политика `whenScaled: Retain`. | Диски остаются в системе для предотвращения потери данных. Для автоматической очистки пропатчите `.spec.persistentVolumeClaimRetentionPolicy.whenScaled: Delete`. |
| **Потеря кворума базы данных при обновлении** | Использован параметр `maxUnavailable > 1` на 3-узловом кластере (одновременно отключились 2 ноды из 3). | Восстановить узел из бэкапа/WAL, вернуть `maxUnavailable: 1` (или убрать блок `maxUnavailable`, оставив дефолтное обновление по 1 поду), проверить настройки PDB. |

---

## Лучшие практики

### 1. Архитектура хранилища и топология узлов (On-Premise)

* **Топологическая привязка:** Всегда используйте `volumeBindingMode: WaitForFirstConsumer` в StorageClass для локальных дисков (Local PV) и зональных блочных СХД. Это гарантирует, что том выделится именно на том хосте или в той серверной стойке, где запущен под.
* **Права доступа к данным:** Всегда явно задавайте `securityContext.fsGroup` и оптимизируйте время старта больших объемов данных директивой `fsGroupChangePolicy: "OnRootMismatch"`, чтобы kubelet не тратил десятки минут на рекурсивный `chmod` миллионов файлов при каждом рестарте.
* **Расширяемость томов:** Убедитесь, что в StorageClass включен флаг `allowVolumeExpansion: true`. Без него расширение дисков базы данных потребует сложной ручной миграции через резервные копии.

### 2. Отказоустойчивость и изоляция сбоев

* **Анти-аффинити подов (PodAntiAffinity):** Поды одного StatefulSet никогда не должны размещаться на одном физическом гипервизоре или в одной серверной стойке. Используйте жесткие или мягкие правила топологии:
  ```yaml
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchExpressions:
          - key: app
            operator: In
            values: ["db"]
        topologyKey: "kubernetes.io/hostname"
  ```
* **Защита бюджета доступности (PDB):** Для распределенных систем с кворумом размера $N$ всегда создавайте объект `PodDisruptionBudget` с формулой:
  $$\text{minAvailable} = \left\lfloor \frac{N}{2} \right\rfloor + 1$$
  Для кластера из 3 нод задавайте `minAvailable: 2`. Это заблокирует одновременный `drain` двух физических серверов при обновлении ОС.

### 3. Пробы жизнеспособности и бутстрап (Startup Probes)

* **Защита длительного восстановления (Crash Recovery):** Базы данных с большим буферным пулом после аварийной остановки могут выполнять replay WAL-журналов от 5 до 30 минут. 
* Если использовать только `LivenessProbe` с низким таймаутом, kubelet убьет восстанавливающуюся ноду по таймауту, вызвав бесконечный цикл `CrashLoopBackOff` и разрушение БД.
* **Решение:** Обязательно настраивайте `startupProbe` с достаточным лимитом попыток (`failureThreshold: 30`, `periodSeconds: 10`), отключая проверки Liveness до полного завершения инициализации.

### 4. Сетевая связность и устойчивость DNS

* **Бутстрап кворума:** Всегда выставляйте `spec.publishNotReadyAddresses: true` в Headless Service для распределенных баз данных (ZooKeeper, Cassandra, Patroni, Redis Sentinel).
* **Сетевые политики (NetworkPolicy):** При изоляции namespace не забывайте разрешать внутренний межподовый трафик между репликами StatefulSet по портам репликации и gossip-протокола.

### 5. Безопасность данных и эксплуатационные регламенты

* **Защита от случайного удаления:** В production-средах держите политику `whenDeleted: Retain`. Даже если администратор по ошибке выполнит `kubectl delete ns` или удалит StatefulSet helm-релизом, физические данные на СХД сохранятся.
* **Резервное копирование:** Никогда не полагайтесь исключительно на локальные диски или механизмы репликации StatefulSet. Регулярно настраивайте автоматизированные снапшоты через Kubernetes VolumeSnapshot API или специализированные операторы баз данных (KubeBlocks, Zalando Postgres Operator, CloudNative-PG, Strimzi).

---

## Дополнительная информация

### См. также

* **[Обзор StatefulSet](./statefulset_overview.md)** — архитектура, поля спецификации и операционные сценарии.
* **[Практическое руководство](./statefulset_practical_guide.md)** — пошаговые манифесты, развертывание MySQL и расширение томов.
* **[StatefulSet: Лучшие практики](./statefulset_best_practices.md)** — расширенный чеклист надежности, мониторинга и эксплуатации.
* **[Сравнение Deployment, StatefulSet и DaemonSet](./statefulset_vs_deployment.md)** — сравнительный анализ и матрица выбора контроллера.
* **[Local PV vs CSI](./statefulset_local_pv_vs_csi.md)** — сравнение типов хранилищ для высоконагруженных СУБД.
* **[Exporter Sidecar](./statefulset_exporter_sidecar.md)** — организация мониторинга реплик через sidecar-контейнеры.
* **[Тип Service — Headless](../../Networking/Service/service_type_headless.md)** — архитектура безадресной DNS-маршрутизации.
* **[StorageClass (Классы хранения)](../../Storage/storageclass.md)** — настройка динамического провижининга и параметров связывания.
* **[PV и PVC](../../Storage/pv_and_pvc.md)** — специфика жизненного цикла томов в Kubernetes.
* **[PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md)** — управление бюджетом добровольных прерываний.
* **[Недоступность узла: Taints и выселение](../../Troubleshooting/Common_Errors/NodeUnavailability/taints_and_eviction.md)** — обработка отказов физических серверов.

---

### Ключевые выводы

1. **Идентичность и привязка к диску:** Главная ценность StatefulSet заключается не просто в запуске подов, а в гарантированном сохранении индивидуальной идентичности (индекс, FQDN в Headless Service) и персонального диска (`volumeClaimTemplates` + Sticky Storage).
2. **Семантика At-Most-One:** При сбое физического сервера StatefulSet сознательно не выполняет автоматический перезапуск пода на новом хосте, защищая данные от разрушительного эффекта Split-Brain. Для восстановления упавшего узла в Kubernetes 1.28+ применяется стандартный протокол `node.kubernetes.io/out-of-service=nodeshutdown:NoExecute`.
3. **Строгая упорядоченность:** По умолчанию (`OrderedReady`) масштабирование и обновления выполняются строго последовательно ($0 \to N-1$ при старте, $N-1 \to 0$ при остановке/обновлении). Следующий под не будет затронут, пока предыдущий не подтвердит статус `Ready`.
4. **Контроль рисков при обновлении:** Для безопасных Canary-релизов в production используется механизм `partition`. Параметр ускорения `maxUnavailable` (Beta v1.35, исправлен в v1.37) требует обязательного учета кворумной формулы и опасен для 3-узловых кластеров.
5. **Автоочистка хранилища:** Начиная с версии v1.32 (GA), механизм `persistentVolumeClaimRetentionPolicy` позволяет автоматизировать удаление освободившихся дисков при масштабировании вниз (`whenScaled: Delete`), устраняя утечки дискового пространства на СХД.