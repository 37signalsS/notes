# Service Discovery в Kubernetes

> Полная информация о DNS в Kubernetes находится в файле [DNS в Kubernetes](../dns_deep_dive.md).

## Определения

**Service Discovery** — механизм автоматического обнаружения сервисов в кластере Kubernetes через DNS-имена вместо IP-адресов.

## Основные концепции

IP-адреса подов могут меняться при перезапуске, поэтому Kubernetes предоставляет встроенный DNS для стабильного обращения к сервисам.

### Разрешение имен

- **Имя сервиса:** `my-service.my-ns.svc.cluster.local` (полное)
- **Короткое имя:** `my-service` (из того же неймспейса)

### Важное замечание

Настройки DNS на уровне Docker (`--dns`, `/etc/docker/daemon.json`) **игнорируются** для подов Kubernetes. `Kubelet` самостоятельно управляет `/etc/resolv.conf` в подах.

## Практические сценарии

Для детальной информации о CoreDNS, NodeLocalDNS, конфигурации и оптимизации DNS см. [DNS в Kubernetes](../dns_deep_dive.md).
