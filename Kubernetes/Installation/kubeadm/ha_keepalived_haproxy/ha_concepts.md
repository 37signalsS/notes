# High Availability API-сервера с Keepalived и HAProxy: Концепции

## Определения

| Термин | Описание |
| :--- | :--- |
| **HA Control Plane** | Архитектура с несколькими master-узлами для устранения единой точки отказа (SPOF). |
| **Virtual IP (VIP)** | Плавающий IP-адрес, перемещающийся между узлами кластера. |
| **Control Plane Endpoint** | Единая точка входа для доступа к API-серверу (`<VIP>:<PORT>` или DNS). |
| **L4 Load Balancer** | Балансировщик транспортного уровня (TCP), не терминирующий TLS. |

## Проблема

В кластере с несколькими master-узлами каждый запускает `kube-apiserver` на порту `6443`. При использовании IP одного узла:

* При отказе узла доступ к API теряется.
* Требуется ручное переключение клиентов (`kubectl`, `kubelet`, `kubeadm join`).

## Решение: VIP + L4-балансировщик

```
                    ┌─────────────────────────────────────────┐
                    │           Virtual IP (VIP)              │
                    │         192.168.122.189:7443            │
                    └─────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
              ┌─────▼─────┐   ┌──────▼──────┐   ┌──────▼──────┐
              │ Keepalived│   │ Keepalived  │   │ Keepalived  │
              │  MASTER   │   │   BACKUP    │   │   BACKUP    │
              │           │   │             │   │             │
              │  HAProxy  │   │   HAProxy   │   │   HAProxy   │
              │           │   │             │   │             │
              │ API:6443  │   │  API:6443   │   │  API:6443   │
              └───────────┘   └─────────────┘   └─────────────┘
```

## Компоненты

| Компонент | Назначение | Принцип работы |
| :--- | :--- | :--- |
| **Keepalived** | Обеспечение доступности VIP | Протокол VRRP, приоритеты MASTER/BACKUP |
| **HAProxy** | Балансировка трафика к API | TCP mode (`mode tcp`), health checks |

## Архитектурные решения

| Решение | Описание |
| :--- | :--- |
| **VIP на другом порту** | HAProxy слушает `VIP:7443`, так как `6443` занят локальным API |
| **TCP балансировка** | HAProxy не терминирует TLS, трафик прозрачно передаётся API Server |
| **Health checks** | HAProxy проверяет доступность API Server перед отправкой трафика |
| **Размещение на хостах** | Keepalived + HAProxy запускаются на хостах (не в K8s) для bootstrap |

## Требования

| Компонент | Требование |
| :--- | :--- |
| **Количество master-узлов** | 3 (нечётное число для кворума etcd) |
| **ОС** | Ubuntu 20.04+, Debian 11+, Rocky Linux 9+ |
| **Сеть** | Статические IP, доступ между узлами, свободный VIP |
| **Порты** | 6443 (API), 7443 (HAProxy VIP), 8404 (HAProxy stats, опционально) |

## Best Practices

| Практика | Описание |
| :--- | :--- |
| **Нечётное число master** | 3 или 5 узлов для кворума etcd |
| **Размещение в разных стойках** | Избегание SPOF на уровне инфраструктуры |
| **Мониторинг VIP** | Проверка доступности VIP и HAProxy |
| **Тестирование failover** | Регулярная проверка переключения MASTER → BACKUP |
| **Firewall правила** | Открыть порты 6443, 7443, 8404 между master |

## Альтернативы

| Решение | Среда | Описание |
| :--- | :--- | :--- |
| **Cloud Load Balancer** | AWS/GCP/Azure | NLB/ELB для балансировки API Server |
| **kube-vip** | Bare-metal, VM | VIP внутри Kubernetes (DaemonSet) |
| **MetalLB + Ingress** | Bare-metal | Балансировка для сервисов, не для API |

## Связанные темы

* [HA кластер на bare metal](../../HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)
* [Keepalived обзор](../../../../Networking/ServicesAndTools/keepalived_overview.md)
* [HAProxy обзор](../../../../WebServers/haproxy_overview.md)
* [Высокая доступность Kubernetes](../../../Base/high_availability.md)
