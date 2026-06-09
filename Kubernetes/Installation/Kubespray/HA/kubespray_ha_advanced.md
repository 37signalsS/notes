# Kubespray: Развертывание HA-кластера — Дополнительные темы

## Определения

Основные термины и архитектурные концепции представлены в [основных концепциях](./kubespray_ha_concepts.md).

## Основные концепции

### Конфигурационные файлы Kubespray

| Файл | Назначение |
| :--- | :--- |
| `inventory/my-cluster/inventory.ini` | Хосты и роли |
| `group_vars/all/all.yml` | Общие переменные |
| `group_vars/k8s_cluster/k8s-cluster.yml` | Параметры K8s |
| `group_vars/etcd/etcd.yml` | Настройки etcd |

### Переменные для HA

| Переменная | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `loadbalancer_apiserver_localhost` | `false` | Включить локальный HAProxy |
| `enable_keepalived` | `true` | Включить Keepalived |
| `keepalived_virtual_router_id` | `51` | VRRP router ID |
| `kube_apiserver_insecure_port` | `0` | Небезопасный порт API |

## Практические сценарии

### Тестирование отказоустойчивости

#### Тест 1: Отключение MASTER узла

```bash
# На текущем MASTER узле
systemctl stop keepalived

# На другом узле проверить появление VIP
ip a show dev eth0 | grep 192.168.1.100

# API должен оставаться доступным
kubectl get nodes
```

#### Тест 2: Отключение kube-apiserver

```bash
# На одном из master
systemctl stop kube-apiserver

# HAProxy должен исключить узел из ротации
echo "show stat" | socat stdio /var/run/haproxy/admin.sock | \
  grep kubernetes-api-masters
```

#### Тест 3: Отключение etcd

```bash
# На одном из master
systemctl stop etcd

# Кластер должен оставаться работоспособным (2 из 3)
kubectl get pods --all-namespaces
```

### Устранение неполадок

#### Проблема: VIP не назначается

```bash
# Проверка VRRP трафика
tcpdump -n -i eth0 vrrp

# Проверка логов Keepalived
journalctl -u keepalived -n 50
```

#### Проблема: HAProxy не видит бэкенды

```bash
# Проверка доступности API-серверов
curl -k https://192.168.1.10:6444/healthz

# Перезапуск HAProxy
systemctl restart haproxy
```

#### Проблема: etcd кворум потерян

```bash
# Статус etcd на каждом узле
etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/peer-$(hostname).pem \
  --key=/etc/ssl/etcd/ssl/peer-$(hostname)-key.pem \
  endpoint health
```

## Дополнительная информация

**См. также:**

- [Обзор Kubespray](../overview.md)
- [Развертывание в закрытом контуре](../offline_installation/offline_definitions.md)
- [Ручная настройка HA с kubeadm](../../kubeadm/ha_concepts.md)

**Внешние ресурсы:**

- [Документация Kubespray](https://kubespray.io/)
- [GitHub проекта](https://github.com/kubernetes-sigs/kubespray)
- [VRRP RFC 5798](https://datatracker.ietf.org/doc/html/rfc5798)
