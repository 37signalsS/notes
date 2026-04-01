# High Availability API-сервера с Keepalived и HAProxy

Настройка отказоустойчивого Control Plane для Kubernetes с использованием Keepalived и HAProxy.

## Структура

- **[ha_concepts.md](./ha_concepts.md)** — Архитектурные концепции, компоненты, требования
- **[keepalived_haproxy_setup.md](./keepalived_haproxy_setup.md)** — Установка и конфигурация Keepalived и HAProxy
- **[cluster_initialization.md](./cluster_initialization.md)** — Инициализация кластера, проверка, troubleshooting

## Быстрый старт

1. Установить Keepalived на все master-узлы
2. Настроить MASTER и BACKUP узлы
3. Установить HAProxy и настроить балансировку
4. Инициализировать кластер через VIP

## Связанные темы

- **HA кластер на bare metal**: [HA Overview](../../HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)
- **Control Plane & CNI**: [Control Plane & CNI](../../HA_Cluster_Bare_Metal/control_plane_initialization.md)
- **Keepalived обзор**: [Keepalived](../../../../Networking/ServicesAndTools/keepalived_overview.md)
- **HAProxy обзор**: [HAProxy](../../../../WebServers/haproxy_overview.md)
