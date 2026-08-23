# etcd в Kubernetes: интеграция и эксплуатация

**etcd** — это хранилище состояния Kubernetes. Понимание того, как K8s использует etcd, какие данные хранятся в нём и как обслуживать etcd в кластере, критично для любого SRE/Platform Engineer.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Static Pod** | Под, управляемый kubelet напрямую через файлы в `/etc/kubernetes/manifests`. Стандартный способ запуска etcd в K8s. |
| **Control Plane** | Компоненты управления кластером: kube-apiserver, kube-controller-manager, kube-scheduler, etcd. |
| **Stacked etcd** | etcd, запущенный на тех же узлах, что и Control Plane (архитектура по умолчанию в kubeadm). |
| **External etcd** | Отдельный кластер etcd, не связанный с Control Plane узлами. |
| **Encryption at Rest (K8s)** | Шифрование данных в etcd через KMS или статический ключ. Настраивается в API-сервере, а не в etcd. |
| **Admission Controller** | Компонент API-сервера, который проверяет/изменяет объекты перед записью в etcd. |
| **Informer** | Паттерн в клиентах K8s: подписка на Watch + локальный кэш + вызов reconcile при изменениях. |

---

## Основные концепции

### Что хранится в etcd

etcd хранит **ВСЁ** состояние Kubernetes API:

| Ресурс | Пример |
| :--- | :--- |
| Pods | Спецификации, статусы, nodeName |
| Services | ClusterIP, Endpoints, Selectors |
| ConfigMaps | Данные конфигурации |
| Secrets | Секреты (по умолчанию base64, не зашифрованы!) |
| Deployments/ReplicaSets | Желаемое состояние |
| Nodes | Информация об узлах, условия, capacity |
| RBAC | Roles, RoleBindings, ClusterRoles |
| CRDs | Схемы и данные кастомных ресурсов |
| Events | События (создание, удаление, ошибки) |

**Что НЕ хранится в etcd:**
- Логи подов (логи в filesystem узла или централизованный сбор).
- Данные приложений (PersistentVolumes — метаданные в etcd, данные на диске).
- Статус running подов (kubelet управляет подом локально, статус синхронизируется с API).

### Архитектура: Stacked vs External etcd

| Аспект | Stacked etcd | External etcd |
| :--- | :--- | :--- |
| **Развёртывание** | На тех же узлах, что и Control Plane | Отдельные узлы/кластер |
| **Изоляция** | Нет (общие ресурсы CPU/RAM/disk) | Да (отдельные диски, сеть) |
| **Надёжность** | Зависит от Control Plane | Независима |
| **Сложность** | Ниже (kubeadm разворачивает автоматически) | Выше (отдельное обслуживание) |
| **Рекомендация** | Малые/средние кластеры (< 100 узлов) | Production > 100 узлов,Critical workloads |

### Static Pod манифест etcd

```yaml
# /etc/kubernetes/manifests/etcd.yaml
apiVersion: v1
kind: Pod
metadata:
  name: etcd
  namespace: kube-system
spec:
  containers:
  - name: etcd
    image: registry.k8s.io/etcd:3.7.1
    command:
    - etcd
    - --config-file=/etc/etcd/etcd.conf.yml
    - --listen-client-urls=https://127.0.0.1:2379
    - --advertise-client-urls=https://127.0.0.1:2379
    - --listen-peer-urls=https://127.0.0.1:2380
    - --initial-advertise-peer-urls=https://<NODE_IP>:2380
    - --initial-cluster=node1=https://<NODE1_IP>:2380,node2=https://<NODE2_IP>:2380,node3=https://<NODE3_IP>:2380
    - --initial-cluster-state=existing
    - --initial-cluster-token=etcd-cluster-1
    volumeMounts:
    - name: etcd-data
      mountPath: /var/lib/etcd
    - name: etcd-conf
      mountPath: /etc/etcd
    - name: pki
      mountPath: /etc/kubernetes/pki/etcd
      readOnly: true
  volumes:
  - name: etcd-data
    hostPath:
      path: /var/lib/etcd
  - name: etcd-conf
    hostPath:
      path: /etc/etcd
  - name: pki
    hostPath:
      path: /etc/kubernetes/pki/etcd
```

**Важно:** При изменении этого манифеста kubelet автоматически перезапустит etcd. Это может вызвать кратковременную недоступность кластера.

### Взаимодействие API-сервера и etcd

```
[ kubectl ] → [ kube-apiserver ] → [ etcd ]
     ↑                                    |
     └──────── Watch / Informer ──────────┘
```

**Поток записи (Write Path):**
1. `kubectl apply` → gRPC request к kube-apiserver.
2. API-сервер: аутентификация → авторизация → Admission Control.
3. API-сервер записывает объект в etcd (gRPC Put).
4. etcd: Raft replication → commit → apply → ответ API-серверу.
5. API-сервер отвечает клиенту.

**Поток чтения (Read Path):**
1. Контроллер (Deployment, Node) создаёт Informer.
2. Informer подписывается на Watch в API-сервере.
3. API-сервер запрашивает данные из etcd (с кэшированием).
4. При изменении etcd → API-сервер → Watch event → Informer → reconcile.

### Certificate Rotation

etcd в Kubernetes использует несколько сертификатов:
- **etcd/server.crt** — client cert (API-сервер подключается к etcd).
- **etcd/peer.crt** — peer cert (между узлами etcd).
- **ca.crt** — корневой CA.

```bash
# Проверить срок действия
openssl x509 -in /etc/kubernetes/pki/etcd/server.crt -noout -dates

# Ротация (kubeadm)
kubeadm certs renew all
# Или вручную: сгенерировать новые сертификаты, перезапустить Static Pod
```

**Важно:** При ручной ротации сертификатов необходимо перезапустить:
1. etcd Static Pod.
2. kube-apiserver (он использует etcd client certs).

---

## Практические сценарии

### Проверка здоровья etcd в Kubernetes

```bash
# Через kubectl
kubectl get pods -n kube-system -l component=etcd
# → etcd- control-plane — Running

# Проверить логи
kubectl logs -n kube-system etcd- control-plane -c etcd --tail=100

# Проверить endpoint health (с TLS)
ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint health --cluster
```

### Создание снапшота изнутри кластера

```bash
# Через kubectl exec в etcd pod
kubectl exec -n kube-system etcd- control-plane -c etcd -- \
  etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /var/lib/etcd/backup.db

# Скопировать снапшот на локальную машину
kubectl cp kube-system/etcd-control-plane:/var/lib/etcd/backup.db ./etcd-backup.db
```

### Настройка Encryption at Rest в Kubernetes

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
# Перезапустить kube-apiserver с новым флагом
kube-apiserver --encryption-provider-config=/etc/kubernetes/encryption-config.yaml
```

**Важно:** Это шифрование на уровне API-сервера, а не etcd. etcd видит данные в зашифрованном виде.

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `etcdserver: client certificate is not trusted` | Сертификат API-сервера не подписан тем же CA, что и etcd | Проверить `ca.crt` в `/etc/kubernetes/pki/etcd` |
| `etcdserver: no leader` | Потеря кворума | Проверить `kubectl get pods -n kube-system`; проверить network |
| `context deadline exceeded` при `kubectl get pods` | API-сервер не может подключиться к etcd | Проверить `etcdctl endpoint health`; проверить сертификаты |
| etcd pod перезапускается | Ошибка в конфигурации, нехватка памяти, повреждение WAL | Проверить `kubectl logs`; проверить `df -h`; проверить `etcdutl wal verify` |
| `failed to find member` | Неверный `--initial-cluster` в манифесте | Проверить Static Pod манифест; убедиться, что все peer URLs корректны |

---

## Best Practices

- **Отдельный диск для etcd:** Никогда не размещайте `data-dir` на общем диске с ОС или другими сервисами.
- **Static Pod, а не Deployment:** etcd должен быть Static Pod для прямого управления kubelet.
- **Peer TLS — обязательно:** Без шифрования peer-соединений данные передаются в открытом виде.
- **Снапшоты через CronJob:** Настройте автоматические снапшоты (каждые 15 минут) и выгрузку в S3.
- **Не изменяйте Static Pod вручную:** Используйте `kubeadm` или IaC (Terraform, Ansible) для управления конфигурацией.

---

## Edge Cases

- **Static Pod и `hostPath`:** Убедитесь, что `hostPath` существует на всех control plane узлах, иначе Pod не запустится.
- **Смена IP узла:** При изменении IP control plane узла необходимо обновить `--initial-cluster` на ВСЕХ узлах.
- **etcd и containerd:** Если containerd хранит данные на том же диске, что и etcd, при высокой нагрузке на контейнеры может повышаться iowait для etcd.
- **Kubelet не видит Static Pod:** Если kubelet не может прочитать манифест (права доступа), etcd не запустится, и Control Plane не стартует.

---

## См. также

* **[Конфигурация и развертывание](./configuration_and_deployment.md)** — Static Pod и systemd.
* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — stacked vs external etcd.
* **[Безопасность](./security.md)** — TLS и Encryption at Rest.
* **[Совместимость версий и обновление](./version_compatibility.md)** — таблица K8s ↔ etcd версий.
* **[Аварийное восстановление](./emergency_recovery.md)** — `--force-new-cluster` и DR.
* **[Лимиты и ограничения](./limits_and_constraints.md)** — size limits и capacity planning.
* **[Мониторинг etcd](./etcd_monitoring.md)** — метрики и алерты.
* **[Maintenance API](./maintenance_api.md)** — gRPC maintenance endpoint.
