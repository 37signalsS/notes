---
last_update: 2026-08-30
reliability_score: 10
---

# Архитектура Control Plane в Kubernetes

## Определения

**Control Plane (Плоскость управления)** — это совокупность управляющих компонентов Kubernetes, которые принимают глобальные решения о состоянии кластера (например, планирование подов), а также обнаруживают и реагируют на события (например, запуск новой реплики, если текущая вышла из строя). Control Plane поддерживает «желаемое состояние» кластера, описанное в объектах API.

**Data Plane (Плоскость данных)** — совокупность рабочих узлов (**Nodes**), на которых непосредственно выполняются контейнеризированные приложения пользователей. Включает в себя компоненты, обеспечивающие запуск контейнеров и сетевую связность.

### Концепция «6 бинарных файлов»

Архитектура Kubernetes базируется на шести ключевых исполняемых файлах, которые разделены по ролям:

1.  **`kube-apiserver`** (Control Plane)
2.  **`kube-scheduler`** (Control Plane)
3.  **`kube-controller-manager`** (Control Plane)
4.  **`cloud-controller-manager`** (Control Plane)
5.  **`kubelet`** (Рабочий узел)
6.  **`kube-proxy`** (Рабочий узел)

*Примечание: **etcd** и среда выполнения (**Container Runtime**, например, `containerd`) являются внешними по отношению к основному проекту Kubernetes, но критически важны для его функционирования.*

## Предварительные требования (Prerequisites)

### Аппаратные требования Control Plane

| Компонент | CPU | RAM | Диск |
| :--- | :--- | :--- | :--- |
| `kube-apiserver` | 2+ ядра | 2+ GiB | SSD (малая нагрузка) |
| `etcd` | 2+ ядра | 2+ GiB | NVMe/SSD (критично: fsync <10 мс) |
| `kube-scheduler` | 1+ ядро | 512+ MiB | SSD |
| `kube-controller-manager` | 1+ ядро | 512+ MiB | SSD |

*Примечание: Для HA-кластеров рекомендуется выделять Control Plane на отдельные узлы с выделенными дисками NVMe для etcd.*

### Программные зависимости

*   **ОС**: Ubuntu 22.04+, Debian 12+, CentOS/RHEL 9+ (или совместимые)
*   **containerd** (>= 1.6) или **CRI-O** (>= 1.25)
*   **kubeadm**, **kubectl**, **kubelet** одной версии (допустимо отклонение ±1 минорную версию для kubectl/kubelet относительно Control Plane)
*   **Сеть**: Открытые порты (см. секцию «Порты и трафик»)
*   **Ядро Linux**: Открытие `overlay` модуля для containerd, `br_netfilter` для сети

```bash
# Проверка готовности системы (kubeadm)
sudo kubeadm init phase preflight
```

## Основные компоненты Control Plane

### kube-apiserver (API-сервер)
Центральный компонент, «входная дверь» и коммуникационный концентратор кластера. Предоставляет **HTTP REST API**, обрабатывает и проверяет запросы. Служит единственной точкой входа для всех административных задач и связывает все остальные части Control Plane. Масштабируется горизонтально.

### etcd
Распределенное хранилище типа «ключ-значение» на основе алгоритма консенсуса **Raft**. Это **централизованное хранилище** кластера, обеспечивающее согласованность всей конфигурации и текущего состояния ресурсов. Требует нечётного числа узлов для формирования кворума. Медленный диск (fsync >10 мс) вызывает перевыборы лидера и дестабилизацию кластера.

### kube-scheduler (Планировщик)
Отвечает за распределение работы по узлам. Он обнаруживает новые поды без назначенного узла, оценивает их требования к ресурсам (Pod requests), политики качества обслуживания (**QoS**), аффинити-правила и другие ограничения. Процесс включает фазы **Filtering** (отсев) и **Scoring** (ранжирование) в рамках расширяемого **Scheduling Framework**.

### kube-controller-manager
Единый процесс, объединяющий контроллеры, которые поддерживают желаемое состояние кластера (цикл согласования). Основные контроллеры:
*   **Node controller**: следит за состоянием узлов (heartbeat).
*   **Replication controller**: поддерживает заданное количество реплик подов.
*   **Endpoints controller**: заполняет объекты `Endpoints` и `EndpointSlice`.
*   **Service Account & Token controller**: управляет учетными записями и токенами.
*   **Persistent Volume controller**: управляет жизненным циклом PV и PVC через **CSI**.

### cloud-controller-manager (CCM)
Компонент, обеспечивающий интеграцию с API облачных провайдеров. Выносит специфичный для облака код (LB, маршруты, диски) за пределы основного ядра Kubernetes (**out-of-tree**), сохраняя проект вендор-нейтральным.

## kube-apiserver — обработка запросов (Handler Pipeline)

Все запросы проходят через строго упорядоченный конвейер обработки:

1.  **Аутентификация (Authentication)**: Проверка личности («кто вы?»). С версии 1.30 поддерживается **Structured Authentication Config**, позволяющий настраивать несколько провайдеров (JWT, Webhook) через файл конфигурации без перезагрузки API-сервера.
2.  **Авторизация (Authorization)**: Проверка прав («что можно?»). Основной механизм — **RBAC**. С версии 1.30 доступна **Structured Authorization Config** для сложной настройки прав.
3.  **Admission Control (Mutation → Validation)**:
    *   **Mutating Admission**: Может изменять запрос (например, добавлять sidecar-контейнеры, устанавливать дефолтные лимиты ресурсов или инжектировать секреты).
    *   **Validating Admission**: Проверяет финальное состояние объекта на соответствие политикам. Современный стандарт — **ValidatingAdmissionPolicy** на базе языка **CEL** (Common Expression Language), работающий внутри процесса API-сервера, что исключает сетевые задержки внешних вебхуков.
4.  **Сохранение в etcd**: Запись сериализованного объекта в базу данных.
5.  **Уведомление (Watch)**: Рассылка событий подписчикам через асинхронный механизм оповещения.

### API Priority and Fairness (APF)
Механизм защиты API-сервера от перегрузок (Stable в 1.29). Вместо простого ограничения количества запросов (**MaxInFlight**), APF классифицирует запросы по приоритетам:
*   **FlowSchemas**: Определяют, как группировать запросы (по пользователю, Namespace и т.д.).
*   **PriorityLevelConfigurations**: Определяют выделенные ресурсы (очереди и доли пропускной способности) для каждой группы.
Это гарантирует, что критические системные запросы (например, от `kubelet`) не будут вытеснены тяжелыми пользовательскими запросами (например, массовый листинг подов).

## Структура API: Группы и Версии

### API Groups
*   **Core (Legacy)**: `/api/v1`. Базовые ресурсы: `Pods`, `Services`, `Nodes`, `ConfigMaps`.
*   **Named Groups**: `/apis/$GROUP_NAME/$VERSION`. Примеры: `apps` (Deployments), `batch` (Jobs), `networking.k8s.io` (Ingress).

### API Versions
*   **Alpha (`v1alpha1`)**: Новые функции, выключены по умолчанию. Нет гарантии совместимости.
*   **Beta (`v1beta1`)**: Функции протестированы, включены по умолчанию.
*   **Stable (`v1`)**: Готовы к промышленному использованию с долгосрочной поддержкой.

## Размещение etcd: Stacked vs External

1.  **Stacked etcd (Совмещенный)**: etcd работает как статические поды на тех же узлах, что и Control Plane.
    *   *Плюсы*: Простота развертывания, минимальная сетевая задержка.
    *   *Минусы*: Конкуренция за ресурсы (CPU/Disk) между API и базой. Сбой узла выбивает оба компонента.
2.  **External etcd (Выделенный)**: etcd на отдельных физических или виртуальных серверах.
    *   *Плюсы*: Максимальная изоляция, независимое масштабирование, выше надежность.
    *   *Минусы*: Дополнительные сетевые задержки, сложность управления сертификатами и хостами.

## Компоненты рабочего узла (Data Plane)

### kubelet
Главный агент на узле. Управляет жизненным циклом подов, взаимодействуя с Control Plane и средой выполнения через **CRI** (Container Runtime Interface).

### kube-proxy
Сетевой прокси, программирующий правила **iptables** или **IPVS** для реализации абстракции `Service`.

### CRI и Container Runtime
Среда запуска контейнеров (например, **containerd**, **CRI-O**). Kubernetes взаимодействует с ними по стандартному протоколу CRI.

> **Почему Docker Engine был объявлен устаревшим (deprecated)?**
> Традиционный Docker Engine не поддерживал протокол **CRI** напрямую, что требовало использования промежуточного слоя — **dockershim**. С версии 1.24 Kubernetes перешел на прямое использование **containerd** и **CRI-O** по причинам:
> 1.  **Снижение накладных расходов**: Исключается лишнее звено (Docker содержит много функций, не нужных K8s).
> 2.  **Стабильность**: Отсутствие зависимости от специфических обновлений Docker.
> 3.  **Соответствие стандартам OCI**: Фокус на переносимости и модульности.

## Новые архитектурные паттерны

### Native Sidecars (1.29+)
Введен нативный тип sidecar-контейнеров через поле `restartPolicy: Always` внутри `initContainers`. Это решает проблему жизненного цикла: sidecar гарантированно запускается перед основными контейнерами и корректно завершается после них, не блокируя завершение **Job**.

### Механизм Lease и оптимизация Heartbeats
Объекты **Lease** используются для:
1.  **Node Heartbeats**: Вместо тяжелых обновлений объекта `Node` (каждые 10с), `kubelet` обновляет легкий Lease-объект в Namespace `kube-node-lease`. Это радикально снижает нагрузку на `etcd` и API-сервер в крупных кластерах.
2.  **Leader Election**: Компоненты используют Lease для выбора активного лидера в HA-конфигурациях.

## Практические сценарии

### Жизненный цикл создания пода
1.  **Пользователь**: `kubectl apply` отправляет запрос.
2.  **kube-apiserver**: Authn → Authz → Mutating Admission (инъекция sidecars) → Validation.
3.  **etcd**: Запись объекта со статусом `Pending`.
4.  **Deployment Controller**: Создает `ReplicaSet`.
5.  **ReplicaSet Controller**: Создает спецификации `Pod`.
6.  **kube-scheduler**: Проходит фазы Filtering/Scoring, выбирает узел и обновляет `nodeName` в API.
7.  **kubelet**: Видит назначение через Watch, вызывает CRI для запуска.
8.  **Status Update**: Статус `Running` записывается в API.

### Масштабирование Deployment
При `kubectl scale --replicas=5`:
1.  **kube-apiserver**: Сохраняет новое число реплик в `etcd`.
2.  **Deployment controller**: Обновляет `replicas` в ReplicaSet.
3.  **ReplicaSet controller**: Видит разницу и создает новые объекты Pod.
4.  **Scheduler**: Назначает поды на свободные узлы.
5.  **Kubelet**: Запускает контейнеры.

### Сценарии отказов
*   **Отказ единственного мастера**: Приложения работают, но нельзя изменить конфигурацию кластера.
*   **Потеря кворума etcd**: API переходит в **read-only**. Авто-восстановление подов прекращается.
*   **Падение планировщика**: Новые поды зависают в `Pending`.

## Диагностика и проверка здоровья Control Plane

### Быстрая проверка состояния кластера

```bash
# Статус узлов
kubectl get nodes -o wide
# → NAME    STATUS   ROLES           AGE   VERSION   INTERNAL-IP   ...
# → master  Ready    control-plane   45d   v1.36.2   10.0.0.10     ...
# → node1   Ready    <none>          45d   v1.36.2   10.0.0.11     ...

# Системные поды Control Plane
kubectl get pods -n kube-system -o wide
# → NAME                                       READY   STATUS    RESTARTS   AGE
# → etcd-master                                1/1     Running   0          45d
# → kube-apiserver-master                      1/1     Running   0          45d
# → kube-controller-manager-master             1/1     Running   0          45d
# → kube-scheduler-master                      1/1     Running   0          45d
# → kube-proxy-xxxxx                           1/1     Running   0          45d
# → coredns-xxxxx                              1/1     Running   0          45d

# Информация о кластере
kubectl cluster-info
# → Kubernetes control plane is running at https://10.0.0.10:6443
# → CoreDNS is running at https://10.0.0.10:6443/api/v1/...
```

### Проверка компонентов Control Plane

```bash
# Статус компонентов (устаревшая команда, но работает)
kubectl get componentstatuses
# → NAME                 STATUS    MESSAGE             ERROR
# → controller-manager   Healthy   ok
# → scheduler            Healthy   ok
# → etcd-0               Healthy   {"health":"true"}

# Проверка health-эндпоинтов API-сервера
curl -sk https://<master-ip>:6443/healthz
# → ok

# Проверка etcd (на узле Control Plane)
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint health
# → https://127.0.0.1:2379 is healthy: committed proposal took 15.431468ms
```

### Проверка версий и совместимости

```bash
# Версия сервера
kubectl version
# → Client Version: v1.36.2
# → Kustomize Version: v5.4.3
# → Server Version: v1.36.2

# Проверка версий на узлах
kubectl get nodes -o custom-columns=NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,OS:.status.nodeInfo.osImage,CONTAINER-RUNTIME:.status.nodeInfo.containerRuntimeVersion
```

## Порты и трафик

| Порт | Компонент | Назначение |
| :--- | :--- | :--- |
| 6443 | `kube-apiserver` | Основной API кластера |
| 2379–2380 | `etcd` | Клиентские запросы и пиринг Raft |
| 10250 | `kubelet` | Управление и метрики (logs, exec) |
| 10259 | `kube-scheduler` | Проверка состояния (HA) |
| 10257 | `kube-controller-manager` | Проверка состояния (HA) |
| 30000–32767 | `Services` | Диапазон NodePort |

## Типовые ошибки и их диагностика

### API-сервер не отвечает

**Симптомы**: `kubectl` возвращает `The connection to the server was refused` или зависает.

```bash
# Проверка статуса пода
kubectl get pods -n kube-system kube-apiserver-<master> -o yaml

# Проверка логов
kubectl logs -n kube-system kube-apiserver-<master> --tail=100

# Проверка порта на хосте
sudo ss -tlnp | grep 6443
# → LISTEN  0  4096  127.0.0.1:6443  0.0.0.0:*  users:(("kube-apiserver",pid=1234,fd=6))

# Проверка TLS-сертификата
kubectl get apiserver -o jsonpath='{.items[0].spec.tlsCertSource}'
```

**Типичные причины**:
*   Сертификаты API-сервера истекли (`kubeadm certs check-expiration`)
*   etcd недоступен (API-сервер не может читать/записывать состояние)
*   Конфликт портов (другой процесс слушает 6443)
*   Конфигурация `kube-apiserver.yaml` повреждена

### etcd: потеря кворума

**Симптомы**: `etcdserver: no leader`, ошибки записи, `kubectl get` частично работает.

```bash
# Проверка здоровья etcd кластера
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint status -w table
# → ENDPOINT                ID        VERSION   DB SIZE   IS LEADER   IS LEARNER   RAFT APPLIED INDEX   RAFT TERM
# → https://127.0.0.1:2379  8e9a3...  3.5.12    45 MB     true        false        123456                3

# Проверка членов кластера
sudo ETCDCTL_API=3 etcdctl member list -w table
# → ID        NAME       PEERS      CLIENT URLS        CLIENT CERT AUTH   CLIENT TRUSTED CA
# → 8e9a3...  master     =master    https://127.0.0.1:2379
```

**Решение**: Восстановление из снапшота или добавление недостающих узлов. Подробнее — в [High Availability](../Base/high_availability.md) и [etcd — операции](./etcd_operations.md).

### Планировщик не назначает поды

**Симптомы**: Поды зависают в статусе `Pending` indefinitely.

```bash
# Проверка событий пода
kubectl describe pod <pod-name> | grep -A5 Events
# → Events:
# →   Type    Reason     Age   From               Message
# ----
# →   Normal  Scheduled  60s   default-scheduler  Successfully assigned default/pod-xxx to node1

# Проверка логов планировщика
kubectl logs -n kube-system kube-scheduler-<master> --tail=50

# Проверка taints на узлах
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

**Типичные причины**:
*   Все узлы имеют taints без соответствующих tolerations
*   Ресурсов на узлах недостаточно (memory/CPU pressure)
*   Node Affinity/Pod Affinity не может найти подходящий узел
*   Планировщик не запущен или неhealthy

### kube-controller-manager: контроллеры не работают

**Симптомы**: Поды не пересоздаются после удаления, ReplicaSet не реплицирует, сервисы не обновляются.

```bash
# Проверка логов
kubectl logs -n kube-system kube-controller-manager-<master> --tail=100

# Проверка лидерства (в HA-кластерах)
kubectl get lease kube-controller-manager -n kube-system -o yaml
# → spec:
# →   holderIdentity: <master-name>_xxx
# →   leaseDurationSeconds: 15
# →   renewTime: 2026-08-30T10:00:00Z

# Проверка RBAC-прав контроллера
kubectl auth can-i --list --as=system:kube-controller-manager
```

## Best Practices для Control Plane

### Безопасность
*   Включите **RBAC** и отключите анонимный доступ к API
*   Настройте **Network Policies** для изоляции Control Plane
*   Регулярно обновляйте сертификаты (`kubeadm certs renew`)
*   Включите **Admission Control** политики (PodSecurity, OPA/Gatekeeper)
*   Включите аудит-логирование kube-apiserver

### Производительность
*   Используйте NVMe/SSD диски для etcd (задержка fsync критична)
*   В кластерах >500 узлов — выделите Control Plane на отдельные узлы
*   Настройте `--etcd-compaction-interval` и `--etcd-snapshot-count` для баланса между производительностью и безопасностью данных
*   Используйте **APF** для защиты API-сервера от «шумных» потребителей

### Мониторинг
*   Собирайте метрики API-сервера: `apiserver_request_total`, `apiserver_request_duration_seconds`, `etcd_disk_wal_fsync_duration_seconds`
*   Мониторьте health-эндпоинты: `/healthz`, `/readyz`, `/livez`
*   Отслеживайте лидерство компонентов через Lease-объекты
*   Настраивайте алерты на потерю кворума etcd и недоступность API-сервера

### Резервное копирование
*   Регулярно создавайте снапшоты etcd: `etcdctl snapshot save`
*   Храните снапшоты вне кластера (внешнее хранилище)
*   Периодически проверяйте восстановление из снапшота в тестовой среде
*   Документируйте процедуру восстановления для операторов

### Обновление Control Plane
*   Следите за EOL-датами версий (текущая поддерживаемая: 1.34, 1.35, 1.36)
*   Обновляйте по одной минорной версии за раз
*   Перед обновлением создавайте снапшот etcd
*   Проверяйте составленные изменения (changelog) на наличие breaking changes
*   Используйте `kubeadm upgrade plan` для планирования обновления

## Дополнительная информация
*   **[Высокая доступность в Kubernetes](../Base/high_availability.md)** — архитектура HA-кластеров.
*   **[API Priority and Fairness (APF)](api_priority_and_fairness.md)** — глубокий разбор FlowSchema и PriorityLevelConfiguration.
*   **[Обзор etcd](./etcd_overview.md)** — детальный разбор хранилища.
*   **[Kubelet — основы работы](./kubelet.md)** — агент рабочего узла.
*   **[Взаимодействие с API Kubernetes](./api_interaction.md)** — способы работы с API.
