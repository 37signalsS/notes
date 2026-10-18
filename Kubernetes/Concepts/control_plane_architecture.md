# Архитектура Control Plane в Kubernetes

**Актуально для:** Kubernetes 1.32–1.36 (Bare-Metal / On-Premise)

## Определения

*   **Control Plane (Плоскость управления)** — совокупность управляющих компонентов Kubernetes, обеспечивающих глобальное управление кластером, поддержание желаемого состояния (Desired State), регистрацию и обработку событий жизненного цикла рабочих нагрузок, а также планирование и распределение ресурсов.
*   **Data Plane (Плоскость данных / Рабочие узлы)** — инфраструктурный слой кластера (Nodes), на котором исполняются контейнеризированные пользовательские приложения. Включает агент узла (`kubelet`), сетевой прокси (`kube-proxy`) и среду выполнения контейнеров (CRI Runtime, например, `containerd` или `CRI-O`).
*   **etcd** — распределенное, транзакционное хранилище данных типа «ключ-значение» на базе алгоритма консенсуса Raft. Является единственным источником состояния (Single State Store) для всех объектов кластера Kubernetes.
*   **Static Pods (Статические поды)** — поды, жизненный цикл которых управляется демоном `kubelet` напрямую на конкретном узле через чтение локальных манифестов в директории `/etc/kubernetes/manifests/` в обход API-сервера. Используются для начального запуска и саморазвертывания компонентов Control Plane.
*   **Reconciliation Loop (Цикл согласования)** — алгоритмический принцип работы контроллеров Kubernetes: непрерывное сравнение текущего фактического состояния кластера (Actual State) с желаемым состоянием (Desired State), зафиксированным в etcd, и выполнение корректирующих действий при расхождении.
*   **Leader Election (Выбор лидера)** — распределенный механизм координации высокой доступности (HA) на базе объектов `Lease` в пространстве имен `kube-system`. Позволяет запускать несколько реплик компонентов Control Plane (`kube-controller-manager`, `kube-scheduler`) в режиме Active-Standby с мгновенным автоматическим переключением при сбое активного процесса.
*   **API Priority and Fairness (APF)** — встроенная подсистема `kube-apiserver`, заменяющая грубые лимиты `max-requests-inflight` на интеллектуальное управление очередями запросов через классификацию по потокам (`FlowSchema`) и распределение долей пропускной способности (`PriorityLevelConfiguration`).
*   **Admission Controllers (Контроллеры допуска)** — плагины конвейера `kube-apiserver`, перехватывающие запросы к API после успешной аутентификации и авторизации, но до сохранения объекта в etcd, с целью модификации (mutating) или валидации (validating).
*   **Structured Authentication / Authorization** — механизм декларативного конфигурирования нескольких провайдеров аутентификации (OIDC/JWT, Webhook) и авторизации через конфигурационные файлы без необходимости перезапуска процессов API-сервера.

---

## Архитектура и принципы работы

### Компонентная модель Control Plane на Bare-Metal

В отличие от сред публичных облаков, где плоскость управления предоставляется как черный ящик с облачным контроллером (`cloud-controller-manager`), в On-Premise и Bare-Metal инфраструктуре вся ответственность за стабильность, резервирование и изоляцию Control Plane лежит на системных инженерах и SRE.

Архитектура Control Plane строится по модели **звезды (Hub-and-Spoke)**, где центральным узлом является `kube-apiserver`. Все компоненты системы взаимодействуют исключительно через API-сервер по протоколу HTTPS с двусторонней аутентификацией (mTLS):

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              CONTROL PLANE (On-Premise / Bare-Metal)                   │
│                                                                                        │
│   [ L4 Load Balancer: VIP (kube-vip / Keepalived) + Proxy (HAProxy / BGP ECMP) ]       │
│                                           │ :6443 (HTTPS / mTLS)                       │
│                                           ▼                                            │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                                 kube-apiserver                                 │   │
│   │     (Stateless, горизонтально масштабируемый REST/gRPC API-концентратор)       │   │
│   └──────┬──────────────────┬──────────────────────────┬────────────────────┬──────┘   │
│          │ :2379            │ HTTP/2 Watch             │ HTTP/2 Watch       │          │
│          ▼ (mTLS)           ▼                          ▼                    │          │
│   ┌──────────────┐   ┌──────────────┐           ┌──────────────┐            │          │
│   │     etcd     │   │kube-scheduler│           │kube-control- │            │          │
│   │ (Stateful,   │   │(Active-      │           │ler-manager   │            │          │
│   │ Raft Quorum) │   │ Standby)     │           │(Active-      │            │          │
│   └──────────────┘   └──────────────┘           │ Standby)     │            │          │
│                                                 └──────────────┘            │          │
└─────────────────────────────────────────────────────────────────────────────┼──────────┘
                                                                              │
                                                     :10250 (mTLS)            │ :6443 (mTLS)
                                        ┌─────────────────────────────────────┴──────────┐
                                        │                                                │
                                        ▼                                                ▼
                         ┌─────────────────────────────┐                  ┌─────────────────────────────┐
                         │   Worker Node 1 (kubelet)   │                  │   Worker Node 2 (kubelet)   │
                         └─────────────────────────────┘                  └─────────────────────────────┘
```

#### Ключевые архитектурные правила взаимодействия:
1.  **Прямой доступ к etcd имеет ТОЛЬКО `kube-apiserver`**. Ни один другой компонент (ни планировщик, ни контроллеры, ни узловые демоны) не имеет доступа к порту 2379 etcd и сертификатам базы данных.
2.  **Компоненты Control Plane не общаются между собой напрямую**. Планировщик не передает команды диспетчеру контроллеров, а контроллеры не вызывают напрямую `kubelet`. Все взаимодействие построено на концепции подписки на события (**Watch**) через `kube-apiserver`.
3.  **Изоляция Data Plane**. Входящие соединения от `kube-apiserver` к `kubelet` (порт 10250) требуются только для операций `kubectl logs`, `kubectl exec`, `kubectl attach` и вызова проксирования портов. В штатном режиме рабочий узел сам отправляет исходящие запросы в сторону API-сервера.

---

### Детальный разбор компонентов Control Plane

#### 1. kube-apiserver
Центральный интерфейс и масштабируемый REST-шлюз кластера.
*   **Stateless-природа**: сам по себе API-сервер не хранит никакого состояния на диске. Это позволяет запускать любое количество параллельных инстансов за балансировщиком нагрузки.
*   **Функции**: аутентификация клиентов, авторизация прав доступа, схемная проверка спецификаций ресурсов, валидация и мутация через контроллеры допуска, сериализация данных в формат etcd и организация потоковой рассылки изменений подписчикам (Informer/Reflector).
*   **Сетевое взаимодействие**: слушает порт `6443/TCP`. Использует протокол HTTP/2, мультиплексируя сотни параллельных соединений и потоков Watch в рамках одного TCP-сокета.

#### 2. etcd
Высоконадежное согласованное хранилище на базе алгоритма Raft.
*   **Кворум и размер кластера**: для устойчивости к разделению сети и сбоям узлов etcd развертывается в нечетном количестве реплик ($N = 2F + 1$, где $F$ — допустимое число отказавших узлов):
    *   3 узла: переносит отказ 1 узла (кворум = 2).
    *   5 узлов: переносит отказ 2 узлов (кворум = 3).
*   **Критичность задержки дискового ввода-вывода (fsync)**: etcd синхронно сбрасывает журнал транзакций (WAL) на диск перед подтверждением операции записи лидеру. Если задержка `fsync` превышает 10–15 мс, начинаются сбои сердцебиения Raft, потеря лидера и каскадная деградация API-сервера.
*   **Модель данных**: Multi-Version Concurrency Control (MVCC). Объекты не перезаписываются на месте — каждая модификация создает новую ревизию с инкрементом `resourceVersion`. Старые версии удаляются только при периодической процедуре компактизации (Compaction).

#### 3. kube-scheduler
Компонент, отвечающий за интеллектуальное распределение подов по узлам кластера.
*   **Специфика работы**: планировщик отслеживает через Watch появление подов, у которых поле `spec.nodeName` не заполнено.
*   **Scheduling Framework**: процесс планирования разбит на два последовательных цикла:
    1.  *Scheduling Cycle* (однопоточный, последовательный): фазы Pre-Filter, Filter (отсев узлов по Predicates: taints/tolerations, доступность CPU/RAM, affinity, топология томов), Pre-Score, Score (ранжирование узлов плагинами с весовыми коэффициентами) и Reserve.
    2.  *Binding Cycle* (асинхронный, многопоточный): фазы Permit, Pre-Bind, Bind (запись выбранного узла в поле `spec.nodeName` пода через API-сервер) и Post-Bind.
*   Подробный разбор алгоритмов планировщика вынесен в специализированный документ **[Kube-scheduler: планировщик подов](./kube_scheduler.md)**.

#### 4. kube-controller-manager (KCM)
Единый бинарный процесс, объединяющий множество независимых циклов управления (Controllers).
*   **Принцип Reconciliation**: контроллеры не полагаются на идеальную доставку событий. Каждый контроллер периодически опрашивает локальный кэш и устраняет дельту между состоянием в etcd и реальным миром.
*   **Ключевые встроенные контроллеры**:
    *   `Node Lifecycle Controller`: отслеживает аренду узлов (`kube-node-lease`), переводит узлы в статус `NotReady` при пропадании heartbeat и управляет эвикцией подов через выставление taints (`node.kubernetes.io/unreachable`).
    *   `ReplicationController / ReplicaSet / Deployment Controller`: управляют жизненным циклом и репликацией подов.
    *   `EndpointSlice Controller`: отслеживает изменения подов и формирует списки IP-адресов эндпоинтов для сервисов.
    *   `ServiceAccount Controller & TokenCleaner`: создает системные токены и управляет пространствами имен.
    *   `PersistentVolume Controller`: связывает запросы PVC с томами PV и взаимодействует с CSI-драйверами на Bare-Metal.

#### 5. Роль Cloud Controller Manager (CCM) в On-Premise инфраструктуре
В bare-metal кластерах классический `cloud-controller-manager` **не используется** либо заменяется специализированными on-premise реализациями. Традиционные облачные задачи (выделение внешних IP через `Type=LoadBalancer`, управление маршрутизацией между узлами и подключение внешних дисковых полок) решаются нативными bare-metal инструментами:
*   Балансировка сервисов: **MetalLB** (Layer 2 / BGP) или встроенные возможности **Cilium BGP Control Plane**.
*   Хранилище: CSI-драйверы для локальных дисков (LVM-LocalPV, OpenEBS) или распределенных хранилищ (Ceph RBD/CephFS, Rook-Ceph).
*   Управление маршрутами узлов: протоколы динамической маршрутизации (BGP через FRR / Bird / Calico / Cilium).

---

### Механизм саморазвертывания: Static Pods

В типовых bare-metal инсталляциях (`kubeadm`, `kubespray`) возникает фундаментальная проблема: как запустить контейнеры Control Plane (`kube-apiserver`, `etcd`, `kube-controller-manager`, `kube-scheduler`), если самого API-сервера и планировщика еще не существует?

Решением является архитектурный механизм **Static Pods**:

```text
/etc/kubernetes/manifests/
  ├── kube-apiserver.yaml
  ├── kube-controller-manager.yaml
  ├── kube-scheduler.yaml
  └── etcd.yaml
         │
         ▼ (локальный inotify мониторинг директории)
   ┌───────────┐       CRI gRPC       ┌───────────────────┐
   │  kubelet  │ ───────────────────► │ containerd/CRI-O  │ ──► Запуск контейнеров
   └─────┬─────┘                      └───────────────────┘
         │
         ▼ (после старта kube-apiserver)
  Регистрация Mirror Pods в API (read-only проекция в namespace kube-system)
```

#### Особенности функционирования Static Pods:
1.  **Прямое управление от `kubelet`**: демон `kubelet` на мастер-узле сканирует директорию (по умолчанию `/etc/kubernetes/manifests/`). При появлении или модификации YAML-файла `kubelet` напрямую вызывает CRI рантайм (`containerd`) и запускает контейнеры.
2.  **Автономный перезапуск**: если процесс `kube-apiserver` или `etcd` завершается аварийно, `kubelet` самостоятельно перезапускает контейнер на узле без участия планировщика или контроллеров.
3.  **Mirror Pods**: после того как `kube-apiserver` успешно стартует, `kubelet` создает в пространстве имен `kube-system` зеркальные объекты подов (Mirror Pods). Они отображаются в `kubectl get pods -n kube-system`, но являются строго **read-only**: попытка удалить mirror pod через `kubectl delete pod` приводит лишь к его повторному созданию `kubelet`. Для реального изменения параметров необходимо редактировать манифест на диске хоста.
4.  **Иммунитет к `kubectl drain`**: статические поды не вытесняются при переводе узла в режим обслуживания.

---

### Топологии размещения etcd: Stacked vs External

При проектировании On-Premise инфраструктуры выбор топологии размещения базы данных etcd определяет отказоустойчивость и требования к ресурсам:

```text
ВАРИАНТ 1: Stacked etcd (Совмещенный)         ВАРИАНТ 2: External etcd (Выделенный)

  Master Node 1      Master Node 2             Master Node 1     Master Node 2
┌──────────────┐   ┌──────────────┐          ┌─────────────┐   ┌─────────────┐
│kube-apiserver│   │kube-apiserver│          │kube-apiserv.│   │kube-apiserv.│
├──────────────┤   ├──────────────┤          └──────┬──────┘   └──────┬──────┘
│  etcd (pod)  │   │  etcd (pod)  │                 │   :2379 mTLS        │
└──────┬───────┘   └──────┬───────┘                 ▼                 ▼
       │   Raft Peering   │                  ┌─────────────┐   ┌─────────────┐
       └──────────────────┘                  │ etcd Node 1 │   │ etcd Node 2 │
                                             └──────┬──────┘   └──────┬──────┘
                                                    │   Raft Peering  │
                                                    └─────────────────┘
```

| Критерий | Stacked etcd (Совмещенный) | External etcd (Выделенный) |
| :--- | :--- | :--- |
| **Количество серверов** | Минимум 3 мастер-узла | 3 мастера Control Plane + 3 сервера etcd (всего 6) |
| **Изоляция ресурсов** | Конкуренция за CPU, RAM и дисковый ввод-вывод между API и etcd | Полная аппаратная изоляция базы данных от API-нагрузки |
| **Влияние отказа хоста** | Падение узла выбивает одновременно реплику API и член кворума etcd | Отказ мастера API не влияет на размер кворума etcd |
| **Сложность эксплуатации** | Автоматизировано в `kubeadm init --control-plane` | Требует отдельного управления PKI-сертификатами и сетью |
| **Область применения** | Кластеры до 200–300 узлов со стандартной нагрузкой | Высоконагруженные кластеры (>300 узлов, интенсивный CI/CD) |

---

### Обеспечение отказоустойчивости (HA) Control Plane

Для обеспечения непрерывной доступности управляющего слоя на Bare-Metal используются два механизма:

#### 1. Балансировка трафика к `kube-apiserver` (Active-Active)
Так как все инстансы `kube-apiserver` работают в режиме Stateless, внешние клиенты (`kubectl`, рабочие узлы, контроллеры) должны обращаться к единому адресу (Virtual IP / DNS Name).
*   **kube-vip** (рекомендуемый современный стандарт): запускается как Static Pod или daemonset, поднимает виртуальный IP (VIP) через ARP в L2-сегменте либо анонсирует адрес Control Plane по протоколу BGP (ECMP) на физические коммутаторы ToR.
*   **Keepalived + HAProxy**: классическая связка. Keepalived управляет VIP через протокол VRRP, а локальный экземпляр HAProxy распределяет TCP-трафик порта 6443 между всеми доступными мастер-узлами с проверкой эндпоинта `/readyz`.
*   Подробное руководство по развертыванию отказоустойчивой схемы представлено в **[Высокая доступность в Kubernetes](../Base/high_availability.md)**.

#### 2. Координация лидерства (Active-Standby)
Компоненты `kube-controller-manager` и `kube-scheduler` изменяют состояние кластера, поэтому одновременная работа нескольких активных экземпляров привела бы к состоянию гонки (Race Condition).
*   В кластере запускается несколько реплик компонентов (по одной на каждом мастере Control Plane).
*   С помощью механизма **Leader Election** процессы конкурируют за объект `Lease` в пространстве имен `kube-system` (`kube-controller-manager` и `kube-scheduler`).
*   Только процесс, удерживающий блокировку (Lock Holder), выполняет рабочие циклы. Если текущий лидер перестает обновлять поле `renewTime` в течение интервала аренды (по умолчанию 15 секунд), запасной процесс на соседнем мастере перехватывает лидерство.

---

### Конвейер обработки запросов в `kube-apiserver` (Handler Pipeline)

Каждый HTTP-запрос, поступающий в `kube-apiserver`, проходит через строгий многоступенчатый конвейер:

```text
HTTP Request
     │
     ▼
┌────────────────────────────────────────────────────────┐
│ 1. TLS Termination & Аутентификация (Authentication)   │ ──► Не опознан? 401 Unauthorized
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ 2. Авторизация (Authorization: Node, RBAC, Webhook)    │ ──► Нет прав? 403 Forbidden
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ 3. API Priority and Fairness (APF: Flow & Queuing)     │ ──► Перегрузка? 429 Too Many Requests
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ 4. Мутирующий допуск (Mutating Admission Webhooks)     │ ──► Модификация объекта (sidecars, defaults)
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ 5. Схемная валидация (Schema Validation)               │ ──► Ошибка схемы OpenAPI? 422 Unprocessable
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ 6. Валидирующий допуск (Validating Webhooks / CEL)     │ ──► Нарушение политик? 403 Forbidden
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ 7. Сохранение в etcd (Serialization & MVCC Commit)     │ ──► Конфликт версии? 409 Conflict
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ 8. Оповещение подписчиков (Watch Notification)         │ ──► Рассылка событий в Informers
└────────────────────────────────────────────────────────┘
```

1.  **Аутентификация**: определение субъекта запроса (`User`, `Group`, `ServiceAccount`). Методы: x509 клиентские сертификаты, токены ServiceAccount, Webhook Token Authenticator или Structured Authentication Config. При неудаче возвращается `401 Unauthorized`.
2.  **Авторизация**: проверка разрешений субъекта на выполнение действия (`verb`: get, list, create, update, delete) над ресурсом в целевом namespace. Стандартный режим — комбинация `Node,RBAC`. При отказе возвращается `403 Forbidden`.
3.  **API Priority and Fairness (APF)**: фильтрация и приоритизация. Тяжелые запросы классифицируются по очередям, предотвращая зависание критического системного трафика.
4.  **Mutating Admission**: изменение тела запроса до валидации. Используется для автоматической инъекции init-контейнеров, sidecars, переменных окружения или монтирования томов с секретами.
5.  **Schema Validation**: проверка структуры манифеста на соответствие типам данных OpenAPI v3 схемы Kubernetes.
6.  **Validating Admission**: финальная проверка соблюдения политик. Выполняется через внешние вебхуки либо через нативный внутрипроцессный движок **ValidatingAdmissionPolicy** на языке CEL (Common Expression Language). Подробнее: **[Контроллеры допуска (Admission Controllers)](./admission_controllers.md)**.
7.  **Фиксация в etcd**: объект кодируется в Protobuf/JSON, генерируется новая транзакция в Raft, инкрементируется `resourceVersion`, и запись фиксируется на диск.
8.  **Watch Notification**: API-сервер через открытые HTTP/2 потоки мгновенно уведомляет всех заинтересованных клиентов (контроллеры, kubelet, внешние операторы), подписанных на данный ресурс.

---

## Практические сценарии и конфигурация

### 1. Аппаратные требования и сайзинг Control Plane (Bare-Metal)

| Размер кластера (узлы) | CPU Control Plane | RAM Control Plane | Дисковая подсистема etcd | Сеть Control Plane |
| :--- | :--- | :--- | :--- | :--- |
| **До 20 узлов** | 4 ядра | 8–16 GiB | Enterprise SATA SSD / NVMe | 1 Gbps |
| **20 – 100 узлов** | 8 ядер | 16–32 GiB | Выделенный NVMe (fsync < 5 мс) | 10 Gbps (отдельный VLAN) |
| **100 – 500 узлов** | 16 ядер | 32–64 GiB | Выделенный enterprise NVMe (PCIe 4.0) | 10–25 Gbps LACP |
| **> 500 узлов (HA)** | 32+ ядра | 64–128 GiB | External etcd на отдельных серверах с NVMe | 25+ Gbps с резервированием |

---

### 2. Анализ конфигурационных манифестов Static Pods

Манифесты компонентов Control Plane располагаются на каждом мастер-узле в `/etc/kubernetes/manifests/`. Любое изменение файла немедленно применяется демоном `kubelet`.

#### Манифест `kube-apiserver.yaml` (ключевые флаги промышленной эксплуатации)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: kube-apiserver
  namespace: kube-system
  labels:
    component: kube-apiserver
    tier: control-plane
spec:
  hostNetwork: true
  priorityClassName: system-node-critical
  containers:
  - name: kube-apiserver
    image: registry.k8s.io/kube-apiserver:v1.36.2
    command:
    - kube-apiserver
    # Сетевые привязки и порты
    - --advertise-address=192.168.10.11
    - --secure-port=6443
    - --anonymous-auth=false
    # Авторизация и аутентификация
    - --authorization-mode=Node,RBAC
    - --client-ca-file=/etc/kubernetes/pki/ca.crt
    - --service-account-key-file=/etc/kubernetes/pki/sa.pub
    - --service-account-signing-key-file=/etc/kubernetes/pki/sa.key
    - --service-account-issuer=https://kubernetes.default.svc.cluster.local
    # Подключение к распределенной базе данных etcd (mTLS)
    - --etcd-servers=https://192.168.10.11:2379,https://192.168.10.12:2379,https://192.168.10.13:2379
    - --etcd-cafile=/etc/kubernetes/pki/etcd/ca.crt
    - --etcd-certfile=/etc/kubernetes/pki/apiserver-etcd-client.crt
    - --etcd-keyfile=/etc/kubernetes/pki/apiserver-etcd-client.key
    # Диапазоны адресов кластера
    - --service-cluster-ip-range=10.96.0.0/12
    # Аудит-логирование безопасности
    - --audit-log-path=/var/log/kubernetes/audit.log
    - --audit-log-maxage=30
    - --audit-log-maxbackup=10
    - --audit-log-maxsize=100
    - --audit-policy-file=/etc/kubernetes/audit-policy.yaml
    # Защита от перегрузки (APF)
    - --enable-priority-and-fairness=true
    - --max-requests-inflight=800
    - --max-mutating-requests-inflight=400
    livenessProbe:
      httpGet:
        path: /livez
        port: 6443
        scheme: HTTPS
      initialDelaySeconds: 10
      timeoutSeconds: 15
    readinessProbe:
      httpGet:
        path: /readyz
        port: 6443
        scheme: HTTPS
      timeoutSeconds: 15
```

#### Манифест `kube-controller-manager.yaml`

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: kube-controller-manager
  namespace: kube-system
spec:
  hostNetwork: true
  priorityClassName: system-node-critical
  containers:
  - name: kube-controller-manager
    image: registry.k8s.io/kube-controller-manager:v1.36.2
    command:
    - kube-controller-manager
    - --authentication-kubeconfig=/etc/kubernetes/controller-manager.conf
    - --authorization-kubeconfig=/etc/kubernetes/controller-manager.conf
    - --kubeconfig=/etc/kubernetes/controller-manager.conf
    - --leader-elect=true
    - --leader-elect-lease-duration=15s
    - --leader-elect-renew-deadline=10s
    - --leader-elect-retry-period=2s
    # Контроллеры жизненного цикла узлов и подов
    - --node-monitor-period=5s
    - --node-monitor-grace-period=40s
    - --cluster-cidr=10.244.0.0/16
    - --allocate-node-cidrs=true
    - --service-cluster-ip-range=10.96.0.0/12
    - --root-ca-file=/etc/kubernetes/pki/ca.crt
    - --service-account-private-key-file=/etc/kubernetes/pki/sa.key
    - --use-service-account-credentials=true
```

#### Манифест `kube-scheduler.yaml`

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: kube-scheduler
  namespace: kube-system
spec:
  hostNetwork: true
  priorityClassName: system-node-critical
  containers:
  - name: kube-scheduler
    image: registry.k8s.io/kube-scheduler:v1.36.2
    command:
    - kube-scheduler
    - --authentication-kubeconfig=/etc/kubernetes/scheduler.conf
    - --authorization-kubeconfig=/etc/kubernetes/scheduler.conf
    - --kubeconfig=/etc/kubernetes/scheduler.conf
    - --leader-elect=true
```

---

### 3. Сквозной жизненный цикл развертывания рабочей нагрузки (Pod Creation Flow)

При выполнении команды `kubectl apply -f deployment.yaml` в Control Plane разворачивается следующая последовательность событий:

1.  **Клиент**: `kubectl` формирует HTTP POST-запрос с манифестом Deployment к виртуальному IP балансировщика Control Plane (`https://k8s-api.corp.local:6443`).
2.  **kube-apiserver (AuthN/AuthZ/Admission)**:
    *   Аутентификация клиента по сертификату или токену.
    *   Проверка прав RBAC (`create` на ресурсе `deployments` в группе `apps`).
    *   Мутация: применение дефолтных значений спецификации.
    *   Схемная валидация и проверка ValidatingAdmissionPolicy.
3.  **Сохранение в etcd**: запись объекта Deployment в etcd. API-сервер возвращает клиенту код `201 Created`.
4.  **Deployment Controller**: получив событие по Watch, обнаруживает расхождение между фактическим состоянием (0 реплик) и желаемым (например, 3). Формирует и отправляет в API-сервер запрос на создание объекта `ReplicaSet`.
5.  **ReplicaSet Controller**: реагирует на появление `ReplicaSet` и отправляет три запроса к API-серверу на создание объектов `Pod`. На этом этапе поды создаются со статусом `Pending` и пустым полем `spec.nodeName`.
6.  **kube-scheduler**:
    *   Обнаруживает в Watch поды без назначенного узла (`nodeName == ""`).
    *   Прогоняет каждый под через фазы Filtering (отсев узлов с нехваткой CPU/RAM или неподходящими taints) и Scoring (ранжирование доступных узлов).
    *   Выбирает оптимальный узел и отправляет вызов `Bind` в API-сервер, записывая имя узла в `spec.nodeName`.
7.  **kubelet (на целевом рабочем узле)**:
    *   Через свой постоянный Watch видит, что под назначен на его имя узла.
    *   Отдает команды CRI-рантайму (`containerd`) на подготовку песочницы (Pause container), монтирование томов и запуск основных контейнеров.
    *   CNI-плагин выделяет IP-адрес из диапазона `podCIDR` узла.
8.  **Обновление статуса**: `kubelet` отправляет статус пода (`Running`, IP-адрес) в API-сервер, который сохраняет изменения в etcd.

---

### 4. Жизненный цикл отказа узла (Node Failure Lifecycle)

В bare-metal окружении выход сервера из строя обрабатывается согласованным взаимодействием `kubelet` и контроллеров Control Plane:

```text
  kubelet узла               kube-apiserver              Node Controller
(рабочий узел)               (Control Plane)             (kube-controller-manager)
      │                            │                                 │
      ├── Обновление Lease (2s) ──►│                                 │
      │   (kube-node-lease)        │◄── Мониторинг Lease (5s) ───────┤
      │                            │    (--node-monitor-period)      │
      X [ Сервер выключился ]     │                                 │
                                   │                                 │
                                   │    Прошло 40 секунд             │
                                   │    (--node-monitor-grace-period)│
                                   │◄────────────────────────────────┤
                                   │    Node Controller выставляет   │
                                   │    Ready=Unknown и вешает Taint │
                                   │    node.kubernetes.io/          │
                                   │    unreachable:NoExecute        │
                                   │                                 │
                                   │    Истек tolerationSeconds (300)│
                                   │◄────────────────────────────────┤
                                   │    Вытеснение подов (Eviction). │
                                   │    ReplicaSet создает новые поды│
                                   │    на исправных серверах        │
```

Параметры времени реакции Control Plane настраиваются флагами `kube-controller-manager`:
*   `--node-monitor-period=5s`: частота проверки аренды узлов контроллером.
*   `--node-monitor-grace-period=40s`: интервал времени, по истечении которого не отвечающий узел признается неисправным (`Ready=Unknown`).
*   Значение по умолчанию для `tolerationSeconds` на системных taints `node.kubernetes.io/unreachable` и `node.kubernetes.io/not-ready` составляет 300 секунд (5 минут). Для критичных приложений его уменьшают в `pod.spec.tolerations` до 30–60 секунд.

---

## Сетевые порты Control Plane

| Порт / Протокол | Компонент | Направление | Назначение |
| :--- | :--- | :--- | :--- |
| **6443 / TCP** | `kube-apiserver` | Inbound | Основной защищенный HTTPS API-интерфейс кластера |
| **2379 / TCP** | `etcd` | Inbound | Клиентский порт для запросов от `kube-apiserver` |
| **2380 / TCP** | `etcd` | Inbound | Внутренний пиринг Raft между членами кластера etcd |
| **10250 / TCP** | `kubelet` | Inbound | Управление узлом, передача логов и команд `exec` от API |
| **10257 / TCP** | `kube-controller-manager` | Inbound (Local) | Метрики Prometheus и проверка здоровья (`/healthz`, `/livez`) |
| **10259 / TCP** | `kube-scheduler` | Inbound (Local) | Метрики Prometheus и проверка здоровья (`/healthz`, `/livez`) |

*Примечание: Порты 10257 и 10259 по соображениям безопасности должны быть закрыты межсетевым экраном от внешнего доступа и доступны только локально либо для системы сбора метрик (Prometheus).*

---

## Диагностика и операции

### 1. Проверка состояния компонентов и эндпоинтов здоровья

Историческая команда `kubectl get componentstatuses` (`cs`) является устаревшей (deprecated) и не отражает реальное состояние HA-кластеров. Актуальный метод проверки здоровья Control Plane — опрос эндпоинтов `/livez` и `/readyz` API-сервера:

```bash
# Комплексная проверка готовности API-сервера с подробным выводом компонентов
kubectl get --raw='/readyz?verbose'
# → [runprofilepass] READY
# → [/poststarthook/start-kube-apiserver-admission-initializer] READY
# → [/poststarthook/apiservice-registration-controller] READY
# → [/etcd] READY
# → [/informer-sync] READY
# → readyz check passed

# Проверка живости API-сервера (Liveness)
kubectl get --raw='/livez'
# → ok

# Проверка кластера и базовых сервисов
kubectl cluster-info
# → Kubernetes control plane is running at https://192.168.10.10:6443
# → CoreDNS is running at https://192.168.10.10:6443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
```

### 2. Проверка состояния распределенного хранилища etcd

Выполняется непосредственно на мастер-узле с передачей управляющих mTLS-сертификатов:

```bash
# Проверка доступности и задержки фиксации предложений Raft
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint health
# → https://127.0.0.1:2379 is healthy: committed proposal took 2.145123ms

# Вывод детальной таблицы состояния всех членов etcd кластера
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://192.168.10.11:2379,https://192.168.10.12:2379,https://192.168.10.13:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint status -w table
# → +---------------------------+------------------+---------+---------+-----------+------------+--------------------+--------+
# → |         ENDPOINT          |        ID        | VERSION | DB SIZE | IS LEADER | IS LEARNER | RAFT APPLIED INDEX | ERRORS |
# → +---------------------------+------------------+---------+---------+-----------+------------+--------------------+--------+
# → | https://192.168.10.11:2379| 8e9a3b12c45d6e7f | 3.5.17  |  42 MB  |   true    |   false    |             348912 |        |
# → | https://192.168.10.12:2379| a1b2c3d4e5f60718 | 3.5.17  |  42 MB  |   false   |   false    |             348912 |        |
# → | https://192.168.10.13:2379| f9e8d7c6b5a43210 | 3.5.17  |  42 MB  |   false   |   false    |             348912 |        |
# → +---------------------------+------------------+---------+---------+-----------+------------+--------------------+--------+
```

### 3. Инспекция распределения лидерства (Leader Election)

Проверка активных лидеров для контроллеров и планировщика:

```bash
# Просмотр держателей Lease-блокировок в kube-system
kubectl get lease -n kube-system kube-controller-manager kube-scheduler -o wide
# → NAME                      HOLDER                  AGE   RENEWTIME
# → kube-controller-manager   master-01_8a12bc4f...   45d   1s
# → kube-scheduler            master-02_3f99aa11...   45d   2s
```

### 4. Экстренная диагностика на хосте при неработающем API-сервере

Если `kubectl` не отвечает (`connection refused`), стандартные команды Kubernetes бесполезны. Диагностика выполняется через низкоуровневые утилиты хоста и рантайма контейнеров:

```bash
# 1. Проверка прослушивания сетевых портов процессов
sudo ss -tlnp | grep -E ':(6443|2379|2380|10250|10257|10259)'
# → LISTEN 0 4096 0.0.0.0:6443  0.0.0.0:* users:(("kube-apiserver",pid=15432,fd=7))
# → LISTEN 0 4096 0.0.0.0:2379  0.0.0.0:* users:(("etcd",pid=14201,fd=9))

# 2. Проверка состояния статических контейнеров через crictl
sudo crictl ps -a --name kube-apiserver
# → CONTAINER     IMAGE          CREATED         STATE     NAME             ATTEMPT
# → b3c1894d01aa  registry...    2 minutes ago   Exited    kube-apiserver   5

# 3. Просмотр логов аварийно завершившегося контейнера
sudo crictl logs --tail=100 b3c1894d01aa

# 4. Проверка системного сервиса kubelet
sudo journalctl -u kubelet -n 100 --no-pager
```

### 5. Аудит и ротация сертификатов Control Plane

Сертификаты, сгенерированные утилитой `kubeadm`, действуют 1 год:

```bash
# Проверка срока действия всех сертификатов Control Plane
sudo kubeadm certs check-expiration
# → CERTIFICATE                EXPIRES                  RESIDUAL TIME   CERTIFICATE AUTHORITY
# → admin.conf                 Aug 30, 2027 12:00 UTC   316d            ca
# → apiserver                  Aug 30, 2027 12:00 UTC   316d            ca
# → apiserver-etcd-client      Aug 30, 2027 12:00 UTC   316d            etcd-ca
# → apiserver-kubelet-client   Aug 30, 2027 12:00 UTC   316d            ca
# → etcd-healthcheck-client    Aug 30, 2027 12:00 UTC   316d            etcd-ca
# → etcd-peer                  Aug 30, 2027 12:00 UTC   316d            etcd-ca
# → etcd-server                Aug 30, 2027 12:00 UTC   316d            etcd-ca
# → front-proxy-client         Aug 30, 2027 12:00 UTC   316d            front-proxy-ca

# Ручное продление всех сертификатов
sudo kubeadm certs renew all
# → [certs] Certificate renewed: ca
# → [certs] Certificate renewed: apiserver
# → ...
```
*Важно: после обновления сертификатов необходимо перезапустить статические поды, временно переместив манифесты из `/etc/kubernetes/manifests/` и вернув их обратно через 10 секунд.*

---

## Типовые ошибки и их устранение (Troubleshooting)

### 1. API-сервер падает в CrashLoopBackOff

**Симптомы**: `kubectl` возвращает `The connection to the server was refused - did you specify the right host or port?`. Процесс `kube-apiserver` непрерывно перезапускается.

**Диагностика**:
```bash
# Получить ID упавшего контейнера
sudo crictl ps -a --name kube-apiserver
# Чтение последних строк лога
sudo crictl logs <CONTAINER_ID>
```

**Типичные причины и решения**:
*   **Истек срок действия сертификатов**: в логах ошибка `remote error: tls: bad certificate` или `x509: certificate has expired`.
    *Решение*: выполнить `sudo kubeadm certs renew all`, обновить `/etc/kubernetes/admin.conf` и скопировать его в `~/.kube/config`.
*   **Недоступность etcd**: в логах ошибка `context deadline exceeded` или `connection refused` к адресу 127.0.0.1:2379.
    *Решение*: проверить статус etcd контейнера (`sudo crictl ps --name etcd`), дисковое пространство и права на сертификаты etcd.
*   **Синтаксическая ошибка в YAML-манифесте**: ошибка форматирования или опечатка в новом флаге в файле `/etc/kubernetes/manifests/kube-apiserver.yaml`.
    *Решение*: проверить манифест утилитой `yamllint` или запустить бинарник вручную для валидации: `kube-apiserver --config=... --validate-only`.

---

### 2. Рассинхронизация времени (NTP Drift) и флапанье Leader Election

**Симптомы**: в логах `kube-controller-manager` и `kube-scheduler` появляются сообщения `leaderelection.go: failed to renew lease: lease lost`. Контроллеры постоянно перезапускаются, поды зависают в переходах между состояниями.

**Причина**: расхождение системных часов между мастер-узлами кластера превышает `leaseDurationSeconds` (15 секунд). При перехвате блокировки узел считает, что аренда истекла, что приводит к состоянию гонки за лидерство.

**Диагностика и решение**:
```bash
# Проверка синхронизации времени на всех серверах Control Plane
chronyc tracking
# → Reference ID    : C0A80A01 (ntp.corp.local)
# → Stratum         : 3
# → System time     : 0.000012411 seconds slow of NTP time
# → Last offset     : -0.000004120 seconds
# → RMS offset      : 0.000018742 seconds

# Принудительная синхронизация времени
sudo systemctl restart chronyd
sudo chronyc -a makestep
```

---

### 3. Деградация задержки fsync в etcd и потеря кворума

**Симптомы**: в логах `etcd` сообщения вида `apply request took too long (125.43ms) exceeds warning threshold (100ms)`. API-сервер начинает возвращать клиентам ошибки HTTP 504 Gateway Timeout.

**Причина**: дисковая подсистема хоста перегружена операциями ввода-вывода (IOPS/Bandwidth saturation). Время синхронизации журнала WAL на диск превышает допустимые пороги.

**Диагностика и решение**:
```bash
# Мониторинг задержки дискового ввода-вывода в реальном времени
sudo iostat -x 1 5
# Проверка скорости сброса WAL etcd через метрики Prometheus
# Метрика: etcd_disk_wal_fsync_duration_seconds_bucket
```
*Решение*:
1.  Перенести директорию данных etcd (`/var/lib/etcd`) на выделенный физический NVMe накопитель.
2.  Настроить приоритет ввода-вывода через `ionice`: `sudo ionice -c2 -n0 -p $(pgrep etcd)`.
3.  Исключить совмещение etcd с интенсивными дисковыми нагрузками (тяжелые базы данных, Elasticsearch, Ceph OSD).

---

### 4. Переполнение базы etcd (Alarm: `NOSPACE`)

**Симптомы**: API-сервер отвергает любые операции создания и модификации ресурсов (`Error from server: etcdserver: mvcc: database space exceeded`). Чтение (`get`, `list`) продолжает работать.

**Причина**: размер файла `member/snap/db` превысил установленный лимит `--quota-backend-bytes` (по умолчанию 2 GiB, максимум 8 GiB) из-за отсутствия регулярной дефрагментации после компактизации.

**Процедура восстановления (Disaster Recovery)**:
```bash
# 1. Получить текущую ревизию etcd
REV=$(sudo ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint status --write-out="json" | grep -o '"raftAppliedIndex":[0-9]*' | cut -d: -f2)

# 2. Выполнить принудительную компактизацию старых ревизий
sudo ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  compact $REV
# → compacted checkpoint 348912

# 3. Дефрагментировать базу на всех узлах etcd
sudo ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  defrag
# → Finished defragmenting etcd member[https://127.0.0.1:2379]

# 4. Снять аварийный флаг переполнения
sudo ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  alarm disarm
# → alarm:NOSPACE disarmed
```

---

### 5. Троттлинг клиентских запросов подсистемой APF (HTTP 429)

**Симптомы**: операторы или пользователи получают ошибку `429 Too Many Requests` с сообщением `request rejected by priority and fairness system`.

**Причина**: клиент выполняет частые нефильтрованные запросы `LIST` ко всем пространствам имен без кэширования либо некорректно настроена конфигурация `FlowSchema`.

**Диагностика и устранение**:
```bash
# Просмотр метрик отброшенных запросов подсистемы APF
kubectl get --raw /metrics | grep apiserver_flowcontrol_rejected_requests_total

# Просмотр статуса очередей PriorityLevelConfiguration
kubectl get prioritylevelconfigurations
# → NAME             HANDS-OFF   CONCURRENCY   QUEUED   REJECTED
# → workload-high    false       100           0        0
# → exempt           true        0             0        0
```
Подробная настройка и тюнинг описаны в **[API Priority and Fairness (APF)](./api_priority_and_fairness.md)**.

---

## Рекомендации (Best Practices) для SRE и системных администраторов

### 1. Архитектурная изоляция и надежность
*   **Правило нечетного кворума**: всегда развертывайте Control Plane на 3 или 5 серверах. Развертывание 2 или 4 серверов не увеличивает отказоустойчивость, но повышает вероятность потери кворума.
*   **Изоляция доменов отказа**: распределяйте мастер-узлы по разным серверным стойкам, различным независимым вводам электропитания (PDU/ИБП) и раздельным ToR-коммутаторам.
*   **Выделение ресурсов (Taints)**: мастер-узлы должны иметь taint `node-role.kubernetes.io/control-plane:NoSchedule`, предотвращающий запуск пользовательских нагрузок на управляющих серверах.

### 2. Дисковая подсистема etcd
*   **Выделенные накопители**: используйте отдельные физические NVMe диски под директорию `/var/lib/etcd` с файловой системой `ext4` или `xfs` (с опцией монтирования `noatime`).
*   **Увеличение квоты backend etcd**: для средних и крупных кластеров установите аргумент `--quota-backend-bytes=8589934592` (8 GiB) в манифесте `/etc/kubernetes/manifests/etcd.yaml`.

### 3. Безопасность Control Plane
*   **Отключение анонимного доступа**: флаг `--anonymous-auth=false` в `kube-apiserver` предотвращает неавторизованные зондирования API.
*   **Шифрование данных в покое (Encryption at Rest)**: настройте шифрование объектов Secret в etcd с использованием провайдера `aescbc` или `kms` через флаг `--encryption-provider-config`.
*   **Изоляция сетевого периметра**: порты 2379, 2380, 10257, 10259 должны быть закрыты на уровне хостового фаервола (`nftables` / `iptables`) и доступны строго для авторизованных IP-адресов Control Plane и серверов мониторинга.

### 4. Мониторинг и эксплуатация
*   **Ключевые метрики SLI/SLO**:
    *   `apiserver_request_duration_seconds`: P99 задержка ответов API должна быть < 1 секунды для мутирующих запросов.
    *   `etcd_disk_wal_fsync_duration_seconds`: задержка сброса WAL на диск должна стабильно держаться < 10 мс.
    *   `etcd_server_has_leader`: флаг наличия лидера в кластере (алерт критического приоритета при `0`).
*   **Регулярное резервное копирование**: настройте автоматическое создание снапшотов etcd каждые 1–4 часа скриптом через `cron`/`systemd-timer` с выгрузкой снапшотов на независимый сервер резервного копирования.

---

## Дополнительная информация

*   **[Высокая доступность в Kubernetes](../Base/high_availability.md)** — архитектура HA-кластеров, L4 балансировка, VRRP и BGP.
*   **[API Priority and Fairness (APF)](./api_priority_and_fairness.md)** — углубленный разбор FlowSchema и PriorityLevelConfiguration.
*   **[Обзор etcd](./etcd_overview.md)** — внутреннее устройство распределенного хранилища, MVCC и Raft.
*   **[Операции и обслуживание etcd](./etcd_operations.md)** — практические процедуры резервного копирования, дефрагментации и восстановления.
*   **[Контроллеры допуска (Admission Controllers)](./admission_controllers.md)** — вебхуки валидации/мутации и политики CEL.
*   **[Kube-scheduler: планировщик подов](./kube_scheduler.md)** — алгоритмы фильтрации, скоринга и плагины планирования.
*   **[Kubelet — агент рабочего узла](./kubelet.md)** — взаимодействие узлового агента с плоскостью управления.
*   **[Взаимодействие с API Kubernetes](./api_interaction.md)** — специфика работы клиентов с REST API.
