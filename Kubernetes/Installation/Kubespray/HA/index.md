# Kubespray: Развертывание HA-кластера

Индексный документ и обзор методов развертывания высокодоступного (High Availability) кластера Kubernetes с использованием Kubespray. Охватывает выбор метода, предварительные требования, сетевую специфику и команды быстрой проверки. Детальные пошаговые инструкции вынесены в поддокументы.

## Определения

**HA-кластер (High Availability)** — конфигурация Kubernetes с несколькими узлами управления (Control Plane), обычно 3 или 5, предназначенная для устранения единой точки отказа (SPoF). Она обеспечивает непрерывную работу API-сервера и etcd при выходе из строя одного или нескольких узлов.

**Control Plane HA** — архитектурный подход, при котором доступ к API-серверу осуществляется через балансировщик нагрузки (Load Balancer) или плавающий IP (VIP), распределяющий запросы между всеми мастерами.

**VIP (Virtual IP)** — плавающий IP-адрес, обеспечивающий единую точку входа для клиентов (kubectl, CI/CD). Управляемый компонентами HA (kube-vip, Keepalived) автоматически перемещается на активный узел при отказе текущего лидера.

**Кворум** — минимальное количество узлов в распределенной системе (например, etcd), необходимое для принятия решений. Для etcd с N узлами кворум составляет N/2 + 1.

**Kubespray HA** — набор встроенных Ansible-ролей и переменных, автоматизирующих настройку компонентов отказоустойчивости (Keepalived, HAProxy, kube-vip).

---

## Предварительные требования

### Аппаратные требования

HA-кластер с совмещенным etcd (Stacked topology) требует ресурсов на каждый узел Control Plane:

| Роль | Кол-во | CPU | RAM | Диск | Примечание |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Control Plane + etcd** | 3 (нечетное) | 2+ ядра | 4 ГБ+ | SSD 40 ГБ+ | NVMe рекомендуется для etcd |
| **Worker** | 2+ | 2+ ядра | 4 ГБ+ | SSD 40 ГБ+ | Зависит от нагрузки приложений |

> [!IMPORTANT]
> Для etcd критична низкая задержка дисковой подсистемы (IOPS) и стабильность сети между мастерами (латентность < 10 мс). Использование HDD вместо SSD для etcd — распространенная причина деградации кластера.

Для выделенной топологии etcd (External) требуется минимум 3+3 узла: 3 для Control Plane и 3 для etcd. Подробнее: [Топологии etcd](../../Concepts/etcd_overview.md).

### Программные требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| **Ansible** | 2.14+ | Устанавливается на машину управления |
| **Python** | 3.10+ | Требуется для Ansible и Kubespray |
| **ОС (целевые узлы)** | Ubuntu 22.04/24.04, Debian 12, Rocky/Alma 9, RHEL 9/10 | См. [совместимость](../overview.md) |
| **Container Runtime** | containerd v2.x (рекомендуется) | CRI-O как альтернатива |
| **Kubespray** | v2.29+ (для K8s v1.33+) | Актуальная матрица: [Обзор Kubespray](../overview.md) |

### Подготовка машины управления

Развертывание выполняется с отдельной Linux-машины (Control Node):

```bash
# 1. Клонирование Kubespray
git clone --branch v2.31.0 --single-branch https://github.com/kubernetes-sigs/kubespray.git
cd kubespray

# 2. Создание виртуального окружения и установка зависимостей
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Проверка SSH-доступа к целевым узлам (все узлы)
ansible -i inventory/mycluster/hosts.yml all -m ping
# → master-1 | SUCCESS => { "ping": "pong" }
```

### Сетевые требования для HA

| Протокол / Порт | Направление | Назначение |
| :--- | :--- | :--- |
| **TCP 6443** | От клиентов к VIP | Kube-apiserver (внешний порт) |
| **TCP 2379** | Между etcd-узлами | etcd клиентские запросы |
| **TCP 2380** | Между etcd-узлами | etcd пиринг (Raft) |
| **TCP 10250** | Между всеми узлами | Kubelet API |
| **UDP 4789** | Между всеми узлами | VXLAN (если используется overlay-сеть) |
| **Proto 112 (VRRP)** | Между узлами Keepalived | Только для Keepalived (L2) |
| **TCP 179** | Между узлами и маршрутизаторами | BGP (для kube-vip BGP или Calico BGP) |

> [!NOTE]
> Между Control Plane узлами должна быть стабильная связность с латентностью < 10 мс и packet loss < 0.1%. Нестабильная сеть — наиболее частая причина split-brain и потери кворума etcd.

---

## Методы обеспечения отказоустойчивости

Kubespray поддерживает три основных метода. Выбор зависит от сетевой инфраструктуры и требований к доступности.

### 1. kube-vip (Рекомендуемый)

*   **Принцип:** Запускается как Static Pod на каждом мастере до инициализации кластера.
*   **Функции:** Управляет VIP и выполняет роль L4-балансировщика для API-сервера.
*   **Режимы:**
    *   **L2 (ARP)** — для локальных L2-сегментов. Лидер анонсирует VIP через Gratuitous ARP. Простая настройка, работает в большинстве bare-metal сред.
    *   **L3 (BGP)** — для интеграции с маршрутизаторами. Лидер анонсирует маршрут к VIP через BGP-сессию. Подходит для межсетевых топологий.
*   **Преимущества:** Cloud-native подход, отсутствие зависимости от системных демонов ОС, минимальные требования к настройке.
*   **Ограничения:** В L2-режиме VIP работает только в пределах одного L2-сегмента (подсети).

### 2. Keepalived + HAProxy (Классический)

*   **Принцип:** Используются стандартные Linux-сервисы. Keepalived реализует VRRP для управления VIP, HAProxy выполняет L4-балансировку на порт 6443.
*   **Схема портов:** Kubespray настраивает HAProxy на порт `6443` (внешний), а kube-apiserver слушает на порт `6444` (внутренний) для избежания конфликта.
*   **Преимущества:** Проверенная временем стабильность, глубокие health-check API-сервера через HAProxy, широкая документированность.
*   **Особенности:** Требует настройки `net.ipv4.ip_nonlocal_bind` в ядре ОС для привязки VIP к интерфейсу. Необходимо следить за уникальностью `keepalived_virtual_router_id` в пределах сети.

### 3. Локальный nginx-proxy

*   **Принцип:** На каждом узле (worker и master) запускается контейнер с Nginx, который проксирует запросы к API-серверу на список всех мастеров из инвентаря.
*   **Особенности:** Не создает единую точку входа (VIP). Обеспечивает отказоустойчивость связи `kubelet -> apiserver` внутри кластера.
*   **Применение:** Тестовые среды, Edge-кластеры, сценарии где VIP невозможен (например, ограниченная L2-сеть). Часто используется как дополнение к основному методу HA (включается через `loadbalancer_apiserver_localhost: true`).

### Сравнение методов

| Характеристика | kube-vip | Keepalived + HAProxy | nginx-proxy (local) |
| :--- | :--- | :--- | :--- |
| **Среда выполнения** | Static Pods (Kubernetes) | Systemd (Linux services) | Containerd / Docker |
| **Наличие VIP** | Да (L2 или BGP) | Да (VRRP) | Нет |
| **Сложность настройки** | Низкая | Средняя | Минимальная |
| **Время failover** | 1–3 сек | 1–3 сек | N/A (каждый узел проксирует сам) |
| **Dependency** | Нет (только K8s) | Keepalived, HAProxy | Только Container Runtime |
| **Рекомендация** | Production (Bare-metal) | Enterprise / Legacy | Dev / Test / Edge |
| **Одновременный доступ** | Да (VIP) | Да (VIP) | Прямой к мастерам |

---

## Алгоритм выбора метода HA

```
Начало
  │
  ├─ 1. Есть возможность использовать плавающий IP (VIP) в подсети мастеров?
  │     │
  │     ├─ Да → 2. Какой протокол доступен для анонсирования VIP?
  │     │         │
  │     │         ├─ L2 (广播/ARP) → kube-vip (L2 режим) ✅
  │     │         │
  │     │         └─ BGP (маршрутизатор) → kube-vip (BGP режим) ✅
  │     │
  │     └─ Нет → 3. Есть ли доступ к настройке сетевого оборудования (VRRP/proto 112)?
  │               │
  │               ├─ Да → Keepalived + HAProxy ✅
  │               │
  │               └─ Нет → nginx-proxy (локальный прокси на узлах) ✅
  │
  └─ Конец
```

> [!NOTE]
> При использовании любого метода HA критически важно иметь **нечетное количество** узлов в группе `etcd` (3 или 5) для обеспечения кворума. Нечетное число гарантирует, что при Partition'е всегда будет одна группа с кворумом, capable of making progress.

> [!TIP]
> На практике методы часто комбинируют: kube-vip или Keepalived для внешнего VIP + `loadbalancer_apiserver_localhost: true` для локальной балансировки на каждом узле. Такая связка обеспечивает максимальную отказоустойчивость.

---

## Документы раздела

| Документ | Содержание |
| :--- | :--- |
| **[Основные концепции HA](./kubespray_ha_concepts.md)** | Архитектура методов, сетевые потоки, математика кворума etcd, сравнение подходов |
| **[Практика развертывания](./kubespray_ha_deployment.md)** | Пошаговые инструкции, примеры inventory (INI/YAML), переменные group_vars, команды управления |
| **[Дополнительные темы и Troubleshooting](./kubespray_ha_advanced.md)** | Тестирование failover, ротация сертификатов, масштабирование, устранение неполадок |

---

## Быстрая проверка кластера

### Проверка VIP

```bash
# Определение текущего владельца VIP (на каком узле привязан)
ip a show <interface> | grep <VIP_ADDRESS>
# → inet 192.168.1.100/32 scope global eth0

# Для Keepalived: проверка статуса сервиса
systemctl status keepalived
journalctl -u keepalived -f

# Для kube-vip: проверка пода и лидерства
kubectl get pods -n kube-system -l name=kube-vip
kubectl logs -n kube-system -l name=kube-vip --tail=20
# → INFO Node <hostname> is now the leader
```

### Проверка балансировщиков

```bash
# HAProxy: статус бэкендов через Unix-сокет
echo "show stat" | socat stdio /var/run/haproxy/admin.sock | grep -E "kubernetes-api.*UP"

# Nginx-proxy: проверка доступности API через локальный прокси
curl -sk https://localhost:6443/healthz
# → ok
```

### Проверка etcd

```bash
# Кластер etcd: health и статус
kubectl exec -n kube-system -it etcd-master-1 -- etcdctl endpoint health --cluster
# → https://10.0.0.11:2379 is healthy
# → https://10.0.0.12:2379 is healthy
# → https://10.0.0.13:2379 is healthy

kubectl exec -n kube-system -it etcd-master-1 -- etcdctl endpoint status --cluster -w table
# → | ENDPOINT        | VERSION | DB SIZE | IS LEADER | IS LEARNER | ...
# → | 10.0.0.11:2379  | 3.5.12  | 24 MB   | true      | false      | ...
```

### Проверка Kubernetes API через VIP

```bash
# Клиентский запрос к API через VIP
kubectl --server=https://192.168.1.100:6443 get nodes
# → NAME       STATUS   ROLES           AGE   VERSION
# → master-1   Ready    control-plane   10d   v1.31.0
# → master-2   Ready    control-plane   10d   v1.31.0
# → master-3   Ready    control-plane   10d   v1.31.0
# → worker-1   Ready    <none>          10d   v1.31.0
```

---

## Типичные ошибки и решения

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **VIP не назначается на узел** | Заблокирован VRRP (proto 112) в firewall; multicast не работает в L2-сегменте | Разрешить `proto 112` между узлами; для Keepalived перейти на unicast: `keepalived_unicast_peers: [10.0.1.11, 10.0.1.12]` |
| **VIP «висит» на нескольких узлах (split-brain)** | Конфликт `virtual_router_id`; multicast/unicast не доставляет VRRP-пакеты | Проверить уникальность `keepalived_virtual_router_id` в подсети; проверить `tcpdump -i any proto 112` |
| **etcd: потеря кворума** | Нечетное число узлов etcd вышло из строя; нестабильная сеть между мастерами | Восстановление из snapshot: `etcdctl snapshot restore`; см. [Восстановление etcd](../../../../etcd/clustering_and_recovery.md) |
| **API-сервер не отвечает через VIP** | HAProxy не может подключиться к бэкендам; kube-apiserver слушает не на том порту | Проверить `curl -sk https://localhost:6443/healthz` локально; проверить конфигурацию HAProxy |
| **kube-vip не становится лидером** | Нет доступа к API-серверу для Leader Election; RBAC не настроен | Проверить логи `kubectl logs -n kube-system -l name=kube-vip`; убедиться что ServiceAccount и ClusterRoleBinding созданы |
| **Ошибка «dial tcp 6443: connect: connection refused»** | kube-apiserver не запущен или слушает на другом порту | Проверить `systemctl status kube-apiserver` или `crictl ps`; убедиться что порт совпадает с конфигурацией HAProxy |

---

## Лучшие практики

*   **Используйте нечетное число узлов etcd** (3, 5) — это математическое требование для кворума. Два узла etcd не обеспечивают отказоустойчивости.
*   **Разделяйте master и worker узлы** — не запускайте приложения на Control Plane для предотвращения конкуренции за ресурсы с компонентами управления.
*   **Мониторьте etcd в первую очередь** — деградация etcd мгновенно влияет на весь кластер. Настройте алерты на DB size, latency и leader changes.
*   **Регулярно тестируйте failover** — останавливайте по одному узлу Control Plane для проверки, что VIP мигрирует корректно и кластер продолжает работать.
*   **Используйте SSD/NVMe для etcd** — HDD не обеспечивают достаточную IOPS для стабильной работы распределенного хранилища.
*   **Резервируйте etcd** — настройте автоматический snapshot через cron: `etcdctl snapshot save /backup/etcd-$(date +%Y%m%d).db`.
*   **Версионируйте инвентарь в Git** — используйте GitOps для отслеживания изменений в `group_vars` и `inventory`.
*   **Избегайте изменения VIP вручную** — Allow Keepalived/kube-vip управлять миграцией VIP. Ручное изменение приводит к split-brain.

---

## Дополнительная информация

### См. также

- [Обзор Kubespray](../overview.md) — совместимость версий, поддерживаемые компоненты.
- [Базовая установка](../kubespray_install/basic_concepts.md) — системные требования, подготовка ОС.
- [Высокая доступность на Bare-Metal](../../HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md) — общие принципы HA в Kubernetes.
- [Обзор etcd](../../Concepts/etcd_overview.md) — архитектура и управление распределенным хранилищем.

### Внешние ресурсы

- [Kubespray: HA Mode Documentation](https://kubespray.io/#/docs/ha-mode)
- [Kube-vip: Cloud-Native HA Architecture](https://kube-vip.io/)
- [GitHub: Kubernetes-sigs/Kubespray](https://github.com/kubernetes-sigs/kubespray)
