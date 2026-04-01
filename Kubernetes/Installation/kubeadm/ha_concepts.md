# High Availability API-сервера с Keepalived и HAProxy

## Определения

**HA Control Plane** — архитектура с несколькими master-узлами для устранения единой точки отказа (SPOF).

**Virtual IP (VIP)** — плавающий IP-адрес, перемещающийся между узлами кластера через протокол VRRP.

**Control Plane Endpoint** — единая точка входа для доступа к API-серверу (`<VIP>:<PORT>` или DNS).

**L4 Load Balancer** — балансировщик транспортного уровня (TCP), не терминирующий TLS.

**VRRP (Virtual Router Redundancy Protocol)** — протокол для автоматического переключения VIP между узлами.

---

## Основные концепции

### Проблема единой точки отказа

В кластере с одним master-узлом при его отказе:

- Доступ к API теряется
- `kubelet` не может получать инструкции
- `kubeadm join` не работает
- Требуется ручное вмешательство

### Решение: VIP + L4-балансировщик

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

**Принцип работы:**

1. **Keepalived** обеспечивает доступность VIP через VRRP (heartbeat между узлами)
2. **HAProxy** балансирует TCP-трафик к API-серверам на всех мастер-узлах
3. При отказе узла VIP мигрирует на резервный, HAProxy исключает узел из ротации

### Компоненты

| Компонент | Назначение | Подробнее |
| :--- | :--- | :--- |
| **Keepalived** | Обеспечение доступности VIP, протокол VRRP, приоритеты MASTER/BACKUP | [Keepalived overview](../../../../Networking/ServicesAndTools/keepalived_overview.md) |
| **HAProxy** | Балансировка трафика к API, TCP mode, health checks | [HAProxy overview](../../../../WebServers/haproxy_overview.md) |

### Архитектурные решения

| Решение | Описание |
| :--- | :--- |
| **VIP на другом порту** | HAProxy слушает `VIP:7443`, так как `6443` занят локальным API |
| **TCP балансировка** | HAProxy не терминирует TLS, трафик прозрачно передаётся API Server |
| **Health checks** | HAProxy проверяет доступность API Server перед отправкой трафика |
| **Размещение на хостах** | Keepalived + HAProxy запускаются на хостах (не в K8s) для bootstrap |

### Требования

| Компонент | Требование |
| :--- | :--- |
| **Количество master-узлов** | 3 (нечётное число для кворума etcd) |
| **ОС** | Ubuntu 20.04+, Debian 11+, Rocky Linux 9+ |
| **Сеть** | Статические IP, доступ между узлами, свободный VIP |
| **Порты** | 6443 (API), 7443 (HAProxy VIP), 8404 (HAProxy stats, опционально) |

### Версии компонентов (актуально на март 2026)

| Компонент | Версия | Статус | EOL |
| :--- | :--- | :--- | :--- |
| **Keepalived** | 2.3.x | Актуальная стабильная | — |
| **HAProxy** | 3.2 LTS | Актуальная LTS | 01 Apr 2030 |
| **HAProxy** | 3.0 LTS | Поддерживается | 01 Apr 2029 |
| **HAProxy** | 2.8 LTS | Поддерживается | 01 Apr 2028 |

> **Важно:** Для production рекомендуется HAProxy 3.2 LTS или 3.0 LTS. Версии 2.6 и старше приближаются к EOL.

---

## Практические сценарии

### Проверка статуса VIP

```bash
# Проверка наличия VIP на интерфейсе
ip addr show | grep <VIP>

# Проверка статуса Keepalived
systemctl status keepalived
journalctl -u keepalived -f

# Определение текущего MASTER
vrrp-send-adv -i <interface> -p <priority>
```

### Проверка состояния HAProxy

```bash
# Статус сервиса
systemctl status haproxy

# Проверка конфигурации
haproxy -c -f /etc/haproxy/haproxy.cfg

# Статистика через stats socket (если настроен)
echo "show stat" | socat /run/haproxy/admin.sock stdio
```

### Тестирование failover

```bash
# 1. На клиенте запустить непрерывный запрос
watch kubectl get nodes

# 2. На текущем MASTER остановить Keepalived
sudo systemctl stop keepalived

# 3. Наблюдать переключение VIP (2-3 секунды)
# 4. Запустить Keepalived обратно
sudo systemctl start keepalived
```

### Диагностика проблем

```bash
# Логи Keepalived
journalctl -u keepalived -f --no-pager

# Логи HAProxy
journalctl -u haproxy -f --no-pager

# Проверка VRRP-пакетов (требуется tcpdump)
sudo tcpdump -i <interface> -n vrrp

# Проверка доступности backend'ов
curl -k https://<master-ip>:6443/healthz
```

**Типичные проблемы:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| VIP не мигрирует | Блокировка firewall | Открыть протокол VRRP (IP protocol 112) |
| HAProxy не видит backend | Неправильный IP:порт | Проверить конфигурацию backend |
| Split-brain (два MASTER) | Потеря heartbeat | Настроить unicast-режим, выделенный канал |
| Долгое переключение | Низкий advert_int | Уменьшить `advert_int` до 1 секунды |

---

## Дополнительная информация

### Best Practices

| Практика | Описание |
| :--- | :--- |
| **Нечётное число master** | 3 или 5 узлов для кворума etcd |
| **Размещение в разных стойках** | Избегание SPOF на уровне инфраструктуры |
| **Unicast VRRP** | Обязательно для production, multicast запрещён в облаках |
| **Выделенный heartbeat-канал** | Прямое соединение между узлами или LACP |
| **Мониторинг VIP** | Проверка доступности VIP и HAProxy |
| **Тестирование failover** | Регулярная проверка переключения MASTER → BACKUP |
| **Firewall правила** | Открыть порты 6443, 7443, 8404, протокол VRRP |

### Альтернативы

| Решение | Среда | Описание |
| :--- | :--- | :--- |
| **Cloud Load Balancer** | AWS/GCP/Azure | NLB/ELB для балансировки API Server |
| **kube-vip** | Bare-metal, VM | VIP внутри Kubernetes (DaemonSet), упрощает развёртывание |
| **MetalLB + Ingress** | Bare-metal | Балансировка для сервисов, не для API |

### Интеграция с процессом развёртывания

Настройка Keepalived + HAProxy — **шаг 1** перед [инициализацией кластера](./cluster_initialization.md). Подробная инструкция по установке — в [keepalived_haproxy_setup.md](./keepalived_haproxy_setup.md). Общая архитектура HA кластера описана в [обзоре](../../HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md).
