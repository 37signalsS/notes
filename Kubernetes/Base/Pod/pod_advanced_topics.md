# Продвинутые темы Pod в Kubernetes

**Актуально для:** Kubernetes 1.30–1.35+

Документ охватывает архитектурные механизмы и параметры спецификации Pod (`PodSpec`), выходящие за рамки базового развертывания контейнеров: управление жизненным циклом и мутацией спецификации, расширенные шлюзы готовности и планирования (`Readiness Gates`, `Scheduling Gates`), изоляцию сред выполнения (`RuntimeClass`) с учетом накладных расходов (`Pod Overhead`), разделение пространств имен процессов (`shareProcessNamespace`), тонкую настройку сетевого резолва и диагностику аварийных завершений. Является единым источником правды (SSoT) для DevOps-инженеров, SRE и системных администраторов при проектировании отказоустойчивых on-premise и bare-metal инсталляций.

---

## Определения

* **Неизменяемые поля (Immutable fields)** — поля спецификации Pod (`PodSpec`), значение которых валидатор Kube-API-Server запрещает модифицировать после первичного создания объекта в etcd (например, `spec.containers[*].command`, `spec.volumes`, `spec.nodeName`).
* **Мутируемые поля (Mutable fields)** — строго ограниченный перечень полей PodSpec, допускающих изменение в работающем объекте: образы (`spec.containers[*].image`, `spec.initContainers[*].image`), лимит времени (`spec.activeDeadlineSeconds`), добавление исключений (`spec.tolerations`), ресурсы (`spec.containers[*].resources` через подресурс `/resize` в Kubernetes 1.33+ Beta / 1.35+ GA) и подключение отладочных контейнеров (`spec.ephemeralContainers` через `/ephemeralcontainers`).
* **Врата готовности (Readiness Gates)** — механизм расширения стандартных проверок доступности Pod (`spec.readinessGates`). Позволяет внешним контроллерам (Ingress, Service Mesh, операторам канареечных релизов) удерживать условие `Ready: False`, предотвращая попадание трафика и преждевременную утилизацию старых реплик до завершения прогрева внешней инфраструктуры.
* **Врата планирования (Scheduling Gates)** — механизм ядра Kubernetes (GA с версии 1.30), позволяющий заблокировать постановку Pod на узел (`spec.schedulingGates[*].name`) до выполнения внешних предусловий (выделение аппаратных квот, подготовка хранилища, динамический аудит безопасности), не нагружая цикл вычислений `kube-scheduler`.
* **Оверхед пода (Pod Overhead)** — фиксированное количество процессорного времени и оперативной памяти (`spec.overhead.podFixed` в `RuntimeClass`), которое резервируется планировщиком и Pod cgroup для функционирования гипервизора или ядра изоляции (Kata Containers, gVisor) сверх лимитов пользовательских контейнеров.
* **shareProcessNamespace** — параметр спецификации (`spec.shareProcessNamespace: true`), активирующий общее пространство имен процессов (PID Namespace) для всех контейнеров внутри одного Pod. Назначает инфраструктурный `pause`-контейнер процессом PID 1 (сборщиком зомби) и открывает видимость чужих процессов через файловую систему `/proc`.
* **setHostnameAsFQDN** — булев флаг спецификации Pod (GA с v1.22), форсирующий назначение полного доменного имени (FQDN вида `<hostname>.<subdomain>.<namespace>.svc.<cluster-domain>`) в качестве системного имени хоста (kernel hostname) внутри контейнеров.
* **terminationMessagePolicy** — директива контейнера, регламентирующая источник формирования статусных данных об аварийном завершении (`status.containerStatuses[*].lastState.terminated.message`): чтение локального файла (`File`, по умолчанию `/dev/termination-log`) либо аварийный перехват хвоста консольного вывода (`FallbackToLogsOnError`).

---

## Архитектура и принципы работы

### 1. Жизненный цикл изменений спецификации (Mutable vs Immutable)

Большинство параметров Pod в Kubernetes являются неизменяемыми (`immutable`). Это архитектурное ограничение обусловлено тем, что контейнерный рантайм (CRI) создает изолированные пространства имен Linux и структуры cgroups однократно при инициализации Pod Sandbox.

```
                           ┌─────────────────────────────┐
                           │   PATCH / PUT к PodSpec     │
                           └──────────────┬──────────────┘
                                          │
                         Валидация Kube-API-Server
                                          │
                   ┌──────────────────────┴──────────────────────┐
                   ▼                                             ▼
           Мутируемое поле?                             Неизменяемое поле?
                   │                                             │
      ┌────────────┴────────────┐                                ▼
      │                         │                    HTTP 422 Unprocessable Entity
      ▼                         ▼                    "field is immutable"
Прямой PATCH             Подресурс API                           │
- image                  - /resize (resources)                   ▼
- activeDeadlineSeconds  - /ephemeralcontainers     Требуется пересоздание Pod
- tolerations (добавление)                          (RollingUpdate / Delete)
```

#### Доступные для модификации поля

| Поле PodSpec | Механизм применения | Поведение рантайма и Kubelet |
| :--- | :--- | :--- |
| `spec.containers[*].image` | Прямой PATCH к Pod | Kubelet останавливает старый контейнер по graceful shutdown и запускает новый с новым образом (перезапуск контейнера, песочница Pod сохраняется). |
| `spec.initContainers[*].image` | Прямой PATCH к Pod | Допускается API, но если init-контейнеры уже успешно завершились, перезапуск не инициируется. |
| `spec.activeDeadlineSeconds` | Прямой PATCH к Pod | Допускается установка значения или его уменьшение. При превышении лимита Kubelet переводит Pod в фазу `Failed` с причиной `DeadlineExceeded`. |
| `spec.tolerations` | Прямой PATCH к Pod | Разрешено **только добавление** новых tolerations. Удаление или модификация существующих запрещены. |
| `spec.containers[*].resources` | Подресурс `/resize` | В Kubernetes 1.33+ (Beta) / 1.35+ (GA) доступна мутация CPU и Memory без перезапуска при политике `RestartNotRequired` (см. [In-Place Pod Resize](../../Autoscaling/in_place_pod_resize.md)). |
| `spec.ephemeralContainers` | Подресурс `/ephemeralcontainers` | Добавление временных отладочных контейнеров без перезапуска рабочих процессов (см. [Эфемерные контейнеры](./ephemeral_containers.md)). |

#### Критически важные неизменяемые поля

Попытка изменения следующих полей через прямой `kubectl edit`, `patch` или `replace` завершается ошибкой валидации API-сервера `Invalid value: ... field is immutable`:
* `spec.containers[*].command` и `spec.containers[*].args` — определяют инициализацию процесса при старте ядра контейнера.
* `spec.containers[*].ports` — привязка портов транслируется в сетевой стек CNI.
* `spec.containers[*].env` — переменные окружения инжектируются в дескриптор процесса при вызове `execve` рантаймом.
* `spec.volumes` и `spec.containers[*].volumeMounts` — точки монтирования связываются в mount namespace контейнера.
* `spec.nodeName` — после завершения фазы биндинга планировщиком привязка Pod к узлу необратима.

---

### 2. Врата готовности (Readiness Gates)

По умолчанию Pod считается готовым к обслуживанию пользовательского трафика (`status.conditions[Type=Ready].status == True`), если все контейнеры в `spec.containers` успешно прошли свои `readinessProbe`. Однако в распределенных системах готовность локального порта внутри контейнера не гарантирует, что сетевая инфраструктура готова передавать трафик.

```
[ Pod запущен ] ──► [ readinessProbe: OK ] ──► [ ContainersReady: True ]
                                                        │
                      ┌─────────────────────────────────┴─────────────────────────────────┐
                      │                                                                   │
               Readiness Gates нет                                                Readiness Gates заданы
                      │                                                                   │
                      ▼                                                                   ▼
               [ Ready: True ]                                              Ожидание внешнего контроллера
                      │                                                                   │
             Трафик подается в Service                                   Условие gate установлено в True?
                                                                                   ├── НЕТ ──► [ Ready: False ]
                                                                                   │          (трафик не идет,
                                                                                   │           старый Pod жив)
                                                                                   └── ДА  ──► [ Ready: True ]
                                                                                              (трафик разрешен)
```

#### Логика вычисления статуса Pod Ready

Формула готовности Pod при наличии `readinessGates`:

$$\text{PodReady} = \text{ContainersReady} \land \bigwedge_{i=1}^{n} (\text{Condition}(\text{Gate}_i) == \text{True})$$

Если внешний контроллер еще не выставил статус условия или установил его в `False`, общий статус Pod остается `Ready: False` с причиной `ReadinessGatesNotReady`.

#### Значение для SRE и Zero-Downtime деплоев
При проведении Rolling Update без `readinessGates` возможна потеря пакетов (HTTP 502/503):
1. Новый контейнер стартует и отвечает 200 OK на локальный HTTP `/healthz`.
2. Kubelet немедленно рапортует `Ready: True`.
3. Deployment-контроллер считает шаг развертывания успешным и отправляет `SIGTERM` подам предыдущей версии.
4. В этот момент внешний Ingress-контроллер (или аппаратный балансировщик) еще не успел зарегистрировать IP-адрес нового пода в апстрим-пуле или синхронизировать BGP/eBPF таблицы.
5. Трафик продолжает поступать на удаляемые старые поды либо сбрасывается.

Использование `readinessGates` блокирует шаг ротации в Deployment до тех пор, пока контроллер балансировки явно не подтвердит готовность датаплейна через PATCH подресурса `/status`.

---

### 3. Врата планирования (Scheduling Gates)

Механизм Scheduling Gates (GA с версии 1.30) позволяет удерживать Pod в статусе `Pending` (состояние `SchedulingGated`), полностью исключая его из вычислительного цикла планировщика `kube-scheduler`.

```
                  Создание Pod (spec.schedulingGates: [quota-gate])
                                       │
                                       ▼
                       Очередь kube-scheduler (SchedulingQueue)
                                       │
                         Проверка spec.schedulingGates
                                       │
                    ┌──────────────────┴──────────────────┐
                 Не пусто                               Пусто
                    │                                     │
                    ▼                                     ▼
        Перемещение в пул "gated"                Стандартный цикл планирования:
      (Планировщик игнорирует Pod)               1. Pre-filter / Filter
                    │                            2. Pre-score / Score
        Внешний контроллер проверил              3. Reserve / Permit
         квоту и удалил ворота                   4. Pre-bind / Bind к Node
                    │                                     ▲
                    └─────────── Событие Pod Update ──────┘
```

#### Схема данных в PodSpec
В спецификации ядра Kubernetes `PodSchedulingGate` содержит только строковое имя ворот (`name`):

```yaml
spec:
  schedulingGates:
  - name: "infrastructure.internal/quota-validated"
  - name: "security.internal/image-scanned"
```

> [!IMPORTANT]
> В поле `schedulingGates` недопустимы параметры `apiGroup` или вложенные объекты. Массив принимает исключительно объекты вида `{"name": "<gate-name>"}`.

#### Отличие Scheduling Gates от смежных механизмов

| Механизм | На каком этапе действует | Влияние на Control Plane | Возможность гибкого снятия |
| :--- | :--- | :--- | :--- |
| **Mutating Admission Webhook** | Прием запроса API-сервером | Задерживает HTTP-сессию API, падает по таймауту при долгих операциях | Нет (работает синхронно в момент вызова API) |
| **Scheduling Gates** | До вызова алгоритма планирования | **Нулевое**: исключает холостые попытки `kube-scheduler` перебирать узлы | Да: асинхронный контроллер снимает gate в любой момент |
| **Node Taints / Tolerations** | Стадия фильтрации (Filter) | Нагружает планировщик вычислениями для каждого узла кластера | Требует изменения конфигурации узла или спецификации Pod |
| **Readiness Gates** | После размещения на узле (Kubelet) | Узел уже занят, ресурсы (Requests) зарезервированы | Управляет только трафиком, не освобождает узел |

---

### 4. Изоляция рантайма и Pod Overhead

Стандартный контейнерный рантайм `runc` обеспечивает изоляцию за счет пространств имен ядра Linux (namespaces) и контрольных групп (cgroups). Это означает общее монолитное ядро хоста: уязвимость ядра (kernel panic или escape) затрагивает все рабочие нагрузки узла.

Для изоляции недоверенного кода, мультитенантных окружений и соблюдения регламентов безопасности (PCI-DSS) применяются специализированные среды изоляции, подключаемые через `RuntimeClass`.

```
  Стандартный Pod (runc)           gVisor (runsc)                Kata Containers
┌─────────────────────────┐   ┌─────────────────────────┐   ┌─────────────────────────┐
│  App Container          │   │  App Container          │   │  App Container          │
├─────────────────────────┤   ├─────────────────────────┤   ├─────────────────────────┤
│  Namespaces / Cgroups   │   │  Sentry (Guest Kernel)  │   │  Guest Kernel (Linux)   │
├─────────────────────────┤   ├─────────────────────────┤   ├─────────────────────────┤
│  Общее ядро узла (Host) │   │  Gofer / runsc sandbox  │   │  QEMU / Cloud-Hypervisor│
├─────────────────────────┤   ├─────────────────────────┤   ├─────────────────────────┤
│  Железо (Bare-Metal)    │   │  Общее ядро хоста       │   │  KVM / Bare-Metal HW    │
└─────────────────────────┘   └─────────────────────────┘   └─────────────────────────┘
  Overhead: 0                   Overhead: ~100m CPU, 128Mi    Overhead: ~250m CPU, 256Mi
```

#### Характеристики контейнерных рантаймов

| Рантайм | Архитектура изоляции | Накладные расходы (Overhead) | Задержка системных вызовов | Сфера применения |
| :--- | :--- | :--- | :--- | :--- |
| **runc** | Стандартная (cgroups v2 + namespaces) | Нулевые (только процессы приложения) | Минимальная (нативные syscalls хоста) | Доверенные production-нагрузки, базы данных |
| **crun** | Легковесная реализация OCI на C | Ультранизкие (на 30% быстрее runc при старте) | Минимальная | Высоконагруженные микросервисы |
| **gVisor (runsc)** | Эмуляция ядра Linux в userspace (Sentry) | Средние (~5-15% CPU, 30–128 MiB RAM на Pod) | Средняя (перехват через seccomp/ptrace/KVM) | Обработка недоверенных данных, CI/CD runners, вебхуки |
| **Kata Containers** | Аппаратная виртуализация (микро-ВМ) | Высокие (~15-30% CPU, 128–256 MiB RAM на Pod) | Низкая для CPU/памяти, умеренная для дискового I/O | Мультитенантные кластеры, изоляция на уровне железа |

#### Механика расчета Pod Overhead
При использовании сред виртуализации процесс-прокладка (VMM, userspace-ядро) потребляет физические ресурсы узла. Механизм `Pod Overhead` решает проблему корректного учета этих затрат:

1. **Планирование (`kube-scheduler`):**
   Планировщик вычисляет эффективные запросы Pod как сумму запросов всех контейнеров плюс фиксированный оверхед:
   $$\text{EffectiveRequest}_{\text{CPU}} = \sum \text{containers.requests.cpu} + \max(\text{initContainers.cpu}) + \text{Overhead}_{\text{CPU}}$$
   $$\text{EffectiveRequest}_{\text{Mem}} = \sum \text{containers.requests.mem} + \max(\text{initContainers.mem}) + \text{Overhead}_{\text{Mem}}$$
2. **Контрольные группы (`cgroup v2`):**
   Kubelet создает корневую cgroup пода (`pod<UID>`) с лимитом, равным сумме лимитов контейнеров плюс `Overhead`. Лимиты внутренних контейнеров остаются неизменными. Вспомогательные процессы гипервизора запускаются внутри родительской cgroup пода, но за пределами cgroup контейнеров приложения.

---

### 5. Разделяемое пространство процессов (shareProcessNamespace)

По умолчанию в Kubernetes каждый контейнер в Pod получает собственное изолированное пространство имен процессов (PID Namespace). Главный процесс контейнера (`ENTRYPOINT`) выполняется с PID 1, что исключает возможность межконтейнерного мониторинга и сигналинга.

Флаг `spec.shareProcessNamespace: true` активирует общий PID Namespace для всех контейнеров пода.

```
       Структура процессов внутри Pod при spec.shareProcessNamespace: true
┌───────────────────────────────────────────────────────────────────────────────┐
│ Pod Sandbox (PID Namespace)                                                   │
│                                                                               │
│  PID 1: /pause (инфраструктурный контейнер ядра, собирает зомби-процессы)    │
│                                                                               │
│  PID 23: nginx: master process /usr/sbin/nginx  [Контейнер: web-server]       │
│    └─► PID 24: nginx: worker process                                          │
│                                                                               │
│  PID 58: python reloader.py                     [Контейнер: config-sidecar]   │
│    └─► Вызывает: kill -HUP 23 (Перезагрузка конфигурации Nginx)               │
└───────────────────────────────────────────────────────────────────────────────┘
```

#### Ключевые архитектурные последствия

1. **PID 1 переходит к Pause-контейнеру:**
   Процессы контейнеров больше не имеют PID 1. Процесс `/pause` берет на себя роль `init` системы и автоматически выполняет `wait()` для завершения зомби-процессов (zombie process reaping), оставшихся после гибели дочерних процессов любого контейнера.
2. **Прозрачность файловой системы `/proc`:**
   Каждый контейнер видит чужие процессы через стандартный `ps aux` или дерево `/proc`. Контейнер-сайдкар может прочитать параметры запуска `/proc/<PID>/cmdline` и переменные окружения `/proc/<PID>/environ` других контейнеров.
3. **Межконтейнерные сигналы (Signal Handling):**
   Контейнеры могут взаимодействовать через системные вызовы сигналов ядра (`kill -HUP`, `SIGTERM`).
   * **Требование к безопасности:** Отправка сигнала разрешена только в том случае, если оба контейнера запущены под одним и тем же пользователем (`securityContext.runAsUser`), либо вызывающий контейнер обладает Linux-капабилити `CAP_KILL`.

---

### 6. Продвинутая адресация и сетевой резолв

#### Стратегии формирования DNS (`dnsPolicy`)
Поле `spec.dnsPolicy` определяет правила генерации файла `/etc/resolv.conf` внутри контейнеров:

* **`ClusterFirst` (по умолчанию):** Любой DNS-запрос сначала отправляется во внутренний кластерный DNS (CoreDNS). Если имя не принадлежит домену кластера (`cluster.local`), CoreDNS пересылает запрос внешним резолверам узла.
* **`ClusterFirstWithHostNet`:** Обязателен для подов, работающих с сетевым стеком хоста (`hostNetwork: true`). Без этой директивы Pod с `hostNetwork` будет использовать исключительно DNS хоста и потеряет способность разрешать имена сервисов Kubernetes (`<service>.<ns>.svc.cluster.local`).
* **`Default`:** Pod напрямую наследует конфигурацию резолвера с физического узла, полностью игнорируя кластерный CoreDNS.
* **`None`:** Kubelet игнорирует стандартные настройки кластера. Конфигурация DNS должна быть полностью описана вручную в блоке `spec.dnsConfig`.

#### Проблема `ndots:5` и деградация conntrack
По умолчанию Kubelet генерирует файл `/etc/resolv.conf` со значением директивы `options ndots:5`:

```
nameserver 10.96.0.10
search default.svc.cluster.local svc.cluster.local cluster.local
options ndots:5
```

Если доменное имя содержит меньше 5 точек, резолвер glibc обязан последовательно опросить все суффиксы из списка `search`:
1. Запрос к `api.github.com` (2 точки < 5):
   * `api.github.com.default.svc.cluster.local.` $\rightarrow$ NXDOMAIN
   * `api.github.com.svc.cluster.local.` $\rightarrow$ NXDOMAIN
   * `api.github.com.cluster.local.` $\rightarrow$ NXDOMAIN
   * `api.github.com.` $\rightarrow$ NOERROR (успех только на 4-й попытке)
2. **Последствия для SRE:**
   * Четырехкратное умножение трафика на CoreDNS.
   * Переполнение таблицы отслеживания соединений ядра Linux (`nf_conntrack_max`).
   * Состояние гонки (UDP race condition) в glibc при одновременных A и AAAA запросах, приводящее к 5-секундным задержкам ответов (DNS timeout).

#### Механизм `hostAliases`
Директива `spec.hostAliases` позволяет безопасно внедрять статические соответствия IP-адресов и доменных имен в `/etc/hosts` на уровне пода. Попытка вручную отредактировать `/etc/hosts` внутри работающего контейнера не сохраняется при перезапуске контейнера, так как файл монтируется и управляется непосредственно процессом Kubelet.

#### Механизм `setHostnameAsFQDN`
Стандартно внутри Pod системный вызов `gethostname()` возвращает только короткое имя пода (`spec.hostname`). При установке `setHostnameAsFQDN: true` в комбинации с `subdomain` Kubelet настраивает ядро так, что команда `hostname -f` и системные вызовы возвращают полный кластерный FQDN (`node-0.database.production.svc.cluster.local`), что критично для работы протоколов Kerberos, Kafka, Zookeeper и распределенных баз данных.

---

### 7. Диагностика завершения процессов (Termination Messages)

Когда контейнер падает или завершается аварийно, оркестратору необходимо зарегистрировать причину инцидента. Kubernetes предоставляет механизм сохранения предсмертных сообщений в объекте Pod (`status.containerStatuses[*].lastState.terminated.message`), доступных через API без обращения к логам.

#### Политики `terminationMessagePolicy`

| Политика | Источник данных | Максимальный размер | Поведение при сбое |
| :--- | :--- | :--- | :--- |
| **`File`** (по умолчанию) | Локальный файл контейнера (`spec.containers[*].terminationMessagePath`, дефолт: `/dev/termination-log`) | 4096 байт или 80 строк | Если файл пуст, статусное сообщение в объекте Pod остается пустым. |
| **`FallbackToLogsOnError`** | Сначала проверяется `terminationMessagePath`. Если он пуст и контейнер завершился с кодом ошибки (!= 0), берутся последние строки лога (stdout/stderr) | 2048 байт или 80 строк | Гарантирует попадание stack trace падения прямо в `kubectl describe pod`. |

---

## Практические сценарии и конфигурация

### Сценарий 1: Тонкая настройка DNS и системный FQDN

Сценарий конфигурирования узла распределенной базы данных, требующей снижения задержек DNS (`ndots:2`), расширенных таймаутов резолвера и строгого соответствия FQDN хоста.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: storage-node-0
  namespace: database
  labels:
    app.kubernetes.io/name: storage-cluster
    app.kubernetes.io/component: database
spec:
  hostname: storage-node-0
  subdomain: storage-cluster
  setHostnameAsFQDN: true
  dnsPolicy: ClusterFirst
  dnsConfig:
    nameservers:
      - 10.96.0.10
    searches:
      - database.svc.cluster.local
      - svc.cluster.local
      - cluster.local
    options:
      - name: ndots
        value: "2"
      - name: timeout
        value: "2"
      - name: attempts
        value: "3"
      - name: single-request-reopen
  containers:
    - name: db-engine
      image: postgres:16.8-alpine
      ports:
        - name: postgres
          containerPort: 5432
      env:
        - name: POSTGRES_PASSWORD
          value: "ClusterSecurePass123"
      resources:
        requests:
          cpu: "500m"
          memory: "1Gi"
        limits:
          cpu: "2"
          memory: "2Gi"
```

**Проверка сетевой конфигурации и FQDN:**
```bash
# Проверка системного FQDN внутри контейнера
kubectl exec -n database storage-node-0 -c db-engine -- hostname -f
# → storage-node-0.storage-cluster.database.svc.cluster.local

# Проверка содержимого сгенерированного /etc/resolv.conf
kubectl exec -n database storage-node-0 -c db-engine -- cat /etc/resolv.conf
# → nameserver 10.96.0.10
# → search database.svc.cluster.local svc.cluster.local cluster.local
# → options ndots:2 timeout:2 attempts:3 single-request-reopen
```

---

<a id="врата-готовности-readiness-gates"></a>
### Сценарий 2: Readiness Gates для внешнего Ingress / Mesh контроллера

Сценарий интеграции Pod с внешним балансировщиком нагрузки, использующим кастомное условие `loadbalancer.internal/target-registered`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: api-gateway-backend
  namespace: production
  labels:
    app.kubernetes.io/name: api-gateway
spec:
  readinessGates:
    - conditionType: "loadbalancer.internal/target-registered"
  containers:
    - name: api-server
      image: nginx:1.27.4-alpine
      ports:
        - name: http
          containerPort: 8080
      readinessProbe:
        httpGet:
          path: /healthz
          port: 8080
        initialDelaySeconds: 3
        periodSeconds: 5
      resources:
        requests:
          cpu: "200m"
          memory: "256Mi"
        limits:
          cpu: "1"
          memory: "512Mi"
```

**Диагностика и перевод статуса внешним контроллером:**
```bash
# 1. Проверка условий Pod сразу после запуска (локальный порт готов, но Pod не Ready)
kubectl get pod -n production api-gateway-backend -o jsonpath='{range .status.conditions[*]}{.type}{"="}{.status}{" ("}{.reason}{")\n"}{end}'
# → Initialized=True ()
# → Ready=False (ReadinessGatesNotReady)
# → ContainersReady=True ()
# → PodScheduled=True ()

# 2. Имитация работы внешнего контроллера: регистрация IP и установка условия в True через API status
kubectl patch pod -n production api-gateway-backend --subresource=status --type='json' -p='[
  {
    "op": "add",
    "path": "/status/conditions/-",
    "value": {
      "type": "loadbalancer.internal/target-registered",
      "status": "True",
      "lastTransitionTime": "'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'",
      "reason": "TargetRegisteredInBalancer",
      "message": "Pod IP registered in edge proxy pool"
    }
  }
]'
# → pod/api-gateway-backend patched

# 3. Проверка результирующей готовности Pod
kubectl get pod -n production api-gateway-backend -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# → True
```

---

### Сценарий 3: Scheduling Gates для внешнего аудита безопасности

Сценарий удержания Pod от планирования до завершения аудита целостности образов контроллером безопасности.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-worker
  namespace: processing
  labels:
    app.kubernetes.io/name: payment-processor
spec:
  schedulingGates:
    - name: "security.internal/image-compliance"
  containers:
    - name: worker
      image: alpine:3.21
      command: ["sleep", "3600"]
      resources:
        requests:
          cpu: "100m"
          memory: "128Mi"
        limits:
          cpu: "500m"
          memory: "256Mi"
```

**Инспекция состояния и снятие ворот планирования:**
```bash
# 1. Проверка состояния пода (должен быть в состоянии SchedulingGated)
kubectl get pod -n processing secure-worker
# → NAME            READY   STATUS            RESTARTS   AGE
# → secure-worker   0/1     SchedulingGated   0          15s

# 2. Проверка активных ворот в манифесте объекта
kubectl get pod -n processing secure-worker -o jsonpath='{.spec.schedulingGates[*].name}'
# → security.internal/image-compliance

# 3. Проверка событий: scheduler не предпринимает попыток размещения
kubectl describe pod -n processing secure-worker | grep -E "Events:|Scheduling disabled"
# → Events:
# →   Normal  Scheduled  20s  default-scheduler  Scheduling disabled: pod has unresolved scheduling gates

# 4. Снятие ворот контроллером безопасности после успешной проверки
kubectl patch pod -n processing secure-worker --type='json' -p='[
  {
    "op": "remove",
    "path": "/spec/schedulingGates/0"
  }
]'
# → pod/secure-worker patched

# 5. Проверка успешного планирования на узел
kubectl get pod -n processing secure-worker -o wide
# → NAME            READY   STATUS    RESTARTS   AGE   IP           NODE
# → secure-worker   1/1     Running   0          45s   10.244.1.18  worker-node-01
```

---

### Сценарий 4: Межконтейнерное управление сигналами через `shareProcessNamespace`

Сценарий динамической перезагрузки конфигурации веб-сервера без перезапуска Pod. Контейнер `reloader` отслеживает изменения в монтируемом томе и отправляет сигнал `SIGHUP` главному процессу `nginx` в соседнем контейнере.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: web-with-reloader
  namespace: production
spec:
  shareProcessNamespace: true
  securityContext:
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
  volumes:
    - name: config-volume
      emptyDir: {}
  containers:
    - name: nginx
      image: nginxinc/nginx-unprivileged:1.27-alpine
      volumeMounts:
        - name: config-volume
          mountPath: /etc/nginx/conf.d
      resources:
        requests:
          cpu: "100m"
          memory: "128Mi"
        limits:
          cpu: "500m"
          memory: "256Mi"
    - name: reloader
      image: alpine:3.21
      command:
        - "sh"
        - "-c"
        - |
          echo "Reloader started. Waiting for reload trigger..."
          while true; do
            if [ -f /etc/nginx/conf.d/trigger.reload ]; then
              echo "Reload trigger detected. Finding Nginx master process..."
              PID=$(pgrep -f "nginx: master process" | head -n 1)
              if [ -n "$PID" ]; then
                echo "Sending SIGHUP to Nginx master PID $PID"
                kill -HUP "$PID"
                rm -f /etc/nginx/conf.d/trigger.reload
              else
                echo "Error: Nginx master process not found!"
              fi
            fi
            sleep 2
          done
      volumeMounts:
        - name: config-volume
          mountPath: /etc/nginx/conf.d
      resources:
        requests:
          cpu: "50m"
          memory: "64Mi"
        limits:
          cpu: "100m"
          memory: "128Mi"
```

**Тестирование межконтейнерного сигналинга:**
```bash
# Просмотр общего дерева процессов из контейнера reloader
kubectl exec -n production web-with-reloader -c reloader -- ps aux
# → PID   USER     TIME  COMMAND
# →     1 1000      0:00 /pause
# →     7 1000      0:00 nginx: master process nginx -g daemon off;
# →    22 1000      0:00 nginx: worker process
# →    28 1000      0:00 sh -c echo "Reloader started...
# →    45 1000      0:00 ps aux

# Создание триггера перезагрузки в общем томе
kubectl exec -n production web-with-reloader -c reloader -- touch /etc/nginx/conf.d/trigger.reload

# Проверка логов контейнера reloader
kubectl logs -n production web-with-reloader -c reloader --tail=5
# → Reload trigger detected. Finding Nginx master process...
# → Sending SIGHUP to Nginx master PID 7
```

---

<a id="overhead-пода"></a>
### Сценарий 5: Изоляция рантайма и Pod Overhead

Определение класса среды выполнения с аппаратной изоляцией микро-ВМ (Kata Containers) и резервированием системного оверхеда для гипервизора.

```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata-qemu
handler: kata-qemu
overhead:
  podFixed:
    cpu: "250m"
    memory: "192Mi"
scheduling:
  nodeSelector:
    kubernetes.io/arch: "amd64"
    node.kubernetes.io/runtime: "kata"
---
apiVersion: v1
kind: Pod
metadata:
  name: untrusted-isolated-job
  namespace: security-sandbox
spec:
  runtimeClassName: kata-qemu
  containers:
    - name: data-parser
      image: alpine:3.21
      command: ["sh", "-c", "head -c 64M </dev/urandom > /tmp/data.bin && sleep 3600"]
      resources:
        requests:
          cpu: "500m"
          memory: "256Mi"
        limits:
          cpu: "1"
          memory: "512Mi"
```

**Верификация учета оверхеда планировщиком:**
```bash
# Проверка настроек RuntimeClass
kubectl get runtimeclass kata-qemu -o jsonpath='{.overhead.podFixed}'
# → {"cpu":"250m","memory":"192Mi"}

# Проверка эффективного расчета планировщика в описании пода:
# Запрос контейнера: 500m CPU, 256Mi RAM
# Итоговый запрос планировщика: 500m + 250m = 750m CPU, 256Mi + 192Mi = 448Mi RAM
kubectl describe pod -n security-sandbox untrusted-isolated-job | grep -A 4 "Overhead:"
# → Overhead:
# →   cpu:     250m
# →   memory:  192Mi
```

---

<a id="пример-3-диагностика-через-termination-message"></a>
### Сценарий 6: Post-Mortem диагностика через `FallbackToLogsOnError`

Конфигурация аварийного перехвата критических ошибок упавшего сервиса прямо в объект Pod без необходимости наличия централизованной системы сбора логов.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: crashing-backend
  namespace: test-debug
spec:
  restartPolicy: Never
  containers:
    - name: application
      image: alpine:3.21
      command:
        - "sh"
        - "-c"
        - |
          echo "[INFO] Application initializing..."
          echo "[INFO] Connecting to database master at 10.0.12.5..."
          sleep 2
          echo "FATAL: Connection refused: SQLSTATE[08006] Database connection failure" >&2
          exit 1
      terminationMessagePath: /dev/termination-log
      terminationMessagePolicy: FallbackToLogsOnError
      resources:
        requests:
          cpu: "50m"
          memory: "64Mi"
        limits:
          cpu: "100m"
          memory: "128Mi"
```

**Получение аварийного сообщения из статуса Pod:**
```bash
# Ожидание падения контейнера
kubectl wait --namespace test-debug --for=jsonpath='{.status.phase}'=Failed pod/crashing-backend --timeout=30s
# → pod/crashing-backend condition met

# Мгновенная вычитка причины аварии из объекта Pod (минуя хранилища логов)
kubectl get pod -n test-debug crashing-backend -o jsonpath='{.status.containerStatuses[0].lastState.terminated.message}'
# → FATAL: Connection refused: SQLSTATE[08006] Database connection failure

# Проверка кода возврата (Exit Code)
kubectl get pod -n test-debug crashing-backend -o jsonpath='{.status.containerStatuses[0].lastState.terminated.exitCode}'
# → 1
```

---

### Сценарий 7: Статическое связывание имен через `hostAliases`

Интеграция корпоративного legacy-клиента с локальными сервисами филиала, не имеющими публичных DNS-записей.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: legacy-client
  namespace: default
spec:
  hostAliases:
    - ip: "192.168.100.55"
      hostnames:
        - "erp-auth.internal"
        - "sso-gateway.corp"
    - ip: "192.168.100.56"
      hostnames:
        - "audit-collector.internal"
  containers:
    - name: client
      image: alpine:3.21
      command: ["sleep", "3600"]
      resources:
        requests:
          cpu: "50m"
          memory: "64Mi"
```

**Проверка генерации `/etc/hosts` внутри контейнера:**
```bash
kubectl exec legacy-client -- cat /etc/hosts
# → # Kubernetes-managed hosts file.
# → 127.0.0.1	localhost
# → ::1	localhost ip6-localhost ip6-loopback
# → fe00::0	ip6-localnet
# → ...
# → # Entries added by HostAliases.
# → 192.168.100.55	erp-auth.internal	sso-gateway.corp
# → 192.168.100.56	audit-collector.internal
```

---

<a id="продвинутые-паттерны-init-контейнеров"></a>
### Сценарий 8: Продвинутые паттерны Init-контейнеров

В практической эксплуатации инициализирующие контейнеры разделяются на два архитектурных типа:
1. **Классические Init-контейнеры (`restartPolicy: OnFailure` / `Never`):** Выполняются строго последовательно до старта основных контейнеров.
   * *Паттерн ожидания зависимости:* Блокировка старта приложения до доступности внешних сервисов (`until nc -z db 5432; do sleep 2; done`).
   * *Паттерн миграции данных:* Однократный запуск скриптов обновления схемы базы данных перед развертыванием приложения.
   * *Паттерн подготовки конфигурации:* Скачивание или генерация конфигураций в общий том `emptyDir`.
   *(Подробный разбор и готовые манифесты см. в [Init-контейнеры в Kubernetes](./pod_init_containers.md)).*
2. **Нативные Sidecar-контейнеры (`restartPolicy: Always` внутри `initContainers`):**
   * Стартуют в порядке очереди среди init-контейнеров.
   * Следующий контейнер запускается **только после** того, как сайдкар прошел `startupProbe` или `readinessProbe`.
   * При завершении Pod сайдкары останавливаются **после** завершения основных рабочих контейнеров, гарантируя передачу логов и метрик до полной остановки пода (см. [Паттерны Sidecar в Kubernetes](./pod_sidecar_patterns.md)).

---

## Операции и команды

Сводная таблица команд `kubectl` для инспекции и управления расширенными параметрами Pod:

| Операция | Команда CLI | Ожидаемый вывод / Результат |
| :--- | :--- | :--- |
| **Поиск всех Pod с Scheduling Gates** | `kubectl get pods -A -o json \| jq -r '.items[] \| select(.spec.schedulingGates != null) \| "\(.metadata.namespace)/\(.metadata.name): \([.spec.schedulingGates[].name])"'` | Список заблокированных подов с именами ворот. |
| **Снятие ворот планирования вручную** | `kubectl patch pod <pod-name> -n <ns> --type='json' -p='[{"op":"remove","path":"/spec/schedulingGates/0"}]'` | `pod/<name> patched` (переход в очередь планировщика). |
| **Проверка статуса Readiness Gates** | `kubectl get pod <pod-name> -n <ns> -o jsonpath='{.status.conditions[?(@.type=="<gate-type>")].status}'` | `True`, `False` или пусто (если условие еще не выставлено). |
| **Установка статуса Readiness Gate** | `kubectl patch pod <pod-name> -n <ns> --subresource=status --type='json' -p='[{"op":"add","path":"/status/conditions/-","value":{"type":"<gate-name>","status":"True","reason":"ManualApproval"}}]'` | `pod/<name> patched` (обновление условий без изменения спецификации). |
| **Вычитка Termination Message** | `kubectl get pod <pod-name> -n <ns> -o jsonpath='{range .status.containerStatuses[*]}{.name}{": "}{.lastState.terminated.message}{"\n"}{end}'` | Текст последней ошибки (stack trace) упавших контейнеров. |
| **Инспекция Pod Overhead** | `kubectl get pod <pod-name> -n <ns> -o jsonpath='{.spec.overhead}'` | `{"cpu":"...","memory":"..."}` (фиксированный оверхед). |
| **Проверка DNS резолвера в Pod** | `kubectl exec <pod-name> -n <ns> -- cat /etc/resolv.conf` | Содержимое DNS-конфигурации (`nameserver`, `search`, `options`). |
| **Замер времени резолва с ndots** | `kubectl exec <pod-name> -n <ns> -- time nslookup ya.ru` | `real 0m0.005s` (быстро при `ndots:2`) либо `real 0m0.050s`+ при задержках search. |

---

## Диагностика и устранение неисправностей

### 1. Pod завис в статусе `SchedulingGated`
* **Симптом:** Pod находится в статусе `SchedulingGated` часами, `kube-scheduler` не выдает событий `FailedScheduling`.
* **Причина:** Внешний контроллер (квот, безопасности, подготовки дисков), ответственный за удаление ворот из `spec.schedulingGates`, завершился аварийно или не получил событие создания Pod.
* **Диагностика:**
  ```bash
  # Проверка списка неразрешенных ворот
  kubectl get pod <pod-name> -n <ns> -o jsonpath='{.spec.schedulingGates[*].name}'
  # → custom.k8s.io/hardware-validation

  # Проверка очереди scheduler в метриках Control Plane
  kubectl get --raw /metrics | grep scheduler_pending_pods
  # → scheduler_pending_pods{queue="gated"} 1
  ```
* **Решение:**
  1. Проверить логи ответственного оператора в кластере.
  2. Если инцидент вызван зависанием контроллера, удалить ворота принудительно через JSON Patch:
     ```bash
     kubectl patch pod <pod-name> -n <ns> --type='json' -p='[{"op":"remove","path":"/spec/schedulingGates"}]'
     ```

---

### 2. Pod в статусе `Running`, но `Ready: False` из-за `ReadinessGates`
* **Симптом:** Приложение внутри контейнера работает стабильно, эндпоинты `readinessProbe` возвращают 200 OK, но Pod не добавляется в Endpoints/EndpointSlice сервиса.
* **Причина:** Одно или несколько условий из `spec.readinessGates` имеют статус `False` либо отсутствуют в `status.conditions`.
* **Диагностика:**
  ```bash
  # Проверка статуса readiness-условий
  kubectl describe pod <pod-name> -n <ns> | grep -A 10 "Readiness Gates:"
  # → Readiness Gates:
  # →   Type                                   Status
  # →   ingress.internal/target-synchronized   False
  ```
* **Решение:**
  1. Убедиться, что сетевой контроллер имеет права доступа RBAC к подресурсу `pods/status`.
  2. Проверить сетевую связность контроллера с внешним балансировщиком.
  3. В аварийной ситуации перевести условие в `True` вручную через `kubectl patch pod ... --subresource=status`.

---

### 3. Задержки DNS и исчерпание conntrack-таблицы из-за `ndots:5`
* **Симптом:** Периодические 5-секундные задержки при исходящих HTTP/gRPC запросах к внешним API; ошибки `dial tcp: lookup ...: i/o timeout`; рост счетчика `drop` в `conntrack`.
* **Причина:** Значение `ndots:5` генерирует лавину NXDOMAIN-запросов к CoreDNS при каждом обращении к внешним хостам с числом точек менее пяти (например, `api.stripe.com`). Одновременные запросы A и AAAA вызывают race condition в conntrack ядра хоста.
* **Диагностика:**
  ```bash
  # Проверка текущего значения ndots внутри пода
  kubectl exec <pod-name> -n <ns> -- cat /etc/resolv.conf | grep ndots
  # → options ndots:5

  # Проверка загрузки conntrack на узле
  sudo conntrack -C
  cat /proc/sys/net/netfilter/nf_conntrack_count
  ```
* **Решение:**
  1. В манифесте Pod добавить явное уменьшение `ndots` до `2` в `spec.dnsConfig.options`.
  2. Добавить опцию `single-request-reopen` для предотвращения параллельных UDP-запросов в одном сокете.
  3. В коде приложений добавлять точку в конце абсолютных внешних доменов (`api.stripe.com.`).

---

### 4. Ошибка `Operation not permitted` при отправке сигнала в `shareProcessNamespace`
* **Симптом:** Контейнер-сайдкар падает с ошибкой `kill: (PID) - Operation not permitted` при попытке отправить сигнал перезагрузки основному приложению.
* **Причина:** Контейнеры запущены под разными пользователями (`runAsUser`), и вызывающий контейнер не имеет привилегии `CAP_KILL`.
* **Диагностика:**
  ```bash
  # Проверка UID процессов в общем дереве
  kubectl exec <pod-name> -n <ns> -c <sidecar> -- ps -o pid,user,comm
  # → PID   USER       COMMAND
  # →   1   root       /pause
  # →  12   1001       app-server
  # →  25   1002       reloader
  ```
* **Решение:**
  1. Унифицировать идентификаторы пользователей через `spec.securityContext.runAsUser`.
  2. Если унификация UID невозможна, выдать контейнеру-сайдкару Linux capability `KILL`:
     ```yaml
     securityContext:
       capabilities:
         add: ["KILL"]
     ```

---

### 5. OOMKilled / Node Eviction из-за неучтенного Pod Overhead в RuntimeClass
* **Симптом:** Pod с изолированным рантаймом (gVisor, Kata) неожиданно завершается по `OOMKilled`, либо узел переходит в состояние `MemoryPressure`, несмотря на то, что контейнеры укладываются в лимиты.
* **Причина:** В объекте `RuntimeClass` не сконфигурирован блок `overhead.podFixed`. Память, потребляемая гипервизором или прокси-ядром, расходуется из системных резервов узла (`system-reserved` / `kube-reserved`).
* **Диагностика:**
  ```bash
  # Проверка наличия overhead в RuntimeClass
  kubectl get runtimeclass <runtime-name> -o yaml | grep -A 5 "overhead:"

  # Проверка реального потребления памяти на уровне cgroup хоста
  cat /sys/fs/cgroup/kubepods.slice/kubepods-burstable.slice/.../memory.current
  ```
* **Решение:**
  Сконфигурировать корректный оверхед в `RuntimeClass`:
  ```yaml
  overhead:
    podFixed:
      cpu: "150m"
      memory: "160Mi"
  ```

---

### 6. Ошибка `field is immutable` при редактировании манифеста
* **Симптом:** Вызов `kubectl apply` или `kubectl edit` завершается отказом:
  `The Pod "my-pod" is invalid: spec: Forbidden: pod updates may not change fields other than ...`
* **Причина:** Попытка прямого редактирования неизменяемых полей PodSpec (`command`, `ports`, `volumeMounts`, `env`).
* **Диагностика:**
  Сравнить локальный файл с текущей спецификацией в кластере:
  ```bash
  kubectl diff -f pod-manifest.yaml
  ```
* **Решение:**
  1. Для production-нагрузок использовать контроллеры верхнего уровня (`Deployment`, `StatefulSet`, `DaemonSet`), которые выполняют ротацию (Rolling Update) через пересоздание Pod.
  2. Для единичных подов: выполнить пересоздание через `kubectl replace --force -f manifest.yaml`.
  3. Для изменения CPU/памяти без перезапуска использовать API `/resize` (при включенном In-Place Pod Resize).

---

### 7. Изменения в `/etc/hosts` пропадают после перезапуска контейнера
* **Симптом:** Сетевой администратор вручную добавил IP в `/etc/hosts` через `kubectl exec`, но после краша контейнера запись стерлась.
* **Причина:** Файл `/etc/hosts` монтируется процессом Kubelet с хоста через `bind mount`. При перезапуске контейнера рантайм пересоздает точку монтирования на основе данных `PodSpec`.
* **Решение:**
  Использовать исключительно декларативное управление через `spec.hostAliases` в манифесте Pod.

---

## Рекомендации и Best Practices

### Чек-лист для DevOps и SRE при проектировании PodSpec

1. **Оптимизация сетевого стека и DNS:**
   * Устанавливайте `ndots: 2` в `spec.dnsConfig.options` для всех микросервисов, выполняющих обращения к внешним доменам.
   * Добавляйте `single-request-reopen`, если кластер использует базовый glibc (Alpine на musl этой проблеме не подвержен, но опция безвредна).
   * Всегда используйте `ClusterFirstWithHostNet`, если для Pod активирован режим `hostNetwork: true`.
2. **Безопасность при `shareProcessNamespace`:**
   * Не используйте общий PID Namespace для разнородных нагрузок. Помните: любой контейнер пода получает доступ к вычитке переменных окружения соседних контейнеров через `/proc/<PID>/environ`, что может привести к утечке паролей и секретных токенов.
   * Всегда явно фиксируйте `runAsUser` и `runAsNonRoot: true`.
3. **Отказоустойчивость внешних шлюзов:**
   * Для контроллеров, управляющих `Readiness Gates` и `Scheduling Gates`, обязательно настраивайте аварийный таймаут (TTL/Watchdog). Если контроллер недоступен более 5 минут, внешняя система мониторинга должна выдавать критический алерт (Sev-2) о блокировке ротации подов.
4. **Эксплуатация изолированных рантаймов:**
   * Никогда не развертывайте `RuntimeClass` с gVisor или Kata Containers без жестко зафиксированного `podFixed` оверхеда. Это исключит деградацию узлов по `MemoryPressure` и каскадные эвикшены.
5. **Диагностика и наблюдаемость:**
   * Добавляйте `terminationMessagePolicy: FallbackToLogsOnError` в шаблоны всех критических сервисов. Это сокращает среднее время восстановления (MTTR) при авариях за счет мгновенной видимости stack trace без обращения к централизованным хранилищам логов.

---

## Дополнительная информация

**Связанные документы в базе знаний:**
* [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — детали фаз, переходов статусов и graceful shutdown.
* [Рекомендации по написанию манифестов Pod](./pod_best_practices.md) — эталонные паттерны безопасности и лимитов для Production.
* [Init-контейнеры в Kubernetes](./pod_init_containers.md) — подробный разбор инициализирующих контейнеров и миграций.
* [Паттерны Sidecar в Kubernetes](./pod_sidecar_patterns.md) — нативные сайдкары и взаимодействие вспомогательных контейнеров.
* [Эфемерные контейнеры в Kubernetes](./ephemeral_containers.md) — отладка работающих подов «на лету» без перезапуска.
* [Изменение ресурсов подов без перезапуска (In-Place Pod Resize)](../../Autoscaling/in_place_pod_resize.md) — детальная архитектура подресурса `/resize` и контроллеров cgroups v2.
* [DNS Deep Dive](../../Networking/dns_deep_dive.md) — тонкая настройка CoreDNS и профилирование сетевого стека.
* [Изоляция рантайма в Security Context](../../Security/pod_security_context.md) — политики безопасности ядра и привилегий.
