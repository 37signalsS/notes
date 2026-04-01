# Service Discovery в Kubernetes

> **SSoT:** Полная информация о DNS в Kubernetes — в файле [DNS в Kubernetes](../dns_deep_dive.md).

## Определения

**Service Discovery** — механизм автоматического обнаружения сервисов в кластере Kubernetes через стабильные DNS-имена вместо изменяющихся IP-адресов подов.

**DNS-имя сервиса** — стабильный адрес сервиса в формате FQDN, который не меняется при перезапуске подов.

## Основные концепции

### Проблема изменчивых IP-адресов

IP-адреса подов в Kubernetes динамические и могут меняться при:
- Перезапуске пода
- Масштабировании Deployment
- Миграции пода между узлами
- Обновлении версии приложения

Для решения этой проблемы Kubernetes предоставляет встроенную DNS-систему, которая автоматически обновляет записи при изменениях в кластере.

### Формат DNS-имён

| Тип имени | Формат | Пример | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Полное (FQDN)** | `<service>.<namespace>.svc.cluster.local` | `redis.default.svc.cluster.local` | Из другого неймспейса |
| **Короткое** | `<service>` | `redis` | Из того же неймспейса |
| **С неймспейсом** | `<service>.<namespace>` | `redis.default` | Из другого неймспейса (сокращённо) |

**Домен кластера по умолчанию:** `cluster.local` (настраивается через флаг `--cluster-domain` у `kubelet`).

### Принцип работы

1. **Создание Service:** При создании объекта `Service` API-сервер регистрирует его в DNS.
2. **DNS-запись:** CoreDNS создаёт A-запись, указывающую на `ClusterIP` сервиса.
3. **Разрешение имени:** Когда под запрашивает имя сервиса, DNS возвращает его стабильный `ClusterIP`.
4. **Маршрутизация:** `kube-proxy` направляет трафик с `ClusterIP` на один из подов сервиса.

### Важное замечание о Docker DNS

Настройки DNS на уровне Docker **игнорируются** для подов Kubernetes:
- Флаг `--dns` в `docker run`
- Файл `/etc/docker/daemon.json`
- Настройки DNS в Docker Compose

`Kubelet` самостоятельно управляет `/etc/resolv.conf` в подах, указывая на внутрикластерный DNS (CoreDNS или NodeLocalDNS).

## Практические сценарии

### Обращение к сервису из того же неймспейса

```bash
# Из пода в неймспейсе default
curl http://redis:6379
```

### Обращение к сервису из другого неймспейса

```bash
# Из пода в неймспейсе production
curl http://redis.default.svc.cluster.local:6379
# или сокращённо:
curl http://redis.default:6379
```

### Диагностика DNS в кластере

```bash
# Проверка разрешения имени из пода
kubectl run dns-test --rm -it --image=busybox -- nslookup redis.default.svc.cluster.local

# Проверка статуса CoreDNS
kubectl get pods -n kube-system -l k8s-app=kube-dns

# Просмотр логов CoreDNS
kubectl logs -n kube-system -l k8s-app=kube-dns
```

### Типичные проблемы

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| `nslookup` работает, приложение нет | Проблема на уровне приложения | Проверить конфиг приложения |
| `Resolving Timeout` | Недоступен CoreDNS | Проверить поды DNS в `kube-system` |
| `ErrImagePull` | Не разрешается имя registry | Проверить `/etc/resolv.conf` на узле |
| Задержки DNS | Нет кеширования | Включить NodeLocalDNS |

## Дополнительная информация

**См. также:**
- [DNS в Kubernetes (SSoT)](../dns_deep_dive.md) — CoreDNS, NodeLocalDNS, конфигурация, оптимизация
- [Обзор сетевой модели Kubernetes](./network_overview.md) — CNI, kube-proxy, NetworkPolicy
- [Диагностика DNS в Linux](../../Linux/Diagnostics/Networking/dns/overview.md) — общие принципы диагностики
