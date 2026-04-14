# Диагностика DNS в контейнерах

## Определения

**DNS в контейнерах** — механизм разрешения имён внутри изолированных сетевых пространств. Отличается от хостового DNS использованием встроенных резолверов (Docker `127.0.0.11`) или внутрикластерных DNS-серверов (CoreDNS в Kubernetes).

**Встроенный DNS Docker** — прокси-сервер на `127.0.0.11`, перенаправляющий запросы к DNS-серверам хоста. Может рассинхронизироваться при изменении сетевой конфигурации хоста.

## Базовые концепции

### Особенности DNS в контейнеризированных средах

| Среда | DNS-сервер | Назначение |
| :--- | :--- | :--- |
| **Docker** | `127.0.0.11` (встроенный) | Прокси к DNS хоста + service discovery |
| **Kubernetes** | CoreDNS (`ClusterIP`) | Обнаружение сервисов внутри кластера |
| **Kubernetes + NodeLocalDNS** | `169.254.25.10` | Кэширование на узлах, снижение нагрузки на CoreDNS |

### Типичные проблемы

- **Docker:** Встроенный DNS не обновляет адреса при смене сети хоста (Wi-Fi, VPN, перезапуск `systemd-resolved`)
- **Kubernetes:** Недоступен CoreDNS, проблемы с `search` доменами и `ndots`
- **Общие:** Контейнер не разрешает внешние имена, но `ping 8.8.8.8` работает

## Практические сценарии

### Сценарий 1: Диагностика DNS в Docker

**Симптом:** Контейнер не разрешает доменные имена, хост работает корректно.

```bash
# 1. Проверить resolv.conf внутри контейнера
docker exec <container> cat /etc/resolv.conf
# nameserver 127.0.0.11 — встроенный DNS Docker

# 2. Проверить разрешение имён
docker exec <container> dig ya.ru
# SERVFAIL или таймаут — проблема с DNS

# 3. Сравнить с хостовым resolv.conf
cat /etc/resolv.conf
```

**Решение — глобальная настройка DNS:**

```json
// /etc/docker/daemon.json
{
  "dns": ["1.1.1.1", "8.8.8.8"]
}
```

```bash
sudo systemctl restart docker
```

**Решение — для конкретного контейнера:**

```bash
docker run --dns=1.1.1.1 my_image
```

> **См. также:** [Решение проблем с DNS в Docker](../../../../Docker/Docker_network/troubleshooting/dns_resolution_issues.md) — полная диагностика и опции `dns-opt`.

### Сценарий 2: Диагностика DNS в Kubernetes

**Симптом:** Поды не разрешают имена сервисов или внешние домены.

```bash
# 1. Проверить статус подов CoreDNS
kubectl get pods -n kube-system | grep dns

# 2. Проверить логи CoreDNS
kubectl logs -n kube-system -l k8s-app=kube-dns

# 3. Проверить resolv.conf внутри пода
kubectl exec <pod> -- cat /etc/resolv.conf
# nameserver 169.254.25.10 — NodeLocalDNS или IP CoreDNS

# 4. Проверить разрешение имени сервиса
kubectl exec <pod> -- nslookup <service>.<namespace>.svc.cluster.local

# 5. Анализ DNS-трафика (если доступен tcpdump)
kubectl exec <pod> -- tcpdump -n -p -i eth0 port 53
```

**Типичные симптомы и причины:**

| Симптом | Возможная причина |
| :--- | :--- |
| `Resolving Timeout` | Недоступен CoreDNS |
| `ErrImagePull` | Не разрешается имя registry |
| `nslookup` работает, приложение нет | Проблема на уровне приложения |
| Медленное разрешение внешних имён | Перебор `search` доменов при `ndots:5` |

> **См. также:** [DNS в Kubernetes](../../../../Kubernetes/Networking/dns_deep_dive.md) — архитектура, оптимизация CoreDNS, NodeLocalDNS.

### Сценарий 3: Проблемы с search доменами и ndots в Kubernetes

**Симптом:** Высокая задержка при обращении к внешним доменам из подов.

**Причина:** При `ndots:5` запрос к `yandex.ru` генерирует 4 DNS-запроса:

1. `yandex.ru.default.svc.cluster.local`
2. `yandex.ru.svc.cluster.local`
3. `yandex.ru.cluster.local`
4. `yandex.ru`

**Решение — использование FQDN:**

```bash
# Вместо короткого имени
curl http://yandex.ru

# Использовать FQDN с точкой на конце
curl http://yandex.ru.
```

**Решение — оптимизация CoreDNS:**

Включить `autopath` в ConfigMap CoreDNS (подробнее в [DNS в Kubernetes](../../../../Kubernetes/Networking/dns_deep_dive.md#оптимизация-через-configmap-coredns)).

## Дополнительная информация

**Связанные темы:** [Решение проблем с DNS в Docker](../../../../Docker/Docker_network/troubleshooting/dns_resolution_issues.md) — Docker DNS детально · [DNS в Kubernetes](../../../../Kubernetes/Networking/dns_deep_dive.md) — K8s DNS архитектура · [Базовая диагностика](./basic_diagnostics.md) — общие принципы диагностики DNS
