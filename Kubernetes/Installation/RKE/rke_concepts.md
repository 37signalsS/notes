# RKE: Основные концепции

> [!WARNING]
> **RKE1 достиг конца жизненного цикла (EOL) 31 июля 2025 года.** 
> Поддержка прекращена, основное внимание Rancher Labs полностью переключено на **RKE2**. Эксплуатация допускается только для существующих сред с обязательным планом миграции.

## Определения

**RKE (Rancher Kubernetes Engine)** — это Docker-ориентированный дистрибутив Kubernetes. Ключевая особенность заключается в том, что все компоненты управления (control plane) и рабочие компоненты (kubelet, proxy) запускаются как обычные Docker-контейнеры.

**rke-tools** — вспомогательный образ контейнера, используемый RKE для выполнения системных операций на узлах (подготовка конфигураций, ротация сертификатов, создание снимков etcd).

**cluster.rkestate** — файл состояния кластера в формате JSON. Содержит полную копию `cluster.yml`, сгенерированные сертификаты и ключи. Без этого файла обновление или модификация кластера через RKE CLI невозможны.

**kube_config_cluster.yml** — файл конфигурации kubectl, содержащий адрес API-сервера и сертификаты аутентификации администратора. Этот файл необходим для управления кластером через kubectl.

## Базовые концепции

### Архитектурные принципы

RKE работает по принципу "инфраструктура как код", где конечное состояние кластера описывается в YAML.

* **Зависимость от Docker:** RKE требует наличия установленного Docker Engine на всех узлах. Утилита взаимодействует с Docker через сокет `/var/run/docker.sock`. Это означает, что Docker должен быть доступен на хосте и настроен для удаленного доступа (для RKE CLI).

* **Управление через SSH:** RKE CLI подключается к узлам по SSH, проверяет версию Docker и запускает необходимые контейнеры компонентов. SSH-туннели используются для безопасного развертывания компонентов, что минимизирует количество открытых портов на узлах.

* **Статические сертификаты:** RKE самостоятельно генерирует все необходимые TLS-сертификаты для внутренних коммуникаций и сохраняет их в файле состояния. Сертификаты генерируются при первом запуске `rke up` и автоматически ротируются при обновлении кластера.

### Механизм работы Docker-based деплоя

Когда RKE выполняет `rke up`, происходит следующий процесс:

1. **Подготовка узлов:** RKE подключается к каждому узлу по SSH и проверяет:
   - Версию Docker (должна быть из списка поддерживаемых)
   - Наличие необходимых портов
   - Доступность файловой системы

2. **Запуск контейнеров:** На каждом узле RKE запускает Docker-контейнеры с компонентами Kubernetes:
   - **Control Plane:** kube-apiserver, kube-controller-manager, kube-scheduler, kube-proxy
   - **etcd:** etcd (если узел имеет роль etcd)
   - **Worker:** kubelet, kube-proxy

3. **Настройка сети:** RKE разворачивает CNI-плагин (Canal по умолчанию) как Kubernetes-ресурсы сразу после запуска Control Plane.

4. **Развертывание аддонов:** После готовности Control Plane автоматически устанавливаются критические аддоны (CoreDNS, Ingress Controller, Metrics Server).

### Сравнение RKE с другими дистрибутивами

| Аспект | RKE (RKE1) | RKE2 (Next Gen) | kubeadm | K3s | MicroK8s |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Среда выполнения (Runtime)** | Docker | containerd | Любой CRI (containerd/CRI-O) | containerd | containerd |
| **Метод запуска** | Docker-контейнеры | Системные сервисы + статические поды | Статические поды (Static Pods) | Системный сервис | Системный сервис (Snap) |
| **Конфигурация** | Один файл `cluster.yml` | Конфиг-файлы + CLI флаги | CLI флаги + ConfigMaps | Конфиг-файлы + CLI | Конфигурация через Snap |
| **Управление узлами** | SSH доступ от имени RKE CLI | Локальный запуск на узле | Локальный запуск `kubeadm join` | Локальный запуск | Локальный запуск |
| **Безопасность** | Базовая | Высокая (CIS Hardened по умолчанию) | Зависит от пользователя | Средняя | Средняя |
| **Целевая среда** | Bare Metal, VM | Bare Metal, VM, Edge | Bare Metal, VM | Edge, IoT, Dev | Dev, Bare Metal |
| **Зависимости** | Docker | Минимальные | Минимальные | Минимальные | Snap |

### Роли узлов (Node Roles)

В RKE узел может совмещать несколько ролей:

1. **etcd:** Хранилище состояния. Требуется нечетное количество (1, 3, 5) для обеспечения кворума. etcd отвечает за хранение всех данных кластера, включая конфигурации, секреты и состояние подов.

2. **controlplane:** Запуск API Server, Scheduler, Controller Manager. Отвечает за управление кластером, планирование подов и поддержание желаемого состояния.

3. **worker:** Запуск пользовательских нагрузок (Kubelet, Proxy). Рабочие узлы фактически выполняют контейнеры приложений.

**Рекомендации по развертыванию:**

| Тип среды | Рекомендованная конфигурация |
| :--- | :--- |
| **Development/Testing** | 1 узел: controlplane + etcd + worker |
| **Small Production** | 3 узла: controlplane + etcd (3 шт.), workers (1-3 шт.) |
| **Medium Production** | 5+ узлов: controlplane (3 шт.), etcd (3 шт.), workers (3+ шт.) |
| **Large Production** | Выделенные etcd кластеры (5-7 узлов), controlplane (3+), workers (10+) |

> [!IMPORTANT]
> Для production-сред рекомендуется выделять etcd на отдельные узлы и не совмещать с controlplane. Совмещение etcd и controlplane допустимо только для dev/test сред.

### Сетевое взаимодействие (CNI)

RKE поддерживает несколько плагинов, которые разворачиваются как Kubernetes-ресурсы сразу после запуска Control Plane:

* **Canal (по умолчанию):** Гибрид Flannel (для VXLAN сети) и Calico (для сетевых политик). Самый популярный выбор для RKE. Обеспечивает L3-сеть с поддержкой NetworkPolicy.

* **Flannel:** Простая L3-сеть, не поддерживает сетевые политики. Подходит для простых сред без требований к изоляции подов на сетевом уровне.

* **Calico:** Полноценная поддержка политик и BGP. Поддерживает как L3 (IP-in-IP), так и L2 (pure L2 bridging) режимы. Более сложный в настройке, но提供更多 функциональности.

* **Weave:** Поддержка шифрования трафика "из коробки". Использует mesh-топологию для связи узлов.

**Выбор CNI-плагина:**

| Плагин | Сетевые политики | Шифрование | Сложность | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **Canal** | Да | Нет | Низкая | По умолчанию, большинство сценариев |
| **Flannel** | Нет | Нет | Очень низкая | Dev/test, простые среды |
| **Calico** | Да | Опционально | Высокая | Высокие требования к политикам |
| **Weave** | Да | Да | Средняя | Требования к шифрованию |

### Системные аддоны (Add-ons)

RKE автоматически управляет жизненным циклом критических компонентов внутри кластера:

* **Ingress:** По умолчанию устанавливается Nginx Ingress Controller в режиме HostNetwork. Поддерживает настройку через опции в `cluster.yml`.

* **DNS:** CoreDNS (в старых версиях KubeDNS). Отвечает за DNS-резолвинг сервисов внутри кластера.

* **Metrics Server:** Для работы HPA (Horizontal Pod Autoscaler). Собирает метрики использования ресурсов подами и нодами.

**Кастомизация аддонов через cluster.yml:**

```yaml
ingress:
  provider: nginx
  options:
    use-forwarded-headers: "true"
    compute-full-forwarded-for: "true"
  node_selector:
    node-role: ingress
  tolerations:
    - key: "node-role.kubernetes.io/ingress"
      operator: "Exists"
      effect: "NoSchedule"

dns:
  provider: coredns
  # Опции для CoreDNS
  options:
    cache: "30"
    prefetch: "true"

monitoring:
  provider: metrics-server
```

## Практические сценарии

### Структура конфигурации (cluster.yml)

Основной файл содержит следующие ключевые блоки:

```yaml
# Версия конфигурации
version: v1.3.0

# Имя кластера (для идентификации)
cluster_name: "production-cluster"

# Узлы кластера
nodes:
  - address: 192.168.1.10
    internal_address: 10.0.0.10  # Для NAT-сред
    user: ubuntu
    role: [controlplane, etcd]
    ssh_key_path: ~/.ssh/id_rsa
    ssh_cert_path: ~/.ssh/id_rsa-cert.pub  # Опционально
    docker_version: "20.10"
    
  - address: 192.168.1.11
    user: ubuntu
    role: [worker]
    ssh_key_path: ~/.ssh/id_rsa
    labels:
      app: web-server
    taints:
      - key: "dedicated"
        value: "web"
        effect: "NoSchedule"

# Копии etcd (для resilience)
etcd:
  snapshot: true
  creation: 6h
  retention: 24h
  # Внешний etcd (опционально)
  # external_urls:
  #   - https://etcd1.example.com:2379
  #   - https://etcd2.example.com:2379

# Сервисы Kubernetes
services:
  etcd:
    snapshot: true
    creation: 6h
    retention: 24h
    # Квота на размер etcd (в байтах)
    quota_backend_bytes: 8589934592  # 8GB
    # Таймауты
    heartbeat_interval: 500
    election_timeout: 5000
    
  kube-api:
    service_cluster_ip_range: 10.43.0.0/16
    service_node_port_range: 30000-32767
    # Extra Args
    extra_args:
      event-ttl: "168h"
      service-account-lookup: "true"
      
  kube-controller:
    cluster_cidr: 10.42.0.0/16
    service_cluster_ip_range: 10.43.0.0/16
    extra_args:
      terminated-pod-gc-threshold: "100"
      
  kubelet:
    cluster_dns_server: 10.43.0.0/16
    # Ограничения ресурсов
    extra_args:
      max-pods: "110"
      image-gc-high-threshold: "85"
      image-gc-low-threshold: "80"

# Сеть
network:
  plugin: canal
  options:
    flannel_backend_type: "vxlan"
    calico_backend: "bird"
  # MTU для сети (важно для VXLAN)
  mtu: 1450

# Аутентификация
authentication:
  strategy: x509
  # Webhook token auth (опционально)
  # webhook:
  #   config_file: webhook-config.yaml

# DNS
dns:
  provider: coredns

# Ingress
ingress:
  provider: nginx
  options:
    use-forwarded-headers: "true"

# Приватный реестр (для оффлайн установки)
private_registries:
  - url: registry.example.com
    user: username
    password: password
    is_default: true

# Дополнительные манифесты (Kubernetes resources)
additional_manifests: manifests/
```

### Безопасность и управление доступом

**Модель безопасности RKE:**

1. **X.509:** Основной метод аутентификации между компонентами. Все компоненты используют TLS-сертификаты для взаимной аутентификации (mTLS).

2. **RBAC:** Включен по умолчанию. Все права доступа внутри кластера управляются через RoleBinding и ClusterRoleBinding.

3. **SSH-туннелирование:** RKE использует SSH-туннели для безопасного развертывания компонентов, что минимизирует количество открытых портов на узлах.

**Требования к SSH-доступу:**

```bash
# 1. Создание ключа для RKE
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa_rke -N ""

# 2. Копирование публичного ключа на узлы
ssh-copy-id -i ~/.ssh/id_rsa_rke.pub user@node-ip

# 3. Проверка доступа
ssh -i ~/.ssh/id_rsa_rke user@node-ip "docker ps"
```

**Сетевые порты для RKE:**

| Порт | Протокол | Назначение | Компонент |
| :--- | :--- | :--- | :--- |
| 22 | TCP | SSH | RKE CLI → узлы |
| 2379 | TCP | etcd client | etcd → API Server |
| 2380 | TCP | etcd peer | etcd → etcd |
| 6443 | TCP | Kubernetes API | API Server ← kubectl |
| 8472 | UDP | VXLAN | Canal/Flannel overlay |
| 9099 | TCP | Canal health | Canal → Prometheus |
| 10250 | TCP | kubelet API | API Server → kubelet |
| 10254 | TCP | metrics-server | Metrics Server |

**Настройка файрвола:**

```bash
# Пример для iptables (на каждом узле)
# Входящие подключения к API Server
iptables -A INPUT -p tcp --dport 6443 -s 10.0.0.0/8 -j ACCEPT

# etcd (только между etcd-узлами)
iptables -A INPUT -p tcp --dport 2379 -s 10.0.0.0/8 -j ACCEPT
iptables -A INPUT -p tcp --dport 2380 -s 10.0.0.0/8 -j ACCEPT

# kubelet API (от controlplane)
iptables -A INPUT -p tcp --dport 10250 -s 10.0.0.0/8 -j ACCEPT

# VXLAN (Canal)
iptables -A INPUT -p udp --dport 8472 -s 10.0.0.0/8 -j ACCEPT
```

## Дополнительная информация

### Жизненный цикл и стратегия миграции

С 2025 года RKE1 считается устаревшим. В 2026 году эксплуатация допускается только в режиме "поддержки до миграции".

**Причины миграции на RKE2:**
1. **Безопасность:** RKE2 имеет встроенное CIS-хардирование, FIPS 140-2 совместимость.
2. **Runtime:** Используется containerd вместо Docker (стандарт индустрии).
3. **Поддержка:** RKE1 более не получает обновлений безопасности.
4. **Экосистема:** Большинство современных инструментов оптимизированы для containerd.

**Шаги миграции на RKE2:**

1. **Подготовка:** Создание нового кластера RKE2 параллельно существующему.
2. **Сетевая связность:** Настройка маршрутизации или использование общих балансировщиков.
3. **Перенос данных:** Использование Velero или Rancher Backup для миграции объектов и томов (PV).
4. **Тестирование:** Проверка работоспособности приложений на новом кластере.
5. **Переключение трафика:** Обновление DNS записей или балансировщиков.
6. **Очистка:** После успешного переключения трафика, старый кластер RKE1 удаляется командой `rke remove`.

> [!WARNING]
> Прямого апгрейда "на месте" (in-place) с RKE1 на RKE2 не существует. Требуется полная миграция с переносом ресурсов.

### Типичные проблемы и ограничения RKE1

**Проблема: Зависимость от Docker**

RKE1 требует установленного Docker Engine. Это может быть проблемой в средах, где Docker не поддерживается (например, Ubuntu 22.04+ с Podman по умолчанию).

**Решение:** Установка Docker перед запуском RKE:
```bash
# Установка Docker на Ubuntu
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

**Проблема: SSH-таймауты при плохом соединении**

При нестабильном SSH-соединении между машиной с RKE CLI и узлами могут возникать таймауты.

**Решение:** Настройка SSH-параметров:
```bash
# ~/.ssh/config
Host 192.168.1.*
    ServerAliveInterval 60
    ServerAliveCountMax 3
    ConnectTimeout 30
```

**Проблема: Истечение сертификатов**

Сертификаты RKE истекают через 1 год. Если не выполнить ротацию заблаговременно, кластер перестает работать.

**Решение:** Ротация сертификатов:
```bash
# Ротация всех сертификатов
rke cert rotate --config cluster.yml

# Проверка срока действия сертификатов
openssl x509 -in /etc/kubernetes/ssl/kube-apiserver.crt -noout -dates
```

### Оптимизация производительности

**Для etcd:**
- Используйте SSD/NVMe диски (min 500 IOPS random read/write)
- Выделяйте выделенные узлы (не совмещайте с worker)
- Настройте квоту: `quota_backend_bytes: 8589934592` (8GB)

**Для Control Plane:**
- Минимум 4 CPU, 8 GB RAM на узел
- Настройте `--max-requests-inflight` для API Server при высокой нагрузке

**Для Worker:**
- Рекомендуется 2+ CPU, 4+ GB RAM
- Настройте `kubelet` для оптимизации планирования подов

**Мониторинг кластера:**

```bash
# Проверка состояния узлов
kubectl get nodes -o wide

# Проверка системных подов
kubectl get pods -n kube-system

# Просмотр использования ресурсов
kubectl top nodes
kubectl top pods -n kube-system

# Проверка логов etcd (на etcd-узлах)
docker logs etcd 2>&1 | tail -100
```

---

**См. также:**
* [RKE: Управление и поиск неисправностей](./rke_management_scenarios.md)
* [RKE: Установка kubectl и настройка доступа](./rke_kubectl_setup.md)
* [etcd: Архитектура и концепции](../../etcd/architecture-and-concepts.md)
