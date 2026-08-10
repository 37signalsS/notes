# Диагностика DNS в контейнерах

## Определения

**DNS в контейнерах** — механизм разрешения доменных имён внутри изолированных сетевых пространств (Network Namespaces). В отличие от классических систем, контейнеры используют специализированные резолверы-посредники (Docker `127.0.0.11`) или кластерные службы (CoreDNS в Kubernetes), что вносит дополнительные уровни абстракции и потенциальные точки отказа.

**Встроенный DNS Docker (Embedded DNS)** — локальный резолвер на адресе `127.0.0.11`, работающий в пользовательских сетях (user-defined networks). Он обеспечивает обнаружение контейнеров по их именам и проксирование внешних запросов на хост.

**CoreDNS** — модульный DNS-сервер, являющийся стандартом в Kubernetes. Он интегрирован с Kubernetes API и динамически управляет записями для Service и Pod.

## Базовые концепции

### Архитектурные особенности

| Среда | DNS-резолвер | Особенности |
| :--- | :--- | :--- |
| **Docker (bridge)** | Хостовый `/etc/resolv.conf` | Прямое наследование настроек хоста. Имена соседних контейнеров не разрешаются. |
| **Docker (user-net)** | `127.0.0.11` | Встроенный сервер. Поддержка Service Discovery по имени контейнера/сервиса. |
| **Kubernetes** | CoreDNS ClusterIP | Разрешение FQDN вида `<svc>.<ns>.svc.cluster.local`. Использование `ndots:5`. |
| **NodeLocalDNS** | `169.254.25.10` | Кэширующий агент (DaemonSet) для снижения задержек и нагрузки на CoreDNS. |

### Критические точки отказа

1. **Конфликт с systemd-resolved (Loopback):** Если на хосте используется `systemd-resolved` (адрес `127.0.0.53`), Docker не может пробросить этот адрес внутрь контейнера, так как он зациклен на loopback хоста. Docker автоматически заменяет его на публичные DNS (8.8.8.8), что блокирует разрешение внутренних (VPN/корпоративных) доменов.
2. **Проблема ndots в Kubernetes:** Параметр `ndots:5` (по умолчанию) заставляет резолвер перебирать все суффиксы из `search` (например, `google.com.default.svc.cluster.local`), если в имени меньше 5 точек. Это приводит к задержкам и лишнему трафику к CoreDNS.
3. **Особенности библиотек (glibc vs musl):**
   - **glibc (Debian/Ubuntu/CentOS):** Разрешает A и AAAA запросы последовательно. Поддерживает опцию `rotate`.
   - **musl (Alpine):** Разрешает A и AAAA параллельно. Если Firewall или DNS-сервер некорректно обрабатывает параллельные UDP-запросы с одного порта, это приводит к таймаутам.
4. **MTU и фрагментация:** Большие DNS-ответы (например, с DNSSEC или длинными списками IP в Headless Service) могут превышать MTU в Overlay-сетях (VXLAN), что приводит к потере пакетов и ошибкам разрешения.

## Практические сценарии

### Сценарий 1: Диагностика в Docker (Сеть и Конфигурация)

Если контейнер не видит внешние адреса или соседей по сети:

```bash
# 1. Проверка текущих настроек резолвера
docker exec <container_id> cat /etc/resolv.conf
# Ожидаемый результат для user-defined network: nameserver 127.0.0.11

# 2. Проверка разрешения через встроенный DNS Docker
docker exec <container_id> nslookup <target_container_name>
# → Server: 127.0.0.11, Address: 127.0.0.11#53

# 3. Глубокая диагностика с использованием netshoot (если в образе нет утилит)
docker run --rm -it --net container:<container_id> nicolaka/netshoot dig google.com
```

**Решение:** Если `127.0.0.11` возвращает `SERVFAIL`, проверьте доступность DNS на хосте. Для обхода проблем с `systemd-resolved` укажите DNS явно в `/etc/docker/daemon.json`.

### Сценарий 2: Оптимизация и отладка в Kubernetes

При жалобах на медленный DNS или ошибки `NXDOMAIN`:

```bash
# 1. Тест с замером времени и обходом ndots (точка в конце)
kubectl exec <pod_name> -- time nslookup google.com.
# → real 0m0.010s (быстро, так как это FQDN)

# 2. Проверка состояния CoreDNS и его эндпоинтов
kubectl get endpoints -n kube-system -l k8s-app=kube-dns
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=20

# 3. Проверка конфигурации пода (ndots)
kubectl get pod <pod_name> -o jsonpath='{.spec.dnsConfig}'
```

**Решение:** Для снижения задержек используйте **NodeLocal DNSCache** или уменьшите `ndots` до 2 в `spec.dnsConfig` пода, если приложение использует в основном внешние FQDN.

### Сценарий 3: Диагностика "черных дыр" (nsenter и tcpdump)

Когда стандартные утилиты не помогают, необходимо смотреть трафик на уровне сетевого пространства имен.

```bash
# 1. Поиск PID процесса контейнера
PID=$(docker inspect -f '{{.State.Pid}}' <container_id>)

# 2. Перехват DNS-трафика (порт 53) внутри пространства имен контейнера
sudo nsenter -t $PID -n tcpdump -i any port 53 -vv
# → Позволяет увидеть, уходят ли запросы и приходят ли ответы
```

### Сводная таблица типичных ошибок

| Ошибка | Вероятная причина | Метод проверки |
| :--- | :--- | :--- |
| **NXDOMAIN** | Ошибка в имени или неверный `ndots`. | Проверить имя с точкой в конце (`host.com.`). |
| **SERVFAIL** | Upstream DNS недоступен или заблокирован. | `dig @<upstream_ip> google.com` с хоста. |
| **Timeout (5s)** | Параллельные A/AAAA запросы (musl) или MTU. | Добавить `options single-request-reopen` в `resolv.conf`. |
| **127.0.0.11:53: i/o timeout** | Ошибка в Docker Network или Firewall. | Проверить цепочки iptables (DOCKER_OUTPUT). |

## Дополнительная информация

- **[Решение проблем с DNS в Docker](../../../../Docker/Docker_network/troubleshooting/dns_resolution_issues.md)** — детальный разбор и SSoT для среды Docker.
- **[DNS в Kubernetes: Глубокое погружение](../../../../Kubernetes/Networking/dns_deep_dive.md)** — архитектура CoreDNS, NodeLocalDNS и политики `dnsPolicy`.
- **[Базовая диагностика DNS](./basic_diagnostics.md)** — общие методы проверки связности и утилиты.
- **[Производительность DNS-резолвинга](./dns_resolution_performance.md)** — оптимизация параметров и решение проблем с `conntrack`.
- **[Инструмент dig](./dig_tool.md)** — анализ флагов и структуры ответов.
