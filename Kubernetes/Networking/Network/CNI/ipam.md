# IPAM (IP Address Management) в Kubernetes

## Определения

**IPAM (IP Address Management) в Kubernetes** — подсистема управления адресным пространством, обеспечивающая жизненный цикл IP-адресов подов (выделение, резервирование, учет и освобождение). В современных реализациях IPAM эволюционировал в **Policy-Driven IPAM**, где распределение адресов зависит от типа нагрузки (Web, Database, Legacy), топологии узлов и требований безопасности.

**Единый реестр сетевых ресурсов (NetBox)** — интеграция сетевой связности кластера с внешними системами инвентаризации (NetBox, Infoblox), обеспечивающая прозрачность сетевой инфраструктуры для смежных ИТ-департаментов.

**Block-Based IPAM** — механизм (используется в Calico), при котором узлам выделяются не фиксированные подсети, а динамические блоки адресов (обычно `/26`). Это позволяет более эффективно использовать адресное пространство в разреженных кластерах.

**Multi-Pool IPAM** — архитектура (стандарт Cilium 1.19+), позволяющая использовать несколько независимых диапазонов IP (CIDR) внутри одного кластера с возможностью их динамического расширения и привязки к конкретным группам узлов.

**Dual-Stack IPAM** — режим работы, при котором поды и сервисы получают адреса обоих протоколов (IPv4 и IPv6) одновременно. В 2026 году является рекомендуемым стандартом для Enterprise-сред из-за исчерпания IPv4-адресов в крупных оверлейных сетях.

---

## Основные концепции

### Жизненный цикл выделения IP

Процесс назначения адреса в современном кластере:

1.  **Kubelet** инициирует создание пода и вызывает основной **CNI-плагин**.
2.  **CNI-плагин** (например, Cilium) проверяет **IPAM Policy** для данного пространства имен или пода.
3.  Система **IPAM** выбирает адрес из соответствующего пула:
    *   **Dynamic:** Автоматически из доступного блока.
    *   **Persistent (KubeVirt):** Привязанный к виртуальной машине и сохраняющийся при миграции между узлами.
    *   **Static:** Указанный в аннотациях пода (требует предварительного резервирования).
4.  Данные о выделении синхронизируются с **External IPAM** (NetBox) через специализированный оператор.
5.  **CNI-плагин** настраивает сетевой стек, и под получает связность.

### Режимы работы IPAM

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| **Integrated (Cilium/Calico)** | Использование CRD или etcd для хранения состояния. Поддерживает динамическое изменение размеров блоков. | Основной режим для высоконагруженных on-prem кластеров. |
| **Cloud-Native (ENI/VNet)** | Использование нативных IP из VPC облачного провайдера. | AWS EKS, Azure AKS, GCP GKE. Прямая маршрутизация без оверлея. |
| **External (NetBox/Infoblox)** | Kubernetes выступает потребителем данных из внешней системы инвентаризации. | Корпоративные среды с жестким контролем сетевого пространства. |
| **Host-local** | Файловое хранение состояния на каждом узле. | Небольшие кластеры, bare-metal инсталляции без сложных CNI. |

### Dual-Stack IPAM

Современные кластеры (Kubernetes 1.23+) поддерживают полноценный Dual-Stack:

*   **Pod Dual-Stack:** Поды получают адреса IPv4 и IPv6 одновременно.
*   **Service Dual-Stack:** Сервисы ClusterIP могут иметь стек обоих протоколов.
*   **Настройка кластера:**
    ```bash
    # Пример конфигурации kubeadm
    apiVersion: kubeadm.k8s.io/v1beta3
    kind: ClusterConfiguration
    networking:
      podSubnet: "10.244.0.0/16,fd00:10:244::/56"
      serviceSubnet: "10.96.0.0/12,fd00:10:96::/112"
    ```
*   **Приоритет трафика:** При наличии обоих стеков Kubernetes предпочитает IPv6 для исходящих соединений (настраивается через `ipFamilyPolicy: PreferDualStack`).

---

## Практические сценарии

### Предварительные требования

#### Аппаратные требования

*   **Процессор:** x86_64 (Intel/AMD) или ARM64.
*   **Память:** Минимум 4 GB RAM на узел; для кластеров >1000 подов рекомендуется 8+ GB (IPAM-состояние и BPF Maps занимают невытесняемую память).
*   **Сеть:** Доступность выделенных подсетей без пересечения с существующей инфраструктурой.

#### Программные требования

*   **Ядро Linux:** Минимум 5.10 для базового режима; рекомендуется 6.1+ для Dual-Stack и современных функций.
*   **Kubernetes:** Версия 1.23+ для Dual-Stack; 1.28+ рекомендуется для полной поддержки ServiceCIDR API.
*   **CNI-плагин:** Calico 3.24+ или Cilium 1.19+.

#### Проверка текущего состояния IPAM

```bash
# Проверка версии Kubernetes
kubectl version --short

# Проверка поддержки Dual-Stack в API
kubectl get --raw='/api/v1' | jq '.serverVersion | .gitVersion'

# Проверка текущего CIDR кластера
kubectl cluster-info dump | grep -i cluster-cidr
```

### 1. Конфигурация host-local IPAM (Calico)

Режим по умолчанию для небольших и средних кластеров.

```yaml
# /etc/cni/net.d/10-calico.conflist
{
  "name": "calico-k8s-network",
  "cniVersion": "0.3.1",
  "plugins": [
    {
      "type": "calico",
      "log_level": "info",
      "log_file_path": "/var/log/calico/cni/cni.log",
      "ipam": {
        "type": "host-local",
        "subnet": "usePodCidr",
        "ranges": [
          [{ "subnet": "10.244.0.0/16" }]
        ]
      },
      "policy": {
        "type": "k8s"
      },
      "kubernetes": {
        "k8s_api_root": "https://10.0.0.10:6443",
        "node_name": "__HOST_NAME__"
      }
    }
  ]
}
```

### 2. Конфигурация Multi-Pool IPAM (Cilium)

```yaml
# CiliumPodIPPool для production
apiVersion: "cilium.io/v2alpha1"
kind: CiliumPodIPPool
metadata:
  name: production-pool
spec:
  ipv4:
    cidrs:
    - "10.0.0.0/16"
    maskSize: 24
  nodeSelector:
    matchLabels:
      node-role.kubernetes.io/worker: "true"
```

### 3. Назначение статического IP (Static IP)

Для баз данных или legacy-сервисов, требующих фиксированного адреса.

**Для Calico:**
```yaml
metadata:
  annotations:
    cni.projectcalico.org/ipAddrs: '["10.0.1.50"]'
```
*Примечание: IP должен входить в разрешенный пул и не быть занятым.*

**Для Cilium (Multi-pool):**
```yaml
metadata:
  annotations:
    ipam.cilium.io/ip-pool: "static-pool-name"
```

### 4. Интеграция с NetBox

NetBox Operator автоматически синхронизирует состояние сети Kubernetes с NetBox:
*   При создании Pod IP помечается в NetBox как `Active`.
*   В метаданных NetBox сохраняется привязка: `Node Name`, `Pod Name`, `Namespace`.
*   При удалении пода статус меняется на `Deprecated` или адрес освобождается.

### 5. IPv6-only архитектура

Лучшие практики при нехватке IPv4:
*   Использование `/48` на весь кластер и `/64` на каждый узел.
*   **DNS64/NAT64:** Обязательная настройка для доступа из IPv6-only кластера к внешним IPv4-репозиториям (Docker Hub, GitHub).
*   Прямая маршрутизация (Native Routing) вместо оверлея для снижения нагрузки на CPU.

### 6. Миграция с Cluster-Pool на Multi-Pool (Cilium 1.20+)

Сценарий актуален при необходимости смены `podCIDR` в работающем кластере (например, из-за пересечения с ЛВС/VPC).

#### Подготовка и миграция Pod IP

Для перехода в режим `multi-pool` без простоя Cilium 1.20 предоставляет специальный флаг миграции.

1.  **Создание нового пула (`CiliumPodIPPool`):**
    ```yaml
    apiVersion: cilium.io/v2alpha1
    kind: CiliumPodIPPool
    metadata:
      name: default
    spec:
      ipv4:
        cidrs:
        - 172.24.0.0/20
        maskSize: 24
    ```

2.  **Обновление Cilium (Helm):**
    ```bash
    helm upgrade cilium cilium/cilium -n kube-system \
      --set ipam.mode=multi-pool \
      --set-string extraConfig.enable-cluster-pool-to-multi-pool-migration=true \
      --set operator.rollOutPods=true \
      --set rollOutCiliumPods=false
    ```
    *   `rollOutCiliumPods=false`: Предотвращает одновременный перезапуск всех агентов.
    *   `enable-cluster-pool-to-multi-pool-migration`: Позволяет Cilium временно понимать старые адреса во время переезда.

3.  **Постепенный перезапуск:**
    *   Поочередный перезапуск `Cilium Agent` на узлах.
    *   Рестарт `CoreDNS` для подхвата новых IP (рекомендуется настроить `PodDisruptionBudget`).
    *   Перезапуск прикладных контейнеров для получения адресов из нового пула.

#### Смена Service IP (Высокий риск)

Если требуется сменить и диапазон сервисов, процедура затрагивает Control Plane:
1.  **Бэкап:** Обязательный бэкап `etcd` и `/etc/kubernetes`.
2.  **Обновление манифестов:** Изменение `--service-cluster-ip-range` в `kube-apiserver` и `kube-controller-manager` на всех мастерах.
3.  **Kubelet:** Обновление `clusterDNS` в `/var/lib/kubelet/config.yaml`.
4.  **Etcd cleanup:** Очистка `/registry/servicecidrs/` в etcd (через `etcdctl`) для удаления старых привязок.
5.  **ServiceCIDR API:** Создание нового объекта `ServiceCIDR` с новым диапазоном.
6.  **Пересоздание сервисов:** Удаление старых сервисов (включая `kubernetes` в `default`) для их пересоздания с новыми IP.

**Внимание:** Смена Service IP вызывает временную потерю связности между компонентами и требует тщательной автоматизации (Ansible/Scripts). Миграция на `multi-pool` необратима.

---

## Диагностика и устранение неполадок

### Поиск утечек IP (IP Leaks) в Calico

Иногда после сбоя узла блоки адресов могут остаться «закрепленными» за несуществующим узлом.
```bash
# Проверка консистентности IPAM
calicoctl ipam check -o report.json

# Очистка осиротевших адресов на основе отчета
calicoctl ipam release --from-report=report.json
```

### Мониторинг использования пулов в Cilium

```bash
# Статус использования пулов (Cilium 1.19+)
cilium status --verbose | grep -A 10 "IPAM"
# → IPAM: 3/3 pools allocated, 0.00% fragmentation

# Список всех пулов в кластере
kubectl get ciliumpodippools
```

### Проверка состояния IPAM в кластере

```bash
# Проверка выделенных IP в Calico
calicoctl ipam show --show-blocks

# Проверка выделенных IP в Cilium
cilium-dbg bpf ipam list
# → вывод списка пулов и использованных адресов

# Проверка конфигурации IPAM через Cilium Operator
kubectl -n kube-system get cm cilium-config -o yaml | grep -i ipam
```

### Типичные проблемы и решения

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Pod в статусе ContainerCreating** | IPAM исчерпан или пул перекрывается | `kubectl describe pod <pod>` → Events: `Failed to allocate`; `calicoctl ipam show` | Расширить пул; проверить отсутствие пересечений CIDR |
| **IP конфликт (ARP конфликт)** | Статический IP уже используется | `arping -D <ip>`; проверка логов CNI | Освободить конфликтующий адрес; использовать аннотации с проверкой |
| **Dual-Stack не работает** | Kubelet или CNI не поддерживает IPv6 | `kubectl get nodes -o wide`; проверка `ipv6` в CNI конфиге | Обновить Kubernetes до 1.23+; настроить `podSubnet` с двумя CIDR |
| **Потеря IP после перезапуска узла** | host-local IPAM без синхронизации | `calicoctl ipam show --show-blocks` | Переход на Integrated IPAM (etcd/CRD) для сохранения состояния |
| **Migration stuck** | Cilium Agent не перешел на новый пул | `cilium status --verbose`; логи `cilium-operator` | Увеличить `rollOutCiliumPods=false`; проверить отсутствие блокировок в `CiliumPodIPPool` |

---

## Рекомендации и очистка

### Рекомендации для production

1.  **Всегда выделяйте Pod CIDR с запасом:** Если планируется 100 узлов по 110 подов, требуется сеть минимум `/16`.
2.  **Используйте Integrated IPAM вместо host-local:** Состояние в etcd/CRD выживает при перезапуске узлов.
3.  **Включите Dual-Stack при наличии IPv6-инфраструктуры:** Это избавляет от проблем с исчерпанием IPv4 в будущем.
4.  **Настройте мониторинг использования пулов:** Регулярно проверяйте `cilium status --verbose` или `calicoctl ipam show`.
5.  **Избегайте пересечения CIDR:** Проектируйте сеть так, чтобы `podCIDR`, `serviceCIDR` и `nodeNetwork` не пересекались.
6.  **Используйте Multi-Pool в Cilium для разделения сред:** Отдельные пулы для production, staging и GPU-узлов упрощают отладку и безопасность.

### Очистка среды

```bash
# Очистка осиротевших IP в Calico
calicoctl ipam release --from-report=report.json

# Удаление Cilium Pod IP Pool
kubectl delete ciliumpodippool production-pool

# Полное удаление Cilium (если требуется)
helm uninstall cilium -n kube-system

# Очистка CRD Cilium (если не используются другие компоненты)
kubectl delete crd ciliumpodippools.cilium.io ciliumendpoints.cilium.io ...
```

---

## Крайние случаи и ограничения

1.  **Исчерпание адресов:** При неверно рассчитанном `/maskSize` в `CiliumPodIPPool` новые поды не смогут получить IP. Мониторьте utilization через `cilium status --verbose`.
2.  **Block-Based IPAM (Calico):** При сбое узла блок `/26` остается «зарезервированным» до освобождения через `calicoctl ipam release`. Это может привести к фрагментации адресного пространства.
3.  **Dual-Stack и IPv6-only:** Не все приложения корректно работают в Dual-Stack среде (проблемы с приоритетом адресов в glibc). Тестируйте приложения перед миграцией.
4.  **Static IP и лицензии:** Назначение статического IP в Calico требует включенной лицензии (Typha или Enterprise). В Cilium Static IP доступен в Open Source через Multi-Pool.
5.  **Совместимость ядра:** Для Dual-Stack требуется ядро 5.10+ с поддержкой `CONFIG_IPV6` и `CONFIG_IPV6_MIP6`. Всегда проверяйте `uname -r` и `zgrep CONFIG_IPV6 /boot/config-$(uname -r)`.
6.  **NetBox Operator:** При большом количестве подов (>10k) синхронизация может создавать значительную нагрузку на API NetBox. Настройте batch-обновления и интервалы синхронизации.
7.  **Миграция IPAM необратима:** Переход с `cluster-pool` на `multi-pool` в Cilium не может быть откачен без ручного вмешательства и перезапуска всех подов.

---

## Дополнительные сведения

### Проблемы перекрытия (Subnet Overlap)

При проектировании критически важно исключить пересечение `podCIDR` с:
1.  **Node Network:** Физические IP узлов.
2.  **Service CIDR:** Виртуальные IP сервисов (ClusterIP).
3.  **Transit/Office Network:** Сети, доступные через VPN/Direct Connect.

**Рекомендация (2026):** При проектировании новых кластеров используйте IPv6 как приоритетный протокол для внутренней связности, оставляя IPv4 только для внешнего Ingress/Egress трафика.

### См. также

- [**Cilium: Высокопроизводительный CNI**](./cilium.md) — детали реализации Multi-pool IPAM.
- [**Обзор сетевой модели Kubernetes**](../network_overview.md) — базовые принципы IP-per-Pod и проектирования CIDR.
- [**CNI и kube-proxy: роли и взаимодействие**](../cni_kube_proxy_roles.md) — жизненный цикл IP-адресов и Dual-Stack.
