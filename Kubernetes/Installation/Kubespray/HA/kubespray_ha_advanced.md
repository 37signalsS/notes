# Kubespray: Развертывание HA-кластера — Продвинутые темы

## Определения

**Отказоустойчивость (High Availability, HA)** — архитектурный подход, обеспечивающий непрерывную работу системы при выходе из строя отдельных компонентов. В Kubespray это достигается резервированием узлов Control Plane и etcd.

**Виртуальный IP (VIP)** — плавающий IP-адрес для доступа к API-серверу, который автоматически перемещается на активный мастер-узел при сбое текущего лидера.

**VRRP (Virtual Router Redundancy Protocol)** — сетевой протокол, используемый Keepalived для обнаружения отказов и автоматического переключения VIP между узлами в L2-сегменте.

**Split-Brain** — критическое состояние, при котором из-за сетевой изоляции два или более узла одновременно объявляют себя лидерами и используют один и тот же VIP, что приводит к конфликтам в сети и нестабильности API.

**Ротация сертификатов** — процесс плановой или экстренной замены TLS-сертификатов компонентов кластера (API-server, etcd, Kubelet) до истечения срока их действия.

---

## Основные концепции

### Тюнинг параметров отказоустойчивости

Настройка поведения механизмов HA выполняется через переменные в `inventory/mycluster/group_vars/k8s_cluster/k8s-cluster.yml` или `all/all.yml`.

| Переменная | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| **`loadbalancer_apiserver_localhost`** | `false` | Если `true`, на каждом рабочем узле запускается локальный прокси (nginx/haproxy) для связи с мастерами. Рекомендуется для стабильности при отсутствии VIP. |
| **`enable_keepalived`** | `false` | Активация Keepalived для управления VIP. Требует включенного `loadbalancer_apiserver`. |
| **`kube_vip_enabled`** | `false` | Включение современного решения kube-vip. Рекомендуемый стандарт для Bare-metal. |
| **`kube_vip_address`** | — | Целевой IP-адрес, который будет назначен как VIP. |
| **`kube_vip_interface`** | — | Сетевой интерфейс, на котором будет поднят VIP (например, `eth0` или `bond0`). |
| **`keepalived_virtual_router_id`** | `51` | Уникальный ID группы VRRP. Не должен конфликтовать с другими инстансами в той же подсети. |

### Взаимодействие с сетевыми плагинами (CNI)

При выборе метода HA необходимо учитывать особенности сетевой подсистемы:
- **Calico:** При использовании BGP в Calico и BGP в kube-vip может потребоваться настройка пиринга с разными AS-номерами или использование разных сетевых интерфейсов во избежание конфликтов маршрутизации.
- **Cilium:** Поддерживает встроенную балансировку через eBPF. В сложных топологиях Cilium может брать на себя функции маршрутизации до API-сервера, делая внешние VIP избыточными.

### Внешние облачные балансировщики

В средах AWS, GCP или Azure использование VIP через Keepalived/L2 невозможно. В этом случае Kubespray настраивается на использование внешнего LB:
- **`external_apiserver_address`**: DNS или IP адрес облачного балансировщика.
- **`external_apiserver_port`**: Порт балансировщика (обычно 443 или 6443).
Kubespray автоматически добавит этот адрес в SAN (Subject Alternative Names) сертификатов API-сервера.

---

## Практические сценарии

### 1. Тестирование отказоустойчивости (Keepalived + HAProxy)

#### Сценарий A: Миграция VIP при отказе узла
1.  **Определите лидера:**
    ```bash
    ip a show | grep <VIP_ADDRESS>
    # → inet 192.168.1.100/32 scope global eth0
    ```
2.  **Имитируйте сбой:** Остановите службу Keepalived на текущем лидере:
    ```bash
    systemctl stop keepalived
    ```
3.  **Проверьте переключение:** На соседнем мастере убедитесь, что VIP появился в выводе `ip a`. Время переключения обычно составляет 1–3 секунды.

#### Сценарий B: Исключение API-сервера из балансировки
1.  Остановите API-сервер на одном из мастеров:
    ```bash
    systemctl stop kube-apiserver
    ```
2.  Проверьте статус бэкенда через сокет HAProxy:
    ```bash
    echo "show stat" | socat stdio /var/run/haproxy/admin.sock | grep kubernetes-api
    # → kubernetes-api-masters,master-1,0,0,0,0,,0,0,0,,0,,OFFLINE,...
    ```
    HAProxy должен пометить узел как `OFFLINE` и перестать направлять на него трафик.

### 2. Тестирование отказоустойчивости (Kube-vip)

1.  **Проверка статуса пода:**
    ```bash
    kubectl get pods -n kube-system -l name=kube-vip
    ```
2.  **Проверка лидерства в логах:**
    ```bash
    kubectl logs -n kube-system -l name=kube-vip --tail=50
    # → INFO[0005] Node <hostname> is now the leader
    ```
3.  **Имитация отказа:** Временно переместите манифест из `/etc/kubernetes/manifests/kube-vip.yaml` в `/tmp/`. Kubelet остановит под, и лидерство перейдет к другому узлу.

### 3. Ротация сертификатов кластера

Плановая замена всех сертификатов (API, etcd, kubelet) выполняется одним запуском плейбука:

```bash
ansible-playbook -i inventory/mycluster/hosts.yml cluster.yml \
  --become --become-user=root \
  --tags=rotate_certs
```
Для обновления только сертификатов etcd используйте `--tags=etcd,rotate_certs`.

### 4. Масштабирование etcd и Control Plane

Добавление нового мастер-узла в существующий HA-кластер:
1.  Добавьте новый узел в секции `[kube_control_plane]` и `[etcd]` вашего инвентаря.
2.  Запустите плейбук масштабирования:
    ```bash
    ansible-playbook -i inventory/mycluster/hosts.yml scale.yml --limit=new_node_name
    ```
3.  **Важно:** Kubespray автоматически обновит конфигурацию балансировщиков (HAProxy/nginx-proxy) на всех существующих узлах.

---

## Дополнительная информация

### Устранение неполадок

#### Проблемы с VIP (Keepalived / Kube-vip L2)
**Симптом:** VIP назначен на нескольких узлах одновременно (Split-brain).
- **Диагностика:** Проверьте наличие VRRP-трафика: `tcpdump -i any proto 112`.
- **Решение:** 
    1. Разрешите VRRP в iptables: `iptables -A INPUT -p vrrp -j ACCEPT`.
    2. Перейдите на Unicast, если мультикаст заблокирован в сети:
       ```yaml
       # в group_vars/all/all.yml
       keepalived_unicast_peers: [10.0.1.11, 10.0.1.12]
       ```

#### Проблемы с etcd (Потеря кворума)
**Симптом:** API-сервер возвращает ошибки таймаута, поды etcd в `CrashLoopBackOff`.
- **Диагностика:** Проверьте статус кластера:
  ```bash
  kubectl exec -n kube-system etcd-master-1 -- etcdctl endpoint status --cluster -w table
  ```
- **Решение:** Если кворум (n/2+1) потерян, требуется процедура восстановления. См. [Восстановление etcd](../../../../etcd/clustering_and_recovery.md).

#### Ошибки 503 Service Unavailable (HAProxy)
**Симптом:** Трафик не проходит через VIP, хотя порты открыты.
- **Диагностика:** Проверьте доступность API локально: `curl -k https://localhost:6443/healthz`.
- **Решение:** Убедитесь, что параметры `check` в `/etc/haproxy/haproxy.cfg` соответствуют актуальному порту API-сервера.

### См. также
- [Основные концепции HA Kubespray](./kubespray_ha_concepts.md) — теория и схемы.
- [Практика развертывания HA](./kubespray_ha_deployment.md) — пошаговая настройка.
- [Восстановление кластера etcd](../../../../etcd/clustering_and_recovery.md) — действия при авариях.
- [Обслуживание узлов](../../../Operations/node_maintenance.md) — регламент работ на узлах.

### Внешние ресурсы
- [Official kube-vip Documentation](https://kube-vip.io/)
- [Keepalived User Guide](https://www.keepalived.org/doc/index.html)
- [HAProxy Configuration Manual](https://docs.haproxy.org/2.8/configuration.html)
