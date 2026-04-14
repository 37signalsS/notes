# Установка Kubernetes через kubeadm

Индекс документов по установке и настройке кластера Kubernetes с использованием утилиты `kubeadm`.

## Структура

- **[kubeadm_installation_guide.md](./kubeadm_installation_guide.md)** — Полное руководство: требования, установка containerd, пакетов, инициализация, CNI, join нод, troubleshooting
- **[cluster_initialization.md](./cluster_initialization.md)** — Инициализация кластера, флаги `kubeadm init`, HA-инициализация, отладка
- **[ha_concepts.md](./ha_concepts.md)** — Архитектурные концепции HA Control Plane, компоненты, требования
- **[keepalived_haproxy_setup.md](./keepalived_haproxy_setup.md)** — Установка и конфигурация Keepalived и HAProxy для HA

## Быстрый старт — Single-node кластер

1. Подготовить узлы: модули ядра, sysctl, отключить swap
2. Установить containerd, kubelet, kubeadm, kubectl
3. Инициализировать Control Plane: `kubeadm init --pod-network-cidr=10.244.0.0/16`
4. Настроить kubeconfig
5. Установить CNI-плагин (Calico/Flannel)

## Быстрый старт — HA кластер

1. Установить Keepalived на все master-узлы
2. Настроить MASTER и BACKUP узлы
3. Установить HAProxy и настроить балансировку
4. Инициализировать кластер через VIP

## Связанные темы

- **HA кластер на bare metal**: [HA Overview](../HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)
- **Control Plane & CNI**: [Control Plane & CNI](../HA_Cluster_Bare_Metal/control_plane_initialization.md)
- **Управление сертификатами**: [Certificate Management](../../Operations/certificate_management.md)
- **Обновление кластеров**: [Upgrading Clusters](../../Operations/upgrading_clusters.md)
- **Keepalived обзор**: [Keepalived](../../../Networking/ServicesAndTools/keepalived_overview.md)
- **HAProxy обзор**: [HAProxy](../../../WebServers/haproxy_overview.md)
