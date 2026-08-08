# Высокая доступность Kubernetes на Bare-Metal: Обзор

## Определения

**Bare-Metal** — физические серверы без слоя виртуализации. Обеспечивают максимальную производительность и прямой доступ к ресурсам, но требуют автономного управления жизненным циклом (IPMI, PXE) и обработки отказов на уровне ОС.

**kubeadm** — стандартная утилита для развертывания кластеров Kubernetes. В 2026 году (v1.35+) поддерживает расширенные функции жизненного цикла, включая автоматическую ротацию сертификатов и интеграцию с внешними etcd. Подробнее: [Индекс kubeadm](../kubeadm/index.md).

**containerd** — индустриальный стандарт среды выполнения контейнеров. В современных инсталляциях используется с поддержкой плагинов для расширенной изоляции (например, gVisor или Kata Containers через RuntimeClass).

**Высокая доступность (High-Availability, HA)** — архитектурный подход, исключающий единую точку отказа (SPoF). Для Kubernetes это означает наличие 3+ узлов Control Plane и отказоустойчивой точки входа (Endpoint). Базовые принципы: [Обзор HA](../../../Concepts/High_Availability/ha_overview.md).

**Control Plane Endpoint** — виртуальный адрес (VIP) или DNS-имя, которое всегда указывает на доступные экземпляры API-сервера.

---

## Основные концепции

### Архитектура HA кластера

Для bare-metal наиболее распространена схема **Stacked Control Plane**, где база данных `etcd` работает на тех же узлах, что и управляющие компоненты.

#### Ключевые компоненты отказоустойчивости

1.  **Балансировка нагрузки API (L4 Load Balancer)**
    - **Классический подход**: Связка `Keepalived` (для VIP) и `HAProxy` (для балансировки на порт 6443).
    - **Современный подход**: [**kube-vip**](../kubeadm/ha_concepts.md#альтернатива-kube-vip) — cloud-native решение, работающее как Static Pod. Оно управляет VIP и может анонсировать маршруты через BGP.
    - **Локальная балансировка**: `kube-proxy` или `node-local-dns` на worker-узлах могут работать в паре с локальным балансировщиком для снижения нагрузки на центральный VIP.

2.  **Плоскость управления (Control Plane Nodes)**
    - Минимум **3 узла** для обеспечения кворума etcd.
    - **Статус компонентов**: `kube-apiserver` является stateless-компонентом, тогда как `kube-scheduler` и `kube-controller-manager` используют механизм выбора лидера (Leader Election).
    - **Требования к etcd**: Критически важна низкая задержка дисковой подсистемы (рекомендуется NVMe) и стабильность сети между мастерами (Latency < 10ms).

3.  **Сетевая связность (CNI)**
    - В HA-средах CNI должен поддерживать отказоустойчивость путей передачи трафика. [Calico](../cni_installation.md) часто выбирается за счет поддержки BGP-пиринга с физическим оборудованием.

### Топологии размещения etcd

| Характеристика | Stacked etcd (Совмещенный) | External etcd (Выделенный) |
| :--- | :--- | :--- |
| **Ресурсы** | Экономия серверов (мин. 3) | Требует больше железа (мин. 3+3) |
| **Изоляция** | API и etcd делят CPU/RAM/Disk | Полная изоляция ресурсов |
| **Сложность** | Настраивается через `kubeadm` автоматически | Требует отдельного управления сертификатами |
| **Масштабируемость** | Ограничена ресурсами узла | Позволяет масштабировать etcd независимо |

Подробнее: [Сценарии etcd](../../Concepts/etcd_overview.md), [Архитектура Control Plane](../../Concepts/control_plane_architecture.md).

---

## Практические сценарии

### Жизненный цикл развёртывания HA кластера

Процесс состоит из последовательных фаз, каждая из которых описана в детальных руководствах:

1.  **Окружение**: Проверка соответствия [аппаратным и программным требованиям](./k8s_ha_environment_requirements.md).
2.  **Подготовка**: Настройка параметров ядра, модулей и `/etc/hosts` на [всех узлах](./k8s_ha_node_preparation.md).
3.  **Компоненты**: Установка Runtime (`containerd`) и утилит Kubernetes на [каждый сервер](./k8s_ha_component_installation.md).
4.  **Load Balancer**: Развертывание [Keepalived + HAProxy](../kubeadm/keepalived_haproxy_setup.md) или [kube-vip](../kubeadm/ha_concepts.md#альтернатива-kube-vip).
5.  **Bootstrap**: [Инициализация первого мастера](../kubeadm/cluster_initialization.md) с флагом `--control-plane-endpoint`.
6.  **Сетевой плагин**: Установка и настройка [CNI (Calico)](./cni_installation.md).
7.  **Масштабирование CP**: [Присоединение остальных мастеров](./node_joining.md) через `join --control-plane`.
8.  **Worker Nodes**: Присоединение рабочих узлов и [финальная верификация](./k8s_ha_cluster_verification.md).

### Сценарий: Самовосстановление при отказе мастера

1.  **Детекция**: Балансировщик (или Keepalived) фиксирует недоступность узла через health-check (обычно < 5 секунд).
2.  **Failover**: VIP переходит на исправный узел. Новые запросы к API направляются на работающие бэкенды.
3.  **Кворум**: etcd продолжает работу в режиме Read/Write (2 из 3 узлов доступны).
4.  **Worker Response**: `kubelet` на воркерах может кратковременно потерять связь, но поды продолжают работать (если не используется короткий Grace Period для Node Lease).

---

## Дополнительная информация

### Мониторинг и отладка HA

```bash
# 1. Проверка доступности API через Endpoint (VIP)
curl -k https://<CONTROL_PLANE_ENDPOINT>:6443/healthz

# 2. Список участников etcd и их состояние
kubectl exec -n kube-system etcd-<master-node-name> -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint status --cluster -w table

# 3. Статус выбора лидера в Control Plane
kubectl get endpoints -n kube-system kube-scheduler -o jsonpath='{.metadata.annotations.control-plane\.alpha\.kubernetes\.io/leader}'
```

**Критические показатели здоровья:**
- `etcd_disk_wal_fsync_duration_seconds`: задержка записи в лог (должна быть < 10ms).
- `apiserver_request_duration_seconds`: время ответа API на запросы.

### Связанные руководства

- **Развертывание**: [Подготовка узлов](./k8s_ha_node_preparation.md), [Компоненты](./k8s_ha_component_installation.md).
- **Инициализация**: [Инициализация мастера](../kubeadm/cluster_initialization.md), [Присоединение узлов](./node_joining.md).
- **Проверка**: [Верификация HA](./k8s_ha_cluster_verification.md).
- **Инфраструктура**: [Балансировка HAProxy](../kubeadm/keepalived_haproxy_setup.md), [Концепции HA](../../../Concepts/High_Availability/ha_overview.md).
- **Альтернативы**: [HA через Kubespray](../Kubespray/HA/index.md).
