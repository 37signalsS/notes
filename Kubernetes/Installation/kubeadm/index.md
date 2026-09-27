# Установка Kubernetes через kubeadm

## Определения

**kubeadm** — официальная CLI-утилита для создания и управления жизненным циклом кластеров Kubernetes. Она автоматизирует сложные задачи, такие как генерация сертификатов, настройка статических подов Control Plane и создание токенов для присоединения узлов.

**CRI (Container Runtime Interface)** — стандарт интерфейса для взаимодействия `kubelet` со средой выполнения контейнеров. В современных версиях (v1.24+) поддержка Docker через `dockershim` удалена, рекомендуется использовать `containerd` или `CRI-O`.

**CNI (Container Network Interface)** — стандарт интерфейса для сетевых плагинов (Calico, Cilium, Flannel), обеспечивающих сетевую связность между подами и узлами.

**Control Plane (Узел управления)** — набор компонентов (API-сервер, планировщик, контроллеры), управляющих состоянием кластера. В кластерах, развернутых через `kubeadm`, компоненты запускаются как **Static Pods** на мастер-узлах.

**Worker Node (Рабочий узел)** — узел кластера, предназначенный для запуска пользовательских нагрузок. На нем обязательно работают `kubelet` и `kube-proxy`.

**Static Pods** — поды, управляемые напрямую `kubelet` на конкретном узле, без участия API-сервера. Используются для запуска основных компонентов Kubernetes на Control Plane.

**kubeadm config (YAML)** — механизм конфигурации кластера через декларативные файлы, позволяющий тонко настраивать параметры компонентов (например, дополнительные SAN для сертификатов или флаги API-сервера).

**etcd** — высокодоступное распределённое хранилище ключ-значение, являющееся «истиной» кластера. Все объекты Kubernetes (Pods, Services, ConfigMaps) хранятся в `etcd`. Подробнее: [etcd — концепции](../Concepts/etcd_overview.md).

**kubelet** — агент, работающий на каждом узле кластера. Отвечает за запуск контейнеров через CRI, проверку здоровья подов и поддержание желаемого состояния, объявленного API-сервером.

**kube-proxy** — сетевой агент, управляющий правилами маршрутизации трафика к подам. Поддерживает режимы `iptables`, `ipvs` и `nftables` (рекомендуется с v1.31+).

---

## Основные концепции

### Архитектура kubeadm: что происходит «под капотом»

При выполнении `kubeadm init` или `kubeadm join` утилита выполняет набор атомарных фаз, которые можно запускать по отдельности для отладки:

```bash
# Просмотр доступных фаз
kubeadm init --help | grep phase

# Запуск отдельной фазы (например, только preflight)
kubeadm init phase preflight
```

**Основные фазы инициализации:**

1. **Preflight**: Проверка системы (ядро, RAM, CPU, порты, swap).
2. **Certs generation**: Создание TLS-сертификатов в `/etc/kubernetes/pki` (CA, apiserver, etcd, front-proxy).
3. **Kubeconfig generation**: Генерация конфигов для `admin.conf`, `kubelet.conf`, `controller-manager.conf`, `scheduler.conf`.
4. **Control plane preparation**: Создание манифестов статических подов в `/etc/kubernetes/manifests`.
5. **etcd initialization**: Запуск локального etcd (если не настроен внешний).
6. **Wait control plane**: Ожидание готовности API-сервера.
7. **Upload-config**: Загрузка конфигурации в ConfigMap `kubeadm-config`.
8. **Mark-control-plane**: Установка меток и Taints на мастер-узел.
9. **Bootstrap-token**: Генерация токенов для присоединения узлов.
10. **Addon**: Деплой CoreDNS и kube-proxy.

### Компоненты Control Plane

В кластере, развернутом через `kubeadm`, следующие компоненты работают как **Static Pods**:

| Компонент | Назначение | Манифест |
| :--- | :--- | :--- |
| **kube-apiserver** | Центральный шлюз для всех запросов (kubectl, kubelet, контроллеры). Единственный компонент, взаимодействующий с etcd. | `/etc/kubernetes/manifests/kube-apiserver.yaml` |
| **etcd** | Распределённое хранилище всех данных кластера. Использует алгоритм консенсуса Raft. | `/etc/kubernetes/manifests/etcd.yaml` |
| **kube-scheduler** | Назначает поды на узлы на основе ресурсов, политик и ограничений. | `/etc/kubernetes/manifests/kube-scheduler.yaml` |
| **kube-controller-manager** | Управляет контроллерами (Deployment, ReplicaSet, Node, Service, Endpoint). | `/etc/kubernetes/manifests/kube-controller-manager.yaml` |
| **cloud-controller-manager** | (Опционально) Интеграция с облачными провайдерами. Не используется bare-metal. | `/etc/kubernetes/manifests/cloud-controller-manager.yaml` |

**Ключевые особенности Static Pods:**
- Управляются `kubelet` напрямую через манифесты в `/etc/kubernetes/manifests`.
- API-сервер видит их как Read-Only объекты (зеркалирует в `node.status.images`).
- `kubectl drain` **не** останавливает Static Pods — для их удаления нужно физически удалить манифест.
- При падении Static Pod `kubelet` автоматически перезапускает его.

### Жизненный цикл кластера kubeadm

Процесс работы с кластером через `kubeadm` делится на следующие фазы:

1.  **Pre-flight checks**: Проверка соответствия системы требованиям (ядро, память, порты).
2.  **Init (Инициализация)**: Создание первого мастера, генерация CA и сертификатов, запуск компонентов Control Plane.
3.  **Join (Присоединение)**: Добавление новых мастер-узлов (для HA) или воркер-узлов с использованием токена.
4.  **Upgrade (Обновление)**: Бесшовное обновление версии кластера без пересоздания.
5.  **Reset (Сброс)**: Удаление всех компонентов Kubernetes с узла и возврат системы в исходное состояние.

**Совместимость и версии (2026):**

| Компонент | Рекомендуемая версия | Поддерживаемые ОС |
| :--- | :--- | :--- |
| **Kubernetes** | v1.36.x (актуальная стабильная) | Ubuntu 22.04+, RHEL 9+, Debian 12+ |
| **containerd** | v2.0+ | Все вышеперечисленные |
| **Linux Kernel** | 5.15+ (рекомендуется 6.x) | Необходима поддержка cgroup v2 |

> **Примечание:** Kubernetes 1.37 уже доступен (v1.37.0), но v1.36 является последней стабильной версией с полной поддержкой. Рекомендуется использовать v1.36.x для production-сред.

### Версионная политика и поддержка

- **Совместимость версий**: `kubeadm` поддерживает установку Kubernetes версии N и N-1 (где N — версия самой утилиты).
- **Поддержка релизов**: Kubernetes поддерживает три последних минорных релиза (N, N-1, N-2).
- **Регулярность обновлений**: Обновления выходят примерно каждые 4 месяца. Рекомендуется обновляться сразу после выхода минорного релиза для получения исправлений безопасности.
- **Матрица совместимости**: Каждая версия `kubeadm` имеет конкретные минимальные версии CRI и ядра. Актуальную таблицу см. в [официальной документации](https://kubernetes.io/releases/version-skew-policy/).

**Feature Gates в v1.36:**
- `NodeLocalCRISocket` — GA (стал стандартным Behavior).
- `ControlPlaneKubeletLocalMode` — GA (удален в v1.36, теперь включен по умолчанию).
- Рекомендуется использовать конфигурационные файлы вместо feature gates для настройки поведения.

### Методы конфигурации

1.  **Флаги командной строки**: Удобны для быстрой установки, но ограничены в настройках.
2.  **Конфигурационные файлы (рекомендуется)**: Использование `InitConfiguration`, `ClusterConfiguration` и `JoinConfiguration` в формате YAML. Это позволяет:
    - Настраивать внешнюю базу `etcd`.
    - Добавлять дополнительные адреса в сертификаты API-сервера.
    - Переопределять параметры `kube-proxy` и `kubelet`.
    - Настройка через YAML обеспечивает воспроизводимость и версионирование конфигурации.

---

## Практические сценарии

### 1. Подготовка инфраструктуры

Перед запуском `kubeadm` необходимо выполнить подготовку узлов:
- Отключение Swap (обязательно).
- Настройка `sysctl` (ip_forward, bridge-nf-call-iptables).
- Установка Container Runtime (`containerd`).
- Установка пакетов `kubelet`, `kubeadm`, `kubectl`.
- **[Полное руководство по подготовке](./kubeadm_installation_guide.md)**.

### 2. Развёртывание базового кластера (Single-node)

Для тестирования и разработки на одном узле:
1. Инициализация: `kubeadm init`.
2. Настройка `kubectl` для текущего пользователя.
3. Установка CNI (например, Calico).
4. Снятие ограничения на запуск подов на мастере:
   ```bash
   kubectl taint nodes --all node-role.kubernetes.io/control-plane-
   ```
- **[Подробная инструкция по инициализации](./cluster_initialization.md)**.

### 3. Отказоустойчивый кластер (High Availability)

Создание production-ready среды с 3+ мастерами:
1. Настройка внешнего балансировщика (HAProxy + Keepalived) для Control Plane Endpoint.
2. Инициализация первого мастера с флагом `--control-plane-endpoint`.
3. Присоединение дополнительных мастеров через `kubeadm join ... --control-plane`.
4. Присоединение воркеров.
- **[Архитектура HA](./ha_concepts.md)**.
- **[Настройка балансировщика](./keepalived_haproxy_setup.md)**.

### 4. Обслуживание и эксплуатация

- **Обновление кластера**: Последовательное обновление `kubeadm`, затем выполнение `kubeadm upgrade plan/apply`.
- **Ротация сертификатов**: Автоматическая проверка и ручное продление через `kubeadm certs check-expiration`.
- **Добавление узлов**: Генерация нового токена при истечении старого: `kubeadm token create --print-join-command`.

### 5. Масштабирование кластера

**Добавление Worker-узлов:**
```bash
# На новом узле (после установки пакетов kubeadm/kubelet/containerd):
sudo kubeadm join <control-plane-endpoint>:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash>
```

**Добавление Control Plane узлов (для HA):**
```bash
# На новом мастере:
sudo kubeadm join <control-plane-endpoint>:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <certificate-key>
```

**Удаление узла:**
```bash
# На Control Plane:
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data
kubectl delete node <node-name>

# На удаляемом узле:
sudo kubeadm reset --force
sudo rm -rf /etc/kubernetes/ /var/lib/etcd/ /var/lib/kubelet/
```

### 6. Backup и восстановление

**Резервное копирование etcd (критически важно для disaster recovery):**
```bash
# Создание снапшота etcd
ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-snapshot-$(date +%Y%m%d).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# Проверка снапшота
ETCDCTL_API=3 etcdctl snapshot status /backup/etcd-snapshot-$(date +%Y%m%d).db --write-out=table
```

**Восстановление etcd:**
```bash
# 1. Остановите etcd и API-сервер на всех узлах
sudo systemctl stop kubelet

# 2. Восстановите данные из снапшота
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-snapshot-20240101.db \
  --data-dir=/var/lib/etcd-restored \
  --name=<etcd-member-name> \
  --initial-cluster=<etcd-member-name>=https://<ip>:2380 \
  --initial-advertise-peer-urls=https://<ip>:2380

# 3. Обновите конфигурацию etcd и перезапустите
```

**Автоматизация бэкапов (cron):**
```bash
# Добавьте в crontab:
0 2 * * * /usr/local/bin/etcd-backup.sh >> /var/log/etcd-backup.log 2>&1
```

Подробнее: [Backup стратегии](../Operations/backup-strategies.md), [etcd — операции](../Concepts/etcd_operations.md).

### 7. Мониторинг кластера после установки

**Проверка состояния компонентов:**
```bash
# Статус узлов
kubectl get nodes -o wide

# Все поды в kube-system
kubectl get pods -n kube-system -o wide

# Здоровье API-сервера
kubectl get --raw /healthz

# Готовность API-сервера
kubectl get --raw /readyz

# Статус компонентов Control Plane
kubectl get componentstatuses
```

**Мониторинг etcd:**
```bash
# Здоровье etcd
ETCDCTL_API=3 etcdctl endpoint health --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# Статус etcd
ETCDCTL_API=3 etcdctl endpoint status --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key --write-out=table
```

**Установка metrics-server (для HPA и мониторинга ресурсов):**
```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# Если используется самоподписанный сертификат, добавьте флаг --kubelet-insecure-tls
kubectl patch deployment metrics-server -n kube-system --type='json' -p='[
  {"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}
]'
```

Подробнее: [Мониторинг Kubernetes](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md).

---

## Дополнительная информация

### Best Practices для продакшн-среды

1. **Используйте HA для Control Plane**: Минимум 3 мастера с Keepalived/HAProxy или kube-vip.
2. **Регулярно бэкапьте etcd**: Автоматизируйте создание снапшотов и проверяйте восстановление.
3. **Настройте мониторинг**: Установите Prometheus + Grafana для отслеживания метрик кластера.
4. **Используйте Network Policies**: Ограничьте сетевое взаимодействие между подами.
5. **Настройте Pod Security Standards**: Вместо deprecated PodSecurityPolicies.
6. **Включите Audit Logging**: Для отслеживания запросов к API-серверу.
7. **Используйте RBAC**: Минимальные привилегии для сервисных аккаунтов.
8. **Регулярно обновляйте кластер**: Следите за релизами и исправлениями безопасности.
9. **Настройте Resource Quotas**: Для предотвращения исчерпания ресурсов.
10. **Используйте Node Affinity/Taints**: Для правильного размещения критических подов.

### Диагностика типичных проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `kubelet` не запускается | Не отключен Swap или неверный cgroup driver | `swapoff -a`, проверьте `config.toml` в containerd |
| Ошибка `preflight` портов | Порты 6443 или 10250 заняты | Проверьте `netstat -tulpn`, убедитесь, что K8s еще не установлен |
| Поды CNI в статусе ImagePullBackOff | Нет доступа к реестру образов | Проверьте настройки прокси или доступ к `registry.k8s.io` |
| Узлы в статусе NotReady | Не установлен CNI плагин | Проверьте логи `kubelet` и установите Calico/Cilium |
| API-сервер не отвечает | Проблемы с etcd или сертификатами | Проверьте логи API и etcd, валидность сертификатов |
| Поды в CrashLoopBackOff | Ошибка приложения или неверная конфигурация | Проверьте логи пода и events |

**Полезные команды диагностики:**
```bash
# Логи основного агента
journalctl -u kubelet -f

# Просмотр запущенных контейнеров напрямую через CRI
crictl ps -a

# Запуск только проверок без инициализации
kubeadm init phase preflight

# Проверка логов API-сервера
kubectl logs -n kube-system kube-apiserver-<hostname> -f

# Проверка логов etcd
kubectl logs -n kube-system etcd-<hostname> -f

# Проверка событий кластера
kubectl get events --sort-by='.lastTimestamp' -n kube-system

# Проверка использования ресурсов узлов
kubectl top nodes
kubectl top pods -n kube-system
```

### Сравнение CNI-плагинов

| Плагин | Описание | L3/L4 | L7 | NetworkPolicy | Шифрование |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Calico** | Универсальный, поддерживает BGP и VXLAN | L3 | Да | Да | WireGuard |
| **Cilium** | eBPF-оптимизированный, высокая производительность | L3/L4 | Да | Да | IPSec/WireGuard |
| **Flannel** | Простой, только L3 (нет NetworkPolicy) | L3 | Нет | Нет | Нет |
| **Weave** | Автоконфигурирующийся, с шифрованием | L3 | Да | Да | NaCl |

**Рекомендации:**
- **Production**: Calico или Cilium (поддержка NetworkPolicy, шифрование, высокая производительность).
- **Тестирование/Development**: Flannel (простота настройки).
- **Высоконагруженные среды**: Cilium (eBPF, оптимизация для больших кластеров).

### Выбор Container Runtime

| Runtime | Описание | Поддержка CRI | Особенности |
| :--- | :--- | :--- | :--- |
| **containerd** | Промышленный стандарт, рекомендуемый | Да | Широкое сообщество, интеграция с Docker |
| **CRI-O** | Минималистичный, для Kubernetes | Да | Официально поддерживается OpenShift |
| **Docker Engine** | Депрекейтирован (v1.24+) | Через dockershim | Не рекомендуется для нового кластера |

**Рекомендация**: Используйте `containerd` — он является стандартом де-факто для kubeadm-кластеров.

### Схема сетевого взаимодействия

```
┌─────────────────────────────────────────────────────────────┐
│                      Control Plane                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ kube-apiserver│  │   etcd      │  │ kube-scheduler      │ │
│  │   (6443)     │  │ (2379-2380) │  │ kube-controller-mgr │ │
│  └──────┬──────┘  └─────────────┘  └─────────────────────┘ │
│         │                                                    │
│  ┌──────┴──────┐                                            │
│  │  HAProxy    │  (7443) — Control Plane Endpoint           │
│  │  Keepalived │  (VIP: 192.168.1.100)                      │
│  └──────┬──────┘                                            │
└─────────┼───────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│                      Worker Nodes                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │   kubelet   │  │  kube-proxy │  │ CNI Plugin          │ │
│  │   (10250)   │  │ (iptables/  │  │ (Calico/Cilium)     │ │
│  │             │  │   nftables) │  │                     │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Связанные темы

- **Управление сертификатами**: [Certificate Management](../Operations/certificate_management.md) — детальная ротация сертификатов Control Plane.
- **Обновление кластеров**: [Upgrading Clusters](../Operations/upgrading_clusters.md) — подробный процесс перехода между версиями.
- **HA на bare metal**: [HA Overview](../Installation/HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md) — архитектурные нюансы без облачных балансировщиков.
- **etcd — концепции**: [etcd Overview](../Concepts/etcd_overview.md) — архитектура, кворум, репликация.
- **etcd — операции**: [etcd Operations](../Concepts/etcd_operations.md) — снапшоты, defrag, восстановление.
- **Архитектура Control Plane**: [Control Plane Architecture](../Concepts/control_plane_architecture.md) — глубокое погружение в компоненты.
- **Backup стратегии**: [Backup Strategies](../Operations/backup-strategies.md) — резервное копирование etcd и данных кластера.
- **Мониторинг Kubernetes**: [Monitoring & Logging](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md) — Prometheus, Grafana, логирование.
- **Node Maintenance**: [Node Maintenance](../Operations/node_maintenance.md) — обслуживание узлов, drain, cordon.
- **RBAC**: [RBAC Overview](../Security/rbac/rbac_overview.md) — управление доступом в кластере.
- **Pod Security**: [Pod Security Context](../Security/pod_security_context.md) — политики безопасности подов.
- **Внешний etcd**: [External etcd Setup](./external-etcd-setup.md) — настройка внешнего etcd-кластера для kubeadm.
- **Продвинутая конфигурация**: [Advanced kubeadm Configuration](./advanced-kubeadm-configuration.md) — детали YAML-конфигурации, extraArgs, extraVolumes.
- **Troubleshooting kubeadm**: [Diagnostics и troubleshooting](./kubeadm-troubleshooting.md) — расширенная диагностика и решение проблем.

### Ссылки

- [Официальная документация kubeadm](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/)
- [Настройка cgroup drivers](https://kubernetes.io/docs/setup/production-environment/container-runtimes/#cgroup-drivers)
- [Матрица совместимости CNI (Calico)](https://docs.tigera.io/calico/latest/about/supported-releases)
- [Официальная документация containerd](https://containerd.io/)
- [Руководство по CNI](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/network-plugins/)
- [Версионная политика Kubernetes](https://kubernetes.io/releases/version-skew-policy/)
- [Troubleshooting kubeadm](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/troubleshooting-kubeadm/)
