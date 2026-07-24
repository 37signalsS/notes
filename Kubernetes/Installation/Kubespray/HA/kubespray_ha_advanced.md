# Kubespray: Развертывание HA-кластера — Дополнительные темы

## Определения

**Отказоустойчивость (High Availability, HA)** — архитектурный подход, обеспечивающий непрерывную работу системы при выходе из строя отдельных компонентов. В контексте Kubespray это достигается резервированием узлов Control Plane и etcd.

**Виртуальный IP (VIP)** — единый IP-адрес для доступа к API-серверу, который автоматически перемещается между активными мастерами.

**Kube-vip** — современное cloud-native решение для управления VIP и балансировки нагрузки, работающее в виде Static Pod или DaemonSet.

Детальное описание архитектурных схем и сравнение методов балансировки представлены в [основных концепциях](./kubespray_ha_concepts.md).

## Основные концепции

### Тюнинг параметров отказоустойчивости

Kubespray позволяет тонко настраивать поведение механизмов HA через переменные в `group_vars`.

| Переменная | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `loadbalancer_apiserver_localhost` | `false` | Использовать локальный nginx/haproxy на worker-нодах для связи с мастерами. |
| `enable_keepalived` | `false` | Активация Keepalived для управления VIP (требует `loadbalancer_apiserver`). |
| `kube_vip_enabled` | `false` | Включение Kube-vip (рекомендуемая замена Keepalived для bare-metal). |
| `kube_vip_address` | — | IP-адрес, который будет использоваться как VIP для Kube-vip. |
| `keepalived_virtual_router_id` | `51` | Идентификатор VRRP-группы (должен быть уникален в L2-сегменте). |

### Взаимодействие с сетевыми плагинами

При использовании Keepalived или Kube-vip в режиме Layer 2 необходимо учитывать особенности CNI:
- **Calico:** может конфликтовать с VIP, если используется BGP. Рекомендуется использовать режим `kube-vip` с анонсированием через BGP при наличии поддержки в сетевой фабрике.
- **Cilium:** имеет встроенные механизмы балансировки и L3-пути, которые могут заменить классический Keepalived.

---

## Практические сценарии

### Тестирование отказоустойчивости (Keepalived + HAProxy)

#### Тест 1: Миграция VIP при отказе узла

1. Проверьте текущий узел-владелец VIP:
   ```bash
   ip a show dev eth0 | grep <VIP_ADDRESS>
   # → inet 192.168.1.100/32 scope global eth0
   ```
2. Имитируйте сбой, остановив службу:
   ```bash
   systemctl stop keepalived
   ```
3. Проверьте переход VIP на другой узел:
   ```bash
   # На соседнем мастере
   ip a show dev eth0 | grep <VIP_ADDRESS>
   # → inet 192.168.1.100/32 scope global eth0
   ```

#### Тест 2: Исключение API-сервера из балансировки

1. Остановите API-сервер на одном из мастеров:
   ```bash
   systemctl stop kube-apiserver
   ```
2. Проверьте статус бэкенда в HAProxy:
   ```bash
   echo "show stat" | socat stdio /var/run/haproxy/admin.sock | grep kubernetes-api
   # → kubernetes-api-masters,master-1,0,0,0,0,,0,0,0,,0,,OFFLINE,...
   ```

### Тестирование отказоустойчивости (Kube-vip)

1. Проверьте статус статического пода на всех мастерах:
   ```bash
   kubectl get pods -n kube-system -l name=kube-vip
   # → kube-vip-master-1  1/1  Running  0  10m
   ```
2. Удалите манифест или остановите контейнер на текущем лидере.
3. Проверьте логи на другом узле для подтверждения захвата лидерства:
   ```bash
   crictl logs <container_id>
   # → INFO[0000] Beginning cluster leadership election...
   # → INFO[0005] Node <hostname> is now the leader
   ```

### Проверка кворума etcd

Для обеспечения работоспособности кластера должна быть доступна большая часть узлов etcd (`n/2 + 1`).

```bash
# Проверка статуса на любом мастере
kubectl exec -n kube-system -it etcd-master-1 -- etcdctl endpoint status --cluster -w table
# → +------------------------+------------------+---------+---------+-----------+------------+
# → |       ENDPOINT         |        ID        | VERSION | DB SIZE | IS LEADER | RAFT TERM  |
# → +------------------------+------------------+---------+---------+-----------+------------+
# → | https://10.0.1.10:2379 | 8e9e05f52f645634 |  3.5.x  |  20 MB  |   true    |     5      |
# → +------------------------+------------------+---------+---------+-----------+------------+
```

---

## Устранение неполадок

### Проблемы с VIP и VRRP

**Симптом:** VIP назначен на нескольких узлах одновременно (Split-brain).
- **Причина:** Узлы не видят VRRP-пакеты друг друга (заблокирован мультикаст или порт 112).
- **Решение:**
  1. Проверьте прохождение трафика: `tcpdump -i eth0 vrrp`.
  2. Разрешите протокол в Firewall: `iptables -A INPUT -p vrrp -j ACCEPT`.
  3. Если мультикаст запрещен в сети, настройте Unicast в Keepalived через `unicast_peer`.

### Проблемы с HAProxy

**Симптом:** `kubectl` возвращает `503 Service Unavailable`.
- **Причина:** Все бэкенды (API-серверы) помечены как DOWN.
- **Диагностика:**
  ```bash
  # Проверка локального API
  curl -k https://localhost:6444/healthz
  # → ok
  ```
  Если API отвечает, проверьте параметры `check` в `/etc/haproxy/haproxy.cfg`.

### Проблемы с Kube-vip

**Симптом:** VIP не пингуется и не назначается на интерфейс.
- **Диагностика:**
  1. Проверьте логи контейнера `kube-vip`.
  2. Убедитесь, что `kube_vip_interface` указан верно и существует.
  3. В облачных средах (AWS, GCP) Layer 2 VIP не работает без специальных манипуляций; используйте режим BGP или облачный Load Balancer.

### Потеря кворума etcd

**Симптом:** API-сервер не отвечает, поды `etcd` постоянно перезагружаются.
- **Диагностика:** Проверьте логи etcd на наличие ошибок `publish error: etcdserver: request timed out`.
- **Решение:** Следуйте процедуре аварийного восстановления из [руководства по etcd](../../../etcd/clustering_and_recovery.md#аварийное-восстановление-disaster-recovery).

---

## Дополнительная информация

**См. также:**
- [Основные концепции HA Kubespray](./kubespray_ha_concepts.md)
- [Практика развертывания HA](./kubespray_ha_deployment.md)
- [Восстановление кластера etcd](../../../etcd/clustering_and_recovery.md)

**Внешние ресурсы:**
- [Официальная документация kube-vip](https://kube-vip.io/)
- [Kubespray HA Mode Docs](https://github.com/kubernetes-sigs/kubespray/blob/master/docs/ha-mode.md)

