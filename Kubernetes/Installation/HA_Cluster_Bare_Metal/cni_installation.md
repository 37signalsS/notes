# Установка CNI в HA кластере

## Определения

**CNI (Container Network Interface)** — открытый стандарт интерфейса, используемый Kubernetes для делегирования функций сетевого взаимодействия внешним плагинам. Отвечает за создание сетевых интерфейсов контейнеров, выделение IP-адресов (IPAM) и обеспечение связности между подами.

**Pod Network CIDR** — диапазон IP-адресов, из которого поды получают свои адреса. Задается параметром `--pod-network-cidr` при инициализации кластера.

**Инкапсуляция (Encapsulation)** — метод передачи трафика подов через физическую сеть узлов путем оборачивания L3-пакетов подов в пакеты физической сети (например, VXLAN или IPIP).

**MTU (Maximum Transmission Unit)** — максимальный размер пакета. При использовании инкапсуляции MTU сети подов должен быть меньше MTU физической сети (обычно на 20-50 байт) для предотвращения фрагментации.

---

## Основные концепции

### Роль CNI в HA кластере

В высокодоступных (HA) кластерах CNI играет критическую роль не только в связности подов, но и в обеспечении доступности сервисов при отказе узлов. До установки CNI узлы находятся в статусе `NotReady`, так как `kubelet` ожидает готовности сетевой подсистемы.

### Выбор метода установки Calico

В 2026 году для production-сред рекомендуется использование **Tigera Operator** вместо обычных манифестов.

| Метод | Плюсы | Минусы | Применение |
| :--- | :--- | :--- | :--- |
| **Tigera Operator** | Автоматическое обновление, управление через CRD, контроль жизненного цикла | Требует установки дополнительных CRD | Production, HA кластеры |
| **Manifest (Legacy)** | Простота (один файл), отсутствие лишних сущностей | Ручное управление обновлениями, сложность тонкой настройки | Test, Dev, малые кластеры |

### Совместимость версий (актуально на август 2026)

| Компонент | Версия | Статус |
| :--- | :--- | :--- |
| **Kubernetes** | v1.34.x — v1.35.x | Рекомендуемые стабильные версии |
| **Calico** | v3.33.x | Текущая стабильная ветка |

---

## Практические сценарии

### Сценарий 1: Установка Calico через Tigera Operator (Рекомендуемый)

Этот метод позволяет гибко настраивать параметры сети через Custom Resources.

```bash
# 1. Установка оператора Tigera
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/tigera-operator.yaml

# 2. Создание конфигурации установки (Custom Resource)
# ВАЖНО: Укажите ваш CIDR в поле ipPools -> cidr
cat <<EOF > calico-config.yaml
apiVersion: operator.tigera.io/v1
kind: Installation
metadata:
  name: default
spec:
  # Настройка сетевой среды
  calicoNetwork:
    ipPools:
    - blockSize: 26
      cidr: 100.64.0.0/16
      encapsulation: VXLANCrossSubnet
      natOutgoing: Enabled
      nodeSelector: all()
---
apiVersion: operator.tigera.io/v1
kind: APIServer
metadata:
  name: default
spec: {}
EOF

kubectl apply -f calico-config.yaml
```

### Сценарий 2: Настройка MTU для Bare-Metal

Если в вашей физической сети используется стандартный MTU 1500, а Calico использует VXLAN, MTU подов должен быть **1450**.

**Настройка через Tigera Operator:**
```yaml
# Добавить в spec.calicoNetwork файла calico-config.yaml
mtu: 1450
```

**Проверка на узле:**
```bash
# Проверка MTU на интерфейсе caliXXXX
ip link show | grep cali
```

### Сценарий 3: Режимы инкапсуляции

Для bare-metal кластеров выбор режима критичен для производительности:

1.  **VXLAN (Default)**: Работает в любой L2/L3 сети. Самый универсальный режим.
2.  **IPIP**: Чуть выше производительность, чем у VXLAN, но может блокироваться некоторыми сетевыми экранами.
3.  **No Encapsulation (BGP)**: Максимальная производительность. Требует поддержки BGP на физических коммутаторах (Top-of-Rack). Поды получают маршрутизируемые IP в локальной сети.

### Шаг 6: Проверка состояния и связности

После применения конфигурации необходимо убедиться в готовности сети:

```bash
# Проверка статуса узлов
kubectl get nodes
# → Должны перейти в статус Ready

# Проверка подов Calico в namespace calico-system (при использовании Operator)
kubectl get pods -n calico-system

# Проверка состояния IPAM
kubectl get ippools
```

**Тест связности (East-West):**
```bash
# Запуск тестового пода
kubectl run busybox --image=busybox --restart=Never -- sleep 3600

# Пинг API-сервера или другого пода изнутри
kubectl exec busybox -- ping -c 3 10.96.0.1
```

---

## Дополнительная информация

### Диагностика типичных проблем

**1. Узлы застряли в Ready: False**
- **Причина**: Неверный `pod-network-cidr` (не совпадает с `kubeadm init`).
- **Решение**: Проверьте логи оператора: `kubectl logs -n tigera-operator -l k8s-app=tigera-operator`.

**2. Поды не могут связаться между собой (MTU Issue)**
- **Симптомы**: Маленькие пакеты (ping) проходят, большие (HTTP/DB) зависают.
- **Диагностика**: `ping -s 1472 <pod-ip>` (тест с учетом заголовков).
- **Решение**: Уменьшите MTU в конфигурации Calico.

**3. Проблемы с BGP (в режиме без инкапсуляции)**
- **Команда**: `calicoctl node status` (требует установки `calicoctl` как плагина kubectl).
- **Ожидаемый результат**: `Peer Status: Established`.

### Полезные ссылки
- [Официальная документация Calico](https://docs.tigera.io/calico/latest/)
- [Матрица совместимости CNI](https://docs.tigera.io/calico/latest/about/supported-releases)
- [Сравнение производительности CNI (Cilium vs Calico)](../../Networking/Network/CNI/selection_and_external_access.md)
- [Диагностика сети в Kubernetes](../../Networking/Network/network_troubleshooting.md)

### Интеграция с процессом развёртывания HA кластера

Установка CNI — **шаг 5** после [инициализации Control Plane](./control_plane_initialization.md) и перед [подключением узлов](./node_joining.md). Архитектурные детали HA описаны в [обзоре кластера](./k8s_ha_cluster_overview.md).
