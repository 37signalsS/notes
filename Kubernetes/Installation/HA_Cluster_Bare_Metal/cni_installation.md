# Установка CNI в HA кластере

## Определения

**CNI (Container Network Interface)** — открытый стандарт интерфейса, используемый Kubernetes для делегирования функций сетевого взаимодействия внешним плагинам. Отвечает за создание сетевых интерфейсов контейнеров, выделение IP-адресов (IPAM) и обеспечение связности между подами.

**Pod Network CIDR** — диапазон IP-адресов, из которого поды получают свои адреса. Задается параметром `--pod-network-cidr` при инициализации кластера.

**Инкапсуляция (Encapsulation)** — метод передачи трафика подов через физическую сеть узлов путем оборачивания L3-пакетов подов в пакеты физической сети (например, VXLAN или IPIP).

**MTU (Maximum Transmission Unit)** — максимальный размер пакета. При использовании инкапсуляции MTU сети подов должен быть меньше MTU физической сети (обычно на 20-50 байт) для предотвращения фрагментации.

**NetworkPolicy** — декларативный ресурс Kubernetes для управления трафиком между подами на уровнях L3/L4. В Calico поддерживаются расширенные политики: `GlobalNetworkPolicy` (глобальные) и `NetworkSet` (группы CIDR).

**calicoctl** — утилита командной строки для управления и диагностики Calico. Может использоваться как бинарный файл, как плагин kubectl (`kubectl calico`) или как под в кластере.

**Typha** — компонент Calico, снижающий нагрузку на API-сервер при большом количестве узлов (>50). Выступает посредником между Felix (агентом на узле) и etcd.

---

## Основные концепты

### Архитектура CNI в Kubernetes

CNI-плагин вызывается kubelet при создании и удалении контейнеров. Процесс работы:

1. **Kubelet** получает запрос на создание пода от API-сервера
2. **Kubelet** вызывает CNI-плагин, передавая ему информацию о контейнере
3. **CNI-плагин** выделяет IP-адрес из пула (IPAM), создает сетевой интерфейс и подключает его к мосту или напрямую к физической сети
4. **CNI-плагин** настраивает маршрутизацию и политики для пода

Конфигурация CNI хранится в `/etc/cni/net.d/` на каждом узле. Kubernetes использует первый файл конфигурации в алфавитном порядке (поэтому файлы именуются с числовым префиксом, например `10-calico.conflist`).

### Роль CNI в HA кластере

В высокодоступных (HA) кластерах CNI играет критическую роль не только в связности подов, но и в обеспечении доступности сервисов при отказе узлов:

- До установки CNI узлы находятся в статусе `NotReady`, так как `kubelet` ожидает готовности сетевой подсистемы
- CNI реализуется как DaemonSet — автоматически разворачивается на каждый новый узел при его добавлении в кластер
- При отказе узла CNI на соседних узлах обеспечивает переключение маршрутов (BGP) или обновление таблиц маршрутизации (VXLAN)

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

### Компоненты Calico

| Компонент | Тип | Назначение |
| :--- | :--- | :--- |
| **node** (Felix) | DaemonSet | Агент на каждом узле. Управляет маршрутизацией, NetworkPolicy, отчетностью о состоянии |
| **kube-controllers** | Deployment | Отслеживает изменения в API Kubernetes и синхронизирует состояние Calico |
| **typha** | Deployment (опционально) | Снижает нагрузку на API-сервер. Рекомендуется для кластеров >50 узлов |
| **cni-plugin** | DaemonSet | Устанавливает CNI-бинарники и конфигурацию на узлы |

---

## Практические сценарии

### Предварительные требования

#### Аппаратные требования

- **Процессор:** x86_64 (Intel/AMD) или ARM64
- **Память:** Минимум 4 GB RAM на узел; для кластеров >100 узлов рекомендуется 8+ GB

#### Программные требования

- **Ядро Linux:** Минимум 4.18 для Calico; рекомендуется 5.10+ для eBPF-режима
- **Модули ядра:** `br_netfilter` и `overlay` должны быть загружены (подробнее в [подготовке узлов](./k8s_ha_node_preparation.md))
- **Kubernetes:** Кластер инициализирован с параметром `--pod-network-cidr`
- **Сеть:** Порт 179/TCP (BGP) или 4789/UDP (VXLAN) открыт между узлами

#### Проверка готовности

```bash
# Проверка загрузки модулей ядра
lsmod | grep -E 'br_netfilter|overlay'

# Проверка версии ядра
uname -r
# → 5.15.0-101-generic (минимум 4.18)

# Проверка pod-network-cidr
kubectl cluster-info dump | grep -i cluster-cidr
# → --cluster-cidr=100.64.0.0/16

# Проверка что узлы в статусе NotReady (ожидают CNI)
kubectl get nodes
# → Все узлы должны быть NotReady до установки CNI
```

### Сценарий 1: Установка Calico через Tigera Operator (Рекомендуемый)

Этот метод позволяет гибко настраивать параметры сети через Custom Resources.

#### Шаг 1: Установка оператора Tigera

```bash
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/tigera-operator.yaml
```

#### Шаг 2: Создание конфигурации установки

```bash
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

#### Шаг 3: Верификация установки

```bash
# Ожидание готовности всех компонентов
kubectl get tigerastatus

# Проверка подов оператора
kubectl get pods -n tigera-operator
# → tigera-operator-xxx   1/1   Running

# Проверка подов Calico
kubectl get pods -n calico-system
# → calico-node-xxx       1/1   Running (на каждом узле)
# → calico-typha-xxx      1/1   Running (если включен)
# → csi-node-driver-xxx   1/1   Running
```

### Сценарий 2: Установка Calico через манифесты (Legacy)

Для сред, где использование Operator нежелательно, или для полного контроля над конфигурацией.

```bash
# Скачивание и применение манифеста
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/calico.yaml
```

**Важно:** При использовании манифестов необходимо убедиться, что CIDR в манифесте совпадает с `--pod-network-cidr`, указанным при `kubeadm init`. По умолчанию манифест использует `192.168.0.0/16`.

### Сценарий 3: Настройка MTU для Bare-Metal

Если в вашей физической сети используется стандартный MTU 1500, а Calico использует VXLAN, MTU подов должен быть **1450**.

#### Настройка через Tigera Operator

```yaml
# Добавить в spec.calicoNetwork файла calico-config.yaml
apiVersion: operator.tigera.io/v1
kind: Installation
metadata:
  name: default
spec:
  calicoNetwork:
    mtu: 1450
    ipPools:
    - blockSize: 26
      cidr: 100.64.0.0/16
      encapsulation: VXLANCrossSubnet
      natOutgoing: Enabled
      nodeSelector: all()
```

Применить изменения:

```bash
kubectl apply -f calico-config.yaml
```

#### Проверка MTU на узле

```bash
# Проверка MTU на интерфейсе caliXXXX
ip link show | grep cali
# → cali1234567890a: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1450 ...

# Проверка MTU на туннельном интерфейсе
ip link show vxlan.calico
# → vxlan.calico: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1450 ...
```

### Сценарий 4: Режимы инкапсуляции

Для bare-metal кластеров выбор режима критичен для производительности:

| Режим | Описание | MTU | Требования к сети |
| :--- | :--- | :--- | :--- |
| **VXLAN** | Инкапсуляция в UDP-пакеты | 1450 | Любая L3-сеть |
| **VXLANCrossSubnet** | VXLAN только для межподсетевого трафика | 1450 (межподсеть) | Оптимально для распределенных сетей |
| **IPIP** | Инкапсуляция IP в IP | 1440 | Может блокироваться firewall |
| **None (BGP)** | Прямая маршрутизация без инкапсуляции | 1500 | Требует BGP на коммутаторах |

#### Настройка режима через Tigera Operator

```yaml
# VXLAN (универсальный)
encapsulation: VXLAN

# VXLANCrossSubnet (рекомендуется для распределенных сетей)
encapsulation: VXLANCrossSubnet

# IPIP
encapsulation: IPIP

# BGP без инкапсуляции
encapsulation: None
```

### Сценарий 5: Включение Typha для масштабирования

Для кластеров >50 узлов компонент Typha снижает нагрузку на API-сервер, выступая прокси между Felix и etcd.

#### Через Tigera Operator

```yaml
apiVersion: operator.tigera.io/v1
kind: Installation
metadata:
  name: default
spec:
  typhaMetricsPort: 9093
  calicoNetwork:
    ipPools:
    - blockSize: 26
      cidr: 100.64.0.0/16
      encapsulation: VXLANCrossSubnet
      natOutgoing: Enabled
      nodeSelector: all()
```

#### Верификация Typha

```bash
# Проверка что Typha запущен
kubectl get pods -n calico-system -l k8s-app=calico-typha

# Проверка количества подключений
kubectl exec -n calico-system calico-typha-xxx -- /bin/calico-node -typha-conn
```

### Сценарий 6: Верификация установки и связности

#### Проверка состояния компонентов

```bash
# Проверка статуса узлов
kubectl get nodes
# → Должны перейти в статус Ready

# Проверка подов Calico
kubectl get pods -n calico-system
# → Все поды должны быть Running

# Проверка состояния IPAM
kubectl get ippools

# Проверка статуса Calico
kubectl get tigerastatus
# → Available: True для всех компонентов
```

#### Проверка сетевой связности (East-West)

```bash
# Запуск тестовых подов
kubectl run test-client --image=busybox --restart=Never -- sleep 3600
kubectl run test-server --image=nginx --restart=Never --port=80
kubectl expose pod test-server --port=80

# Получение IP сервера
SERVER_IP=$(kubectl get pod test-server -o jsonpath='{.status.podIP}')
echo "Server IP: $SERVER_IP"

# Пинг сервера из клиента
kubectl exec test-client -- ping -c 3 $SERVER_IP
# → 3 packets transmitted, 3 received, 0% packet loss

# Проверка DNS (если CoreDNS установлен)
kubectl exec test-client -- nslookup test-server
# → Address: <cluster-ip>
```

#### Проверка NetworkPolicy

```bash
# Создание тестовой NetworkPolicy (default deny ingress)
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
spec:
  podSelector: {}
  policyTypes:
  - Ingress
EOF

# Проверка что политика применилась
kubectl get networkpolicy
# → default-deny-ingress    default    <none>    <none>

# Удаление тестовой политики
kubectl delete networkpolicy default-deny-ingress
```

### Сценарий 7: Установка и использование calicoctl

calicoctl необходим для расширенной диагностики и управления Calico.

#### Установка как плагин kubectl

```bash
# Скачивание
curl -L https://github.com/projectcalico/calico/releases/download/v3.33.0/calicoctl-linux-amd64 -o kubectl-calico
chmod +x kubectl-calico
sudo mv kubectl-calico /usr/local/bin/

# Проверка
kubectl calico --version
# → calicoctl version v3.33.0
```

#### Настройка подключения к хранилищу данных

```bash
# Для etcd (по умолчанию в bare-metal)
cat <<EOF > /etc/calico/calicoctl.cfg
apiVersion: projectcalico.org/v3
kind: CalicoAPIConfig
metadata:
spec:
  datastoreType: "etcdv3"
  etcdEndpoints: "https://10.0.0.10:2379"
  etcdKeyFile: "/etc/kubernetes/pki/etcd/server.key"
  etcdCertFile: "/etc/kubernetes/pki/etcd/server.crt"
  etcdCACertFile: "/etc/kubernetes/pki/etcd/ca.crt"
EOF
```

#### Основные команды диагностики

```bash
# Проверка статуса узлов Calico
kubectl calico node status
# → Вывод информации о BGP-сессиях, маршрутизации

# Проверка IPAM
kubectl calico ipam show --show-blocks
# → Выделенные блоки адресов по узлам

# Проверка NetworkPolicy
kubectl calico networkpolicy list --all-namespaces

# Проверка конфигурации BGP
kubectl calico bgp peer list
```

### Сценарий 8: Обновление Calico

#### Через Tigera Operator

```bash
# Обновление оператора
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.33.1/manifests/tigera-operator.yaml

# Проверка прогресса обновления
kubectl get tigerastatus
```

#### Через манифесты

```bash
# Применение нового манифеста
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.33.1/manifests/calico.yaml

# Мониторинг rolling update
kubectl rollout status ds/calico-node -n calico-system
```

### Сценарий 9: Удаление Calico

**Внимание:** Выполняйте только при необходимости полной переустановки или миграции на другой CNI.

```bash
# Удаление через Operator
kubectl delete -f calico-config.yaml
kubectl delete -f https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/tigera-operator.yaml

# Удаление через манифесты
kubectl delete -f https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/calico.yaml

# Очистка конфигурации CNI на узлах (выполнить на каждом узле)
sudo rm -rf /etc/cni/net.d/10-calico.conflist
sudo rm -rf /opt/cni/bin/calico
sudo rm -rf /opt/cni/bin/calico-ipam

# Очистка сетевых интерфейсов
sudo ip link delete cni0 2>/dev/null
sudo ip link delete vxlan.calico 2>/dev/null
sudo ip link delete tunl0 2>/dev/null

# Перезапуск kubelet
sudo systemctl restart kubelet
```

---

## Дополнительная информация

### Диагностика типичных проблем

#### 1. Узлы застряли в статусе NotReady

**Причины:**
- Неверный `pod-network-cidr` (не совпадает с `kubeadm init`)
- Отсутствие модулей ядра `br_netfilter` или `overlay`
- Блокировка портов между узлами

**Диагностика:**

```bash
# Проверка логов kubelet
sudo journalctl -u kubelet -f

# Проверка логов Calico
kubectl logs -n calico-system -l k8s-app=calico-node

# Проверка событий
kubectl get events --field-selector reason=NetworkNotReady
```

**Решение:**

```bash
# Загрузка модулей ядра
sudo modprobe br_netfilter
sudo modprobe overlay

# Проверка что модули загружены
lsmod | grep -E 'br_netfilter|overlay'
```

#### 2. Поды не могут связаться между собой (MTU Issue)

**Симптомы:** Маленькие пакеты (ping) проходят, большие (HTTP/DB) зависают.

**Диагностика:**

```bash
# Тест с учетом заголовков (1472 + 28 = 1500)
ping -s 1472 <pod-ip>

# Проверка MTU на интерфейсах
ip link show | grep -E 'cali|vxlan'
```

**Решение:** Уменьшите MTU в конфигурации Calico (см. Сценарий 3).

#### 3. Проблемы с BGP (в режиме без инкапсуляции)

**Диагностика:**

```bash
# Проверка BGP-сессий
kubectl calico node status

# Проверка логов Felix
kubectl logs -n calico-system -l k8s-app=calico-node | grep -i bgp

# Проверка порта 179
ss -tlnp | grep 179
```

**Ожидаемый результат:** `Peer Status: Established`

#### 4. Исчерпание пула IP-адресов

**Симптомы:** Поды зависают в статусе `ContainerCreating` с ошибкой `Failed to allocate IP`.

**Диагностика:**

```bash
# Проверка выделенных IP
kubectl calico ipam show --show-blocks

# Проверка событий
kubectl describe pod <pod> | grep -A5 Events
```

**Решение:** Расширьте Pod CIDR или добавьте новый IP pool (требуется переинициализация кластера для изменения основного CIDR).

#### 5. Конфликт с другим CNI

**Симптомы:** Дублирующиеся интерфейсы, маршруты, неработающая сеть.

**Диагностика:**

```bash
# Проверка конфигурации CNI
ls -la /etc/cni/net.d/

# Проверка бинарников
ls -la /opt/cni/bin/
```

**Решение:** Удалите конфигурации предыдущего CNI:

```bash
# Удаление конфигураций других CNI
sudo rm /etc/cni/net.d/10-flannel.conflist
sudo rm /etc/cni/net.d/05-cilium.conf
```

### Best Practices

1. **Используйте Tigera Operator для production** — автоматическое обновление и управление через CRD
2. **Включайте Typha для кластеров >50 узлов** — снижает нагрузку на API-сервер
3. **Предпочитайте VXLANCrossSubnet** — оптимален для распределенных сетей
4. **Используйте calicoctl для диагностики** — предоставляет детальную информацию о BGP, IPAM, политиках
5. **Мониторьте IPAM** — регулярно проверяйте `kubectl calico ipam show --show-blocks`
6. **Применяйте NetworkPolicy** — начинайте с `default deny` и разрешайте только необходимый трафик
7. **Фиксируйте версии** — указывайте конкретные версии Calico в манифестах, а не `latest`

### Крайние случаи

1. **Изменение Pod CIDR после установки** — требует переинициализации кластера. Заранее планируйте размер пула.
2. **Миграция между CNI** — остановите все приложения, удалите старый CNI, установите новый, перезапустите поды
3. **Multus CNI** — для использования нескольких сетевых интерфейсов на под установите Multus как мета-CNI
4. **Dual-Stack** — требует поддержки от CNI и правильной настройки `kubeadm init` с двумя CIDR

### Интеграция с процессом развёртывания HA кластера

Установка CNI — **шаг 5** после [установки компонентов](./k8s_ha_component_installation.md) и перед [подключением узлов](./node_joining.md). Архитектурные детали HA описаны в [обзоре кластера](./k8s_ha_cluster_overview.md).

### См. также

- [Выбор CNI и методы внешнего доступа](../../Networking/Network/CNI/selection_and_external_access.md) — сравнение CNI-плагинов и методы публикации сервисов
- [Cilium: Высокопроизводительный CNI на базе eBPF](../../Networking/Network/CNI/cilium.md) — альтернативный CNI на базе eBPF
- [IPAM в Kubernetes](../../Networking/Network/CNI/ipam.md) — управление адресным пространством
- [Официальная документация Calico](https://docs.tigera.io/calico/latest/)
