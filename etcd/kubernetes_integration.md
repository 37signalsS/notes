# etcd в Kubernetes: интеграция и эксплуатация

**Актуально для:** etcd 3.5.x / 3.6.x / 3.7.x; Kubernetes 1.31–1.37

**etcd** — хранилище состояния Kubernetes. Понимание того, как K8s использует etcd, какие данные хранятся и как обслуживать etcd в кластере, критично для любого SRE/Platform Engineer.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Static Pod** | Под, управляемый kubelet напрямую через манифест в `/etc/kubernetes/manifests`. Стандартный способ запуска etcd в kubeadm-кластере. |
| **Control Plane** | Компоненты управления кластером: kube-apiserver, kube-controller-manager, kube-scheduler, etcd. |
| **Stacked etcd** | etcd, запущенный на тех же узлах, что и Control Plane (архитектура по умолчанию в kubeadm). |
| **External etcd** | Отдельный кластер etcd, не связанный с узлами Control Plane. |
| **/registry** | Корневой префикс, по которому kube-apiserver хранит все объекты в etcd (`--etcd-prefix`, дефолт `/registry`). |
| **Watch Cache** | Кэш ресурсов в kube-apiserver: большинство list/watch-запросов клиентов обслуживается из кэша, а не из etcd. Включён по умолчанию (`--watch-cache=true`), размер масштабируется автоматически. |
| **resourceVersion** | Поле объекта, соответствующее `modRevision` ключа в etcd (MVCC). Используется для оптимистичной блокировки и консистентного watch. |
| **Encryption at Rest** | Шифрование данных перед записью в etcd. Выполняется kube-apiserver (EncryptionConfiguration/KMS), не etcd. |
| **Admission Controller** | Компонент API-сервера, который проверяет/изменяет объекты перед записью в etcd. |
| **Informer** | Паттерн в клиентах K8s: подписка на Watch + локальный кэш + вызов reconcile при изменениях. |

---

## Основные концепции

### Модель интеграции: только kube-apiserver имеет доступ к etcd

**kube-apiserver — единственный компонент Kubernetes с прямым доступом к etcd.** Все остальные компоненты (kube-controller-manager, kube-scheduler, kubelet, kube-proxy) работают с состоянием исключительно через API-сервер. Это ключевое архитектурное свойство: etcd изолирован от прямого доступа клиентов, и вся валидация (аутентификация, авторизация, Admission Control) выполняется до записи.

### Что хранится в etcd

Все объекты Kubernetes API сериализуются и хранятся в etcd под префиксом `/registry`:

| Путь в etcd | Ресурс |
| :--- | :--- |
| `/registry/pods/<ns>/<name>` | Pods |
| `/registry/services/specs/<ns>/<name>` | Services |
| `/registry/secrets/<ns>/<name>` | Secrets |
| `/registry/configmaps/<ns>/<name>` | ConfigMaps |
| `/registry/events/<ns>/<name>` | Events (TTL по умолчанию 1ч — главный источник роста БД в нестабильном кластере) |
| `/registry/leases/kube-node-lease/<node>` | Lease-объекты (heartbeat узлов, leader election) |
| `/registry/apiextensions.k8s.io/...` | CRDs |
| `/registry/rbac.authorization.k8s.io/...` | Roles, RoleBindings, ClusterRoles |

**Сериализация:** по умолчанию `application/json` (флаг `--storage-media-type`, дефолт `application/json`); Protobuf доступен опционально (`application/vnd.kubernetes.protobuf`). Поле `metadata.resourceVersion` объекта = `modRevision` ключа в etcd.

**Что НЕ хранится в etcd:**
- Логи подов (filesystem узла или централизованный сбор).
- Данные приложений (PersistentVolumes — метаданные в etcd, данные на диске).
- Состояние контейнеров в container runtime (kubelet управляет локально; статус пода kubelet отправляет в API-сервер, и он персистится в etcd).

### Как kube-apiserver подключается к etcd

Флаги kube-apiserver (манифест `/etc/kubernetes/manifests/kube-apiserver.yaml`):

```bash
--etcd-servers=https://127.0.0.1:2379
--etcd-prefix=/registry
--etcd-cafile=/etc/kubernetes/pki/etcd/ca.crt
--etcd-certfile=/etc/kubernetes/pki/apiserver-etcd-client.crt
--etcd-keyfile=/etc/kubernetes/pki/apiserver-etcd-client.key
--storage-backend=etcd3
--storage-media-type=application/json
--etcd-compaction-interval=5m
--watch-cache=true
```

- Сертификат клиента API-сервера: `/etc/kubernetes/pki/apiserver-etcd-client.crt` (CN `kube-apiserver-etcd-client`).
- Сертификаты etcd в kubeadm: `/etc/kubernetes/pki/etcd/{ca,server,peer,healthcheck-client}.{crt,key}`.
- **Компакция выполняет kube-apiserver** (`--etcd-compaction-interval`, дефолт 5м), а не etcd-сервер. Не включайте `--auto-compaction-retention` на стороне etcd — конкурирующие компакторы вызывают `mvcc: required revision has been compacted` на длинных watch-потоках (см. [Garbage Collection](./garbage_collection.md)).
- **Watch Cache** включён по умолчанию и автоматически масштабируется (флаг `--default-watch-cache-size` устарел). Мониторинг попаданий/промахов кэша — `etcd_helper_cache_hit_count` / `etcd_helper_cache_miss_count` на стороне API-сервера (см. [Мониторинг etcd](./etcd_monitoring.md)).

### Потоки записи и чтения

**Запись (Write Path):**
1. `kubectl apply` → gRPC/HTTPS к kube-apiserver.
2. API-сервер: аутентификация → авторизация → Admission Control.
3. API-сервер сериализует объект и записывает в etcd (gRPC Put/Txn).
4. etcd: Raft replication → commit → apply → ответ API-серверу.
5. API-сервер отвечает клиенту.

**Чтение (Read Path):**
1. Клиент (controller, kubelet) создаёт Informer и подписывается на Watch в API-сервере.
2. API-сервер обслуживает list/watch из **Watch Cache** (не из etcd напрямую).
3. При изменении etcd → событие → Watch Cache → Watch event → Informer → reconcile.

### Балансировка и маршрутизация запросов kube-apiserver к etcd

**Клиент etcd и Round Robin.** kube-apiserver использует библиотеку clientv3 (Go-клиент v3 API etcd), которая внутри использует gRPC с собственным resolver, настроенным на политику `round_robin`. Запросы распределяются равномерно по всем живым endpoint'ам:

- **Унитарные (unary) запросы** — одиночные, распределяются по кругу между всеми узлами etcd.
- **Потоковые (stream) запросы** — `Watch`, `Lease` и подобные — удерживаются на одном конкретном соединении, прикреплённом к определённому etcd-узлу.

**Каждый kube-apiserver имеет свой собственный etcd-клиент и свои соединения.** При нескольких API-серверах каждый из них распределяет свои запросы равномерно по узлам etcd.

**Чтение и запись через лидера.**
- **Запись (Put/Txn):** всегда обрабатывается **лидером** etcd-кластера. Даже если запрос на запись попал на фолловер, он пересылает его лидеру. Лидер записывает данные в систему.
- **Чтение:** по умолчанию используется линеаризуемый режим (linearizable read) — запрос также обслуживается через лидера, чтобы гарантировать актуальность данных. Фолловер может переслить запрос лидеру, либо (при serializable read) отдать данные со своей ноды, но это может возвращать устаревшие данные.

**Работа при сбоях узлов.**
- Если отвалился **лидер** — начинаются перевыборы нового лидера (Raft consensus).
- Если отвалился **фолловер** — gRPC-клиент фиксирует lost connection, помечает endpoint как `transient failure` и перестаёт отправлять на него запросы. Остальные узлы продолжают работать. При восстановлении узла он автоматически добавляется обратно в механизм Round Robin.

**Кворум и отказоустойчивость:**
- **3 узла** — кворум 2, переживает отказ 1 узла.
- **5 узлов** — кворум 3, переживает отказ 2 узлов.
- Чётное количество узлов не имеет смысла: кворум не выше, чем у нечётного на 1 меньше.

### Stacked vs External etcd

| Аспект | Stacked etcd | External etcd |
| :--- | :--- | :--- |
| Развёртывание | На узлах Control Plane | Отдельные узлы |
| Изоляция ресурсов | Нет (общие CPU/RAM/disk) | Да |
| Надёжность | Зависит от Control Plane | Независима |
| Сложность | Ниже (kubeadm автоматически) | Выше |
| Рекомендация | Малые/средние кластеры | Production, критичные нагрузки |

Детали топологий, алгоритма Raft и выбора кворума — в [Обзоре etcd в Kubernetes](../Kubernetes/Concepts/etcd_overview.md).

---

## Практические сценарии

### Static Pod манифест etcd (kubeadm)

kubeadm генерирует манифест `/etc/kubernetes/manifests/etcd.yaml`. Пример (K8s 1.34, etcd 3.6.5):

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: etcd
  namespace: kube-system
  labels:
    component: etcd
    tier: control-plane
  annotations:
    kubeadm.kubernetes.io/etcd.advertise-client-urls: https://<NODE_IP>:2379
spec:
  hostNetwork: true
  priorityClassName: system-node-critical
  containers:
  - name: etcd
    image: registry.k8s.io/etcd:3.6.5-0
    imagePullPolicy: IfNotPresent
    command:
    - etcd
    - --name=<NODE_NAME>
    - --listen-client-urls=https://127.0.0.1:2379,https://<NODE_IP>:2379
    - --advertise-client-urls=https://<NODE_IP>:2379
    - --listen-peer-urls=https://<NODE_IP>:2380
    - --initial-advertise-peer-urls=https://<NODE_IP>:2380
    - --data-dir=/var/lib/etcd
    - --cert-file=/etc/kubernetes/pki/etcd/server.crt
    - --key-file=/etc/kubernetes/pki/etcd/server.key
    - --trusted-ca-file=/etc/kubernetes/pki/etcd/ca.crt
    - --client-cert-auth=true
    - --peer-cert-file=/etc/kubernetes/pki/etcd/peer.crt
    - --peer-key-file=/etc/kubernetes/pki/etcd/peer.key
    - --peer-trusted-ca-file=/etc/kubernetes/pki/etcd/ca.crt
    - --peer-client-cert-auth=true
    - --snapshot-count=10000
    - --listen-metrics-urls=http://127.0.0.1:2381
    - --feature-gates=InitialCorruptCheck=true
    - --watch-progress-notify-interval=5s
    - --initial-cluster=<NODE_NAME>=https://<NODE_IP>:2380,<NODE2>=https://<NODE2_IP>:2380,<NODE3>=https://<NODE3_IP>:2380
    - --initial-cluster-state=existing
    resources:
      requests:
        cpu: 100m
        memory: 100Mi
    volumeMounts:
    - name: etcd-data
      mountPath: /var/lib/etcd
    - name: etcd-certs
      mountPath: /etc/kubernetes/pki/etcd
    ports:
    - name: probe-port
      containerPort: 2381
      protocol: TCP
    livenessProbe:
      httpGet: {host: 127.0.0.1, path: /livez, port: probe-port, scheme: HTTP}
      initialDelaySeconds: 10
      timeoutSeconds: 15
      failureThreshold: 8
      periodSeconds: 10
    readinessProbe:
      httpGet: {host: 127.0.0.1, path: /readyz, port: probe-port, scheme: HTTP}
      initialDelaySeconds: 0
      timeoutSeconds: 15
      failureThreshold: 3
      periodSeconds: 1
    startupProbe:
      httpGet: {host: 127.0.0.1, path: /readyz, port: probe-port, scheme: HTTP}
      periodSeconds: 10
      failureThreshold: 24
  volumes:
  - name: etcd-data
    hostPath: {path: /var/lib/etcd, type: DirectoryOrCreate}
  - name: etcd-certs
    hostPath: {path: /etc/kubernetes/pki/etcd, type: DirectoryOrCreate}
```

**Важные особенности kubeadm-манифеста:**
- **Метрики на порту 2381** (`--listen-metrics-urls=http://127.0.0.1:2381`), а не на 2379. Порт 2379 — клиентский API (HTTPS, требует клиентский сертификат); 2381 — HTTP на localhost без аутентификации, обслуживает только `/metrics`, `/health`, `/version`.
- **`--watch-progress-notify-interval=5s`** — kubeadm устанавливает 5 секунд (дефолт etcd — 10m). Для etcd <3.6 флаги: `--experimental-initial-corrupt-check=true` и `--experimental-watch-progress-notify-interval=5s`.
- **`--initial-cluster-state=existing`** присутствует только при присоединении к существующему кластеру; у первого узла отсутствует.
- **Проверки liveness/readiness/startup** (`/livez`, `/readyz`) выполняются по HTTP на порту 2381.
- **`hostNetwork: true`** и **`priorityClassName: system-node-critical`** — etcd слушает на IP узла и критичен для системы.
- При изменении манифеста kubelet автоматически перезапускает etcd (кратковременная недоступность, если перезапускается лидер).

**Версия etcd в K8s:** K8s 1.31–1.33 → `3.5.24-0`; K8s 1.34–1.36 → `3.6.5-0`; K8s 1.37 → `3.6.x` (опционально 3.7.x через gate `EtcdRangeStream`). Полная матрица — в [Совместимости версий](./version_compatibility.md).

### Проверка здоровья etcd в Kubernetes

```bash
# Через kubectl (статус Static Pod)
kubectl get pods -n kube-system -l component=etcd
# → etcd-<node>   1/1     Running   ...

# Через etcdctl (с TLS, на узле Control Plane)
ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
  endpoint health --cluster
# → https://127.0.0.1:2379 is healthy: true

# Через kube-apiserver: etcd-health эндпоинт API-сервера
curl -k https://127.0.0.1:6443/healthz/etcd
# → ok
```

kube-apiserver экспонирует здоровье etcd через собственные эндпоинты `/healthz/etcd` и `/readyz/etcd-readiness` (а при `--etcd-servers-overrides` — дополнительно `etcd-override-N` / `etcd-override-readiness-N`).

### Создание снапшота изнутри кластера

```bash
kubectl exec -n kube-system etcd-<node> -c etcd -- \
  etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
  snapshot save /var/lib/etcd/backup.db
# → Snapshot saved at: /var/lib/etcd/backup.db

# Проверить целостность снапшота (etcdutl, etcd 3.6+)
kubectl exec -n kube-system etcd-<node> -c etcd -- \
  etcdutl snapshot status /var/lib/etcd/backup.db -w table
# → REVISION | TOTAL KEYS | TOTAL SIZE | COMPACT REVISION

# Скопировать снапшот
kubectl cp kube-system/etcd-<node>:/var/lib/etcd/backup.db ./etcd-backup.db
```

Подробные процедуры бэкапа/восстановления — в [Практических сценариях etcd](../Kubernetes/Concepts/etcd_operations.md) и [Стратегиях резервного копирования](./backup_strategies.md).

### Выделенный etcd для событий (Events)

Events — главный источник роста БД в нестабильном кластере. Для крупных/высоконагруженных кластеров Kubernetes рекомендует вынести события в отдельный кластер etcd через `--etcd-servers-overrides`:

```bash
# В манифесте kube-apiserver:
--etcd-servers=https://etcd-app-0:2379,https://etcd-app-1:2379,https://etcd-app-2:2379
--etcd-servers-overrides="/events#https://etcd-events-0:2379,https://etcd-events-1:2379,https://etcd-events-2:2379"
```

Формат: `group/resource#servers` (несколько servers через `;`). API-сервер при этом добавляет отдельные health-эндпоинты `etcd-override-N` / `etcd-override-readiness-N`.

### Настройка Encryption at Rest

```yaml
# /etc/kubernetes/encryption-config.yaml
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources:
      - secrets
    providers:
      - aescbc:
          keys:
            - name: key1
              secret: <base64-encoded-32-byte-key>
      - identity: {}
```

```bash
# Флаг kube-apiserver:
kube-apiserver --encryption-provider-config=/etc/kubernetes/encryption-config.yaml
# Горячая перезагрузка конфига без рестарта API-сервера:
kube-apiserver --encryption-provider-config=/etc/kubernetes/encryption-config.yaml \
  --encryption-provider-config-automatic-reload=true
```

**Важно:** шифрование выполняет kube-apiserver до записи — etcd хранит уже зашифрованные данные. Без `EncryptionConfiguration` (и ключей KMS) расшифровать снапшот невозможно. Детали (KMS v2 envelope encryption, ротация ключей) — в [Хранении Secret в etcd](../Kubernetes/Base/secrets/etcd_storage.md) и [Безопасности](./security.md).

### Ротация сертификатов etcd

etcd в kubeadm использует сертификаты из `/etc/kubernetes/pki/etcd/`:
- **server.crt** — серверный сертификат etcd (клиенты подключаются к 2379).
- **peer.crt** — peer-сертификат (между узлами etcd, порт 2380).
- **ca.crt** — корневой CA etcd.
- **healthcheck-client.crt** — клиент для health-проверок.
- Плюс **apiserver-etcd-client.crt** (в `/etc/kubernetes/pki/`) — клиент API-сервера.

```bash
# Проверить срок действия
openssl x509 -in /etc/kubernetes/pki/etcd/server.crt -noout -dates
# → notAfter=...

# Ротация (kubeadm)
kubeadm certs renew all
```

При ручной ротации перезапустите: etcd Static Pod и kube-apiserver (он использует `apiserver-etcd-client`).

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `etcdserver: client certificate is not trusted` | Сертификат API-сервера не подписан etcd CA | Проверить `--etcd-cafile` и `apiserver-etcd-client.crt` |
| `etcdserver: no leader` | Потеря кворума | `kubectl get pods -n kube-system -l component=etcd`; сеть; `etcdctl endpoint health --cluster` |
| `context deadline exceeded` при `kubectl get pods` | API-сервер не может подключиться к etcd | `etcdctl endpoint health`; сертификаты; `curl -k https://127.0.0.1:6443/healthz/etcd` |
| etcd pod перезапускается | Ошибка конфигурации, OOM, повреждение WAL | `kubectl logs`; `df -h`; `etcd-dump-logs` |
| `etcdserver: assign ids error: the member count is unequal` / `etcdserver: assign ids error: unmatched member while checking PeerURLs` | Неверный `--initial-cluster` (состав кластера или peer URL) | Проверить манифест; peer URLs всех узлов |
| `database space exceeded` (NOSPACE) | БД достигла `--quota-backend-bytes` (дефолт 2GB) | Компакция + дефрагментация; увеличить квоту (см. [etcd_operations](../Kubernetes/Concepts/etcd_operations.md)) |
| `etcdserver: request is too large` | Объект > `--max-request-bytes` (дефолт 1.5MB) | Разбить объект; увеличить лимит |
| `mvcc: required revision has been compacted` | Watcher отстал от компакции | Перезапросить с свежей `resourceVersion`; увеличить интервал компакции |

Подробный troubleshooting — в [Систематическом troubleshooting](./troubleshooting.md) и [etcd_operations](../Kubernetes/Concepts/etcd_operations.md).

---

## Best Practices

- **Отдельный диск для etcd:** `data-dir` не на общем диске с ОС; предпочтительно данные и WAL на разных дисках, NVMe SSD (p99 `fsync` < 10мс).
- **Static Pod, а не Deployment:** etcd должен быть Static Pod для прямого управления kubelet.
- **Peer TLS обязательно:** без шифрования peer-соединений данные передаются в открытом виде.
- **Снапшоты регулярно:** автоматические снапшоты (CronJob/крон) + перед каждым обновлением; проверять целостность (`etcdutl snapshot status`).
- **Не трогайте etcd напрямую:** все изменения только через API-сервер (оптимистичная блокировка через `resourceVersion`).
- **Управляйте манифестом через kubeadm/IaC:** не редактируйте Static Pod вручную.
- **Мониторьте:** `etcd_server_has_leader`, `etcd_disk_wal_fsync_duration_seconds` p99, `etcd_mvcc_db_total_size_in_bytes`/квота. Метрики — на порту 2381 (см. [Мониторинг etcd](./etcd_monitoring.md)).

---

## Edge Cases

- **Static Pod и `hostPath`:** `hostPath` (`/var/lib/etcd`, `/etc/kubernetes/pki/etcd`) должен существовать на всех control-plane узлах.
- **Смена IP узла:** при изменении IP control-plane узла обновите `--initial-cluster` на ВСЕХ узлах и перезапустите etcd.
- **etcd и containerd:** при общей диске высокая нагрузка на контейнеры повышает iowait для etcd.
- **Kubelet не видит Static Pod:** если kubelet не может прочитать манифест (права), etcd не запустится и Control Plane не стартует.
- **EtcdRangeStream (K8s 1.37):** при gate `EtcdRangeStream` (Beta, включён по умолчанию) и etcd 3.7+ kube-apiserver читает большие коллекции потоком (RangeStream), снижая пиковое потребление памяти. При `Unimplemented` от бэкенда — автоматический откат на постраничное чтение. Потоковые чтения логируются как `operation="listStream"` в `etcd_request_duration_seconds` — обновите дашборды, фильтрующие `operation="list"`.
- **Требования control-plane:** kubeadm требует ≥2 CPU и ≥1700 MB RAM на control-plane узле (`ControlPlaneNumCPU`, `ControlPlaneMem`).

---

## См. также

* **[Конфигурация и развертывание](./configuration_and_deployment.md)** — Static Pod и systemd.
* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — stacked vs external etcd, кворум.
* **[Безопасность](./security.md)** — TLS и Encryption at Rest.
* **[Совместимость версий](./version_compatibility.md)** — матрица K8s ↔ etcd.
* **[Аварийное восстановление](./emergency_recovery.md)** — `--force-new-cluster` и DR.
* **[Лимиты и ограничения](./limits_and_constraints.md)** — size limits и capacity planning.
* **[Мониторинг etcd](./etcd_monitoring.md)** — метрики и алерты.
* **[Maintenance API](./maintenance_api.md)** — gRPC maintenance endpoint.
* **[Внутреннее устройство Watch и Lease](./watch_lease_internals.md)** — механика watch/lease, используемая в K8s.
* **[Практические сценарии etcd в K8s](../Kubernetes/Concepts/etcd_operations.md)** — etcdctl, компакция, дефрагментация, NOSPACE, бэкап/восстановление.
* **[Обзор etcd в K8s](../Kubernetes/Concepts/etcd_overview.md)** — MVCC, Raft, топологии.
