# Диагностика DNS в контейнерах

## Определения

**DNS в контейнерах** — механизм разрешения доменных имён внутри изолированных сетевых пространств (Network Namespaces). В отличие от классических систем, контейнеры используют специализированные резолверы-посредники (Docker `127.0.0.11`, Podman Aardvark-DNS) или кластерные службы (CoreDNS в Kubernetes), что вносит дополнительные уровни абстракции и потенциальные точки отказа.

**Встроенный DNS Docker (Embedded DNS)** — локальный резолвер на адресе `127.0.0.11`, работающий в пользовательских сетях (user-defined networks). Он обеспечивает обнаружение контейнеров по их именам и проксирование внешних запросов на хост. Также реализует защиту от DNS Rebinding (запрет на возврат приватных RFC1918-адресов для внешних имён).

**CoreDNS** — модульный DNS-сервер, являющийся стандартом в Kubernetes. Он интегрирован с Kubernetes API и динамически управляет записями для Service и Pod.

**containerd / CRI-O** — контейнерные рантаймы (Container Runtime Interface), используемые Kubernetes по умолчанию. В отличие от Docker Engine, они не имеют встроенного DNS-посредника и наследуют `/etc/resolv.conf` хоста для контейнеров.

**Podman (Aardvark-DNS + Netavark)** — альтернативный контейнерный движок. В rootful-режиме использует Netavark (bridge + nftables) и Aardvark-DNS для разрешения имён. В rootless-режиме — pasta, который не предоставляет встроенного DNS (контейнеры изолированы на уровне L3).

**DNS Rebinding Protection** — механизм безопасности, при котором встроенный DNS Docker (127.0.0.11) блокирует возврат приватных IP-адресов (RFC1918, CGNAT, loopback) для внешних доменов. Это предотвращает атаки, когда вредоносный сайт возвращает внутренний адрес для обхода Same-Origin Policy.

## Базовые концепции

### Архитектурные особенности

| Среда | DNS-резолвер | Особенности |
| :--- | :--- | :--- |
| **Docker (bridge)** | Хостовый `/etc/resolv.conf` | Прямое наследование настроек хоста. Имена соседних контейнеров не разрешаются. |
| **Docker (user-net)** | `127.0.0.11` | Встроенный сервер. Поддержка Service Discovery по имени контейнера/сервиса. Защита от DNS Rebinding. TTL ответов 600 с. |
| **containerd / CRI-O** | Хостовый `/etc/resolv.conf` | Наследует настройки узла напрямую. Нет посредника. Копируется при создании sandbox. |
| **Kubernetes** | CoreDNS ClusterIP | Разрешение FQDN вида `<svc>.<ns>.svc.cluster.local`. Использование `ndots:5`. |
| **NodeLocalDNS** | `169.254.25.10` | Кэширующий агент (DaemonSet) для снижения задержек и нагрузки на CoreDNS. |
| **Podman (rootful, bridge)** | Aardvark-DNS | DNS включен по умолчанию даже в стандартной сети `podman` (10.88.0.0/16). |
| **Podman (rootless, pasta)** | Нет встроенного DNS | Pasta работает в режиме L3-изоляции без NAT. Контейнеры не видят друг друга по именам без отдельной сети. |
| **Docker Swarm** | Встроенный DNS / VIP | В режиме VIP сервис получает один виртуальный IP. В режиме DNSRR возвращаются IP всех реплик. |

### Критические точки отказа

1. **Конфликт с systemd-resolved (DNS Loop):** Если на хосте используется `systemd-resolved` (адрес `127.0.0.53`), Docker или CoreDNS могут попасть в бесконечную петлю перенаправления. Docker автоматически заменяет этот адрес на публичные DNS (8.8.8.8) для контейнеров, что может заблокировать доступ к внутренним ресурсам.
   - **Диагностика:** См. детальные методы захвата трафика и сценарии петель в **[Петли перенаправления DNS](../../../../Networking/Protocols/DNS/dns_forwarding_loops.md)**.

2. **Проблема ndots в Kubernetes:** Параметр `ndots:5` (по умолчанию) заставляет резолвер перебирать все суффиксы из `search` (например, `google.com.default.svc.cluster.local`), если в имени меньше 5 точек. Это приводит к задержкам и лишнему трафику к CoreDNS.

3. **Особенности библиотек (glibc vs musl):**
   - **glibc (Debian/Ubuntu/CentOS):** Разрешает A и AAAA запросы последовательно. Поддерживает опцию `rotate`.
   - **musl (Alpine):** Разрешает A и AAAA параллельно. Если Firewall или DNS-сервер некорректно обрабатывает параллельные UDP-запросы с одного порта, это приводит к таймаутам.

4. **MTU и фрагментация:** Большие DNS-ответы (например, с DNSSEC или длинными списками IP в Headless Service) могут превышать MTU в Overlay-сетях (VXLAN), что приводит к потере пакетов и ошибкам разрешения.

5. **Docker 29.1.0 — регресс DNS-кэша:** В этой версии был обнаружен баг, приводящий к некорректному кэшированию DNS. Рекомендуется обновление до 29.1.1+.

6. **Конфликт портов и nftables (Podman 6.0):** В Podman 6.0 поддержка iptables удалена, firewall настраивается через nftables. Если порт 53 уже занят другим процессом на хосте, Aardvark-DNS не запустится.

### Инструменты диагностики

| Инструмент | Область применения | Примечание |
| :--- | :--- | :--- |
| `docker exec` / `kubectl exec` | Проверка `/etc/resolv.conf` и базовый резолвинг | Первый шаг в контейнере |
| `crictl exec` | Диагностика в containerd/CRI-O без Docker CLI | Требует наличия `dnsutils` в образе |
| `nerdctl` | Альтернатива Docker CLI для containerd | Прямой доступ к CRI |
| `nsenter` | Переход в network namespace контейнера | Для захвата трафика без остановки контейнера |
| `tcpdump` / `tshark` | Захват DNS-трафика (UDP/TCP 53) | В паре с `nsenter` для контейнеров |
| `nicolaka/netshoot` | Диагностический образ с полным набором утилит | Запуск в той же сети, что и целевой контейнер |
| `registry.k8s.io/dnsutils:1.3` | Стандартный образ для K8s DNS-отладки | Содержит `dig`, `nslookup`, `host` |
| `dig` с `+trace` | Трассировка иерархии DNS | Обнаруживает точку обрыва |
| `nc` / `nmap` | Проверка доступности UDP/TCP 53 | Диагностика firewall |
| `resolvectl` | Диагностика systemd-resolved на хосте | Для понимания контекста хоста |
| `podman network inspect` | Просмотр DNS-параметров сети | Проверка subnet, gateway, DNS IP |

### Валидация результатов исправления

После любого изменения DNS-конфигурации в контейнере или кластере выполните проверку:

```bash
# 1. Проверка resolv.conf
docker exec <container> cat /etc/resolv.conf
# → Должен содержать ожидаемый nameserver (127.0.0.11, 10.96.0.10 и т.д.)

# 2. Проверка разрешения внешнего домена
docker exec <container> nslookup google.com
# → Address: <ожидаемый внешний IP>

# 3. Проверка разрешения внутреннего домена (если применимо)
docker exec <container> nslookup my-service.default.svc.cluster.local
# → Address: <ClusterIP или IP пода>

# 4. Замер latency
docker exec <container> time nslookup my-service.default.svc.cluster.local
# → real < 0.05s (при наличии кэша)

# 5. Проверка через getent (NSS)
docker exec <container> getent hosts my-service.default.svc.cluster.local
# → Должен совпадать с nslookup
```

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

**Решение:** Если `127.0.0.11` возвращает `SERVFAIL`, проверьте доступность DNS на хосте. Для обхода проблем с `systemd-resolved` укажите DNS явно в `/etc/docker/daemon.json`. Для постоянного применения:

```json
{
  "dns": ["10.0.0.2", "10.0.0.3"],
  "dns-search": ["company.local", "dev.internal"]
}
```

**Валидация:** После перезапуска контейнера `cat /etc/resolv.conf` должен показывать указанные серверы. `nslookup internal.company.com` должен возвращать внутренний IP.

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

**Решение:** Для снижения задержек используйте **NodeLocal DNSCache** или уменьшите `ndots` до 2 в `spec.dnsConfig` пода, если приложение использует в основном внешние FQDN. Для постоянного применения (опция `single-request-reopen` действует только в glibc-образах; в Alpine/musl игнорируется):

```yaml
spec:
  dnsConfig:
    options:
    - name: ndots
      value: "2"
    - name: single-request-reopen
      value: ""
    - name: timeout
      value: "2"
```

**Валидация:** После применения `kubectl exec <pod> -- time nslookup google.com` должен показывать `real < 0.05s`. Проверьте 10 последовательных запросов — время должно быть стабильным.

### Сценарий 3: Диагностика "черных дыр" (nsenter и tcpdump)

Когда стандартные утилиты не помогают, необходимо смотреть трафик на уровне сетевого пространства имен.

```bash
# 1. Поиск PID процесса контейнера
PID=$(docker inspect -f '{{.State.Pid}}' <container_id>)

# 2. Перехват DNS-трафика (порт 53) внутри пространства имен контейнера
sudo nsenter -t $PID -n tcpdump -i any port 53 -vv
# → Позволяет увидеть, уходят ли запросы и приходят ли ответы
```

**Расширенная диагностика:** Если `tcpdump` показывает исходящие запросы, но ответов нет:
```bash
# Проверка firewall на хосте
sudo iptables -L -n | grep -E "53|DROP|REJECT"
# Или для nftables
sudo nft list ruleset | grep -E "53|drop|reject"

# Проверка DOCKER_OUTPUT цепи
sudo iptables -L DOCKER_OUTPUT -n -v
```

**Валидация:** В выводе `tcpdump` должны присутствовать парные запрос/ответ. Если запросы есть, а ответов нет — проблема на уровне хостового firewall или upstream DNS.

### Сценарий 4: Диагностика в containerd / CRI-O (crictl)

Kubernetes-кластеры на containerd или CRI-O не наследуют встроенный DNS Docker. Резолв настроек происходит через `/etc/resolv.conf` хоста.

```bash
# 1. Проверка DNS внутри контейнера через crictl
crictl exec <container_id> cat /etc/resolv.conf
# → Должен содержать nameserver 10.96.0.10 (CoreDNS ClusterIP)

# 2. Проверка резолвинга
crictl exec <container_id> nslookup kubernetes.default
# → Address: 10.96.0.1

# 3. Проверка обратной связи с узлом
crictl exec <container_id> ping -c 1 kubernetes.default
```

**Распространённая ошибка:** containerd копирует `/etc/resolv.conf` хоста при создании sandbox. Если на хосте `resolv.conf` указывает на `127.0.0.53` (systemd-resolved), контейнер получит бесполезный адрес.

**Решение:** Настройте kubelet на использование чистого `resolv.conf` хоста:
```bash
# В /var/lib/kubelet/kubeadm-flags.env или системном юните kubelet:
--resolv-conf=/run/systemd/resolve/resolv.conf
```

**Валидация:** `crictl exec <id> cat /etc/resolv.conf` должен показывать реальные DNS-серверы, а не loopback.

### Сценарий 5: Podman rootless — отладка Aardvark-DNS

В Podman 6.0 rootless-режим использует pasta, который не предоставляет DNS между контейнерами. Для Service Discovery требуется создание отдельной user-defined bridge-сети.

```bash
# 1. Проверка сетевого бэкенда
podman info --format '{{.Host.NetworkBackend}}'
# → netavark (rootful) или pasta (rootless)

# 2. Создание сети с DNS
podman network create app-net
# → Создаётся subnet 10.88.0.0/16, Aardvark-DNS включён

# 3. Запуск контейнеров в сети
podman run -d --name web --network app-net nginx
podman run -d --name api --network app-net my-api

# 4. Проверка разрешения
podman exec web nslookup api
# → Name:    api
# → Address: 10.88.0.2
```

**Частая проблема:** В rootless-режиме pasta по умолчанию изолирует контейнеры. Если контейнеры в разных сетях, DNS не работает. Решение — разместить их в одной user-defined bridge-сети.

**Валидация:** `podman exec web getent hosts api` должен возвращать IP. `podman network inspect app-net` должен показывать активные контейнеры в секции `Containers`.

### Сценарий 6: Docker Swarm — VIP vs DNSRR

В Swarm-режиме сервисы разрешаются через встроенный DNS. Режим балансировки влияет на ответ DNS.

```bash
# 1. Создание сервиса с режимом VIP (по умолчанию)
docker service create --name web --replicas 3 -p 80:80 nginx

# 2. Проверка DNS-имени сервиса
docker service ls
# → NAME   REPLICAS   IMAGE
# → web    3/3        nginx:latest

# 3. Разрешение имени сервиса
docker exec <task> nslookup web
# → Name:   web
# → Address: 10.0.0.2  (VIP — один виртуальный IP)

# 4. Переключение на DNSRR
docker service update --endpoint-mode dnsrr web

# 5. Повторная проверка
docker exec <task> nslookup web
# → Name:   web
# → Address: 10.0.0.3
# → Address: 10.0.0.4
# → Address: 10.0.0.5
```

**Когда что использовать:**
- **VIP (по умолчанию):** Стандартные HTTP-сервисы, когда нужна прозрачная балансировка.
- **DNSRR:** Приложения с собственным кэшированием DNS (Nginx, HAProxy) или когда нужен прямой доступ к конкретной реплике.

**Валидация:** После переключения на `dnsrr` в ответе DNS должно быть несколько IP-адресов. Проверьте, что приложение видит все реплики.

### Сценарий 7: Валидация Corefile и отладка плагинов CoreDNS

Некорректный Corefile приводит к `CrashLoopBackOff` или `SERVFAIL` для всех кластерных сервисов.

```bash
# 1. Получение текущего Corefile
kubectl -n kube-system get configmap coredns -o yaml | yq '.data.Corefile'

# 2. Валидация синтаксиса (требуется установленный coredns)
curl -s https://raw.githubusercontent.com/coredns/deployment/master/kubernetes/coredns.yaml.sed | \
  sed 's/REPLACE_DNS_SERVER_IP/10.96.0.10/g' | \
  kubectl apply -f -

# Или локальная проверка:
coredns -conf /tmp/Corefile -validate
# → Corefile-2019/04/11: successful validation

# 3. Применение изменений
kubectl edit configmap -n kube-system coredns
# CoreDNS автоматически перезагружает конфигурацию (плагин reload)

# 4. Проверка логов после изменения
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50
# → Ищем [INFO] plugin/reload: Reloading Corefile
# → Ищем [ERROR] plugin/...
```

**Типичные ошибки в Corefile:**
- Отсутствие закрывающей фигурной скобки `}`
- Дублирование имени зоны в нескольких блоках
- Неверный синтаксис `forward` (пропущен IP-адрес)
- `ttl` указан как отрицательное число

**Валидация:** После применения `kubectl run dns-debug --rm -it --image=registry.k8s.io/dnsutils:1.3 -- nslookup kubernetes.default` должен возвращать `10.96.0.1`.

### Сценарий 8: Валидация NodeLocal DNSCache

NodeLocal DNSCache (NLDC) снижает задержки и решает UDP conntrack race, но его сбои часто остаются незамеченными.

```bash
# 1. Проверка статуса DaemonSet
kubectl get daemonset -n kube-system node-local-dns
# → NAME              DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE
# → node-local-dns    3         3         3       3            3

# 2. Проверка подов на всех узлах
kubectl get pods -n kube-system -l k8s-app=node-local-dns -o wide
# → Все поды должны быть в статусе Running

# 3. Проверка конфигурации ConfigMap
kubectl -n kube-system get configmap node-local-dns -o yaml | \
  yq '.data.StubDomains|fromjson'
# → Должен содержать корректный ClusterIP CoreDNS (например, 10.96.0.10)

# 4. Проверка связности из пода к NLDC
kubectl exec -it <pod> -- nc -zv 169.254.25.10 53
# → Connection to 169.254.25.10 53 port [udp/*] succeeded!

# 5. Замер latency до NLDC и CoreDNS
kubectl exec -it <pod> -- time nslookup kubernetes.default.svc.cluster.local
# → real 0m0.015s (NLDC)
# → real 0m0.050s (прямой CoreDNS, для сравнения)
```

**Типичные ошибки:**
| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `bind: address already in use` | Порт 53/UDP занят другим процессом на узле | Остановить конфликтующий процесс (например, dnsmasq) |
| `connection refused` к CoreDNS | CoreDNS не готов или эндпоинты пусты | Проверить `kubectl get endpoints kube-dns` |
| `no such host` при сборке образов | NLDC не доступен в момент запуска kubelet | Проверить порядок запуска системных подов |

**Валидация:** После установки NLDC `kubectl top pod` должен показывать снижение CPU на подах CoreDNS. Замеры `time nslookup` должны показывать p50 < 5ms.

### Сценарий 9: Внутренний домен не разрешается (DNS Loop → 8.8.8.8)

**Проблема:** Контейнер с приложением не может подключиться к `db.internal.company.com`. С хоста `nslookup` работает корректно.

```bash
# 1. Проверка resolv.conf внутри контейнера
docker exec app cat /etc/resolv.conf
# → nameserver 8.8.8.8        ← Docker подставил публичный DNS!

# 2. Проверка с хоста
nslookup db.internal.company.com
# → 10.0.1.50  (корректно, через корпоративный DNS 10.0.0.2)

# 3. Проверка внутри контейнера
docker exec app nslookup db.internal.company.com
# → ** server can't find db.internal.company.com: NXDOMAIN

# 4. Проверка Docker-сети
docker network inspect mynet | grep DNS
# → "DNS": ["8.8.8.8"]   ← Публичный DNS!
```

**Причина:** На хосте `/etc/resolv.conf` содержал `127.0.0.53` (systemd-resolved). Docker обнаружил loopback, подставил `8.8.8.8`. Публичный DNS не знает внутренний домен компании.

**Решение:**

```bash
# Настроить Docker на использование корпоративного DNS
# В /etc/docker/daemon.json:
{
  "dns": ["10.0.0.2", "10.0.0.3"],
  "dns-search": ["company.local", "dev.internal"]
}

# Применить:
sudo systemctl restart docker

# Или для конкретного контейнера:
docker run --dns 10.0.0.2 --dns 10.0.0.3 myapp
```

**Валидация:**

```bash
docker exec app cat /etc/resolv.conf
# → nameserver 10.0.0.2
# → nameserver 10.0.0.3

docker exec app nslookup db.internal.company.com
# → 10.0.1.50   ← Теперь работает!
```

### Сценарий 10: Медленный DNS в Kubernetes (conntrack race + ndots)

**Проблема:** Задержки ровно 1000 мс или 5000 мс при резолвинге сервисов из пода. `kubectl exec <pod> -- time nslookup my-service` показывает `real 0m1.015s`.

```bash
# 1. Проверка ndots
kubectl exec <pod> -- cat /etc/resolv.conf | grep ndots
# → options ndots:5

# 2. Проверка conntrack
sudo conntrack -L | grep :53 | wc -l
# → 15000+  ← Переполнение или гонка

# 3. Проверка UDP-соединений
kubectl exec <pod> -- ss -unp | grep :53
# → Много UNCONN записей с одного порта
```

**Причина:** При параллельных A/AAAA запросах (musl или Happy Eyeballs) ядро создает несколько UDP-соединений с одного сокета. В `conntrack` происходит гонка (race condition), и второй запрос ждет таймаута перетрансмиссии (1с или 5с).

**Решение:**

```yaml
# Вариант 1: Уменьшение ndots + single-request-reopen (опция действует только в glibc-образах; в Alpine/musl игнорируется)
spec:
  dnsConfig:
    options:
    - name: ndots
      value: "2"
    - name: single-request-reopen
      value: ""
    - name: timeout
      value: "2"

# Вариант 2: NodeLocal DNSCache (рекомендуется для production)
# Подробнее: [DNS в Kubernetes: Глубокое погружение](../../../../Kubernetes/Networking/dns_deep_dive.md)
```

**Валидация:**

```bash
for i in $(seq 1 20); do
  kubectl exec <pod> -- time nslookup my-service.namespace.svc.cluster.local 2>&1 | grep real
done
# → real 0m0.010s ... (стабильно, без 1-секундных скачков)
```

### Сценарий 11: Контейнер не может pulled образ (DNS при сборке)

**Проблема:** `kubectl apply -f deployment.yaml` приводит к `ImagePullBackOff` или `ErrImagePull`. Логи kubelet: `Failed to pull image "registry.example.com:5000/my-app:latest": rpc error: code = Unknown desc = failed to resolve reference registry.example.com:5000/my-app:latest`.

```bash
# 1. Проверка DNS на узле
cat /etc/resolv.conf
# → nameserver 10.96.0.10 (CoreDNS)

# 2. Проверка резолвинга имени реестра с узла
nslookup registry.example.com
# → NXDOMAIN или таймаут

# 3. Проверка из debug-пода
kubectl run debug --image=busybox:1.37 --rm -it -- nslookup registry.example.com
# → ** server can't find registry.example.com: NXDOMAIN

# 4. Проверка CoreDNS логов
kubectl -n kube-system logs -l k8s-app=kube-dns | grep registry.example.com
# → [ERROR] plugin/errors: 5 registry.example.com. A: NXDOMAIN
```

**Причина:** CoreDNS не знает о внутреннем реестре. Запись не добавлена в `stubDomains` или `forward`, либо DNS-сервер узла не резолвит домен.

**Решение:**

```bash
# Вариант 1: Добавить stub domain в ConfigMap CoreDNS
kubectl -n kube-system edit configmap coredns
# В секции .:53 добавить:
#     stubDomains {
#         "example.com" = ["10.0.0.53"]
#     }

# Вариант 2: Использовать IP-адрес реестра вместо имени (временно)
# image: 10.0.0.53:5000/my-app:latest

# Вариант 3: Добавить запись в /etc/hosts на всех узлах (не рекомендуется для production)
```

**Валидация:**

```bash
kubectl run debug --image=busybox:1.37 --rm -it -- nslookup registry.example.com
# → Address: 10.0.0.53

# После этого deployment должен перейти в Running
kubectl rollout status deployment/my-app
```

## Сводная таблица типичных ошибок

| Ошибка | Вероятная причина | Метод проверки | Решение |
| :--- | :--- | :--- | :--- |
| **NXDOMAIN** | Ошибка в имени или неверный `ndots`. | Проверить имя с точкой в конце (`host.com.`). | Использовать FQDN или уменьшить `ndots`. |
| **SERVFAIL** | Upstream DNS недоступен или заблокирован. | `dig @<upstream_ip> google.com` с хоста. | Проверить firewall, добавить корпоративные DNS. |
| **Timeout (5s)** | Параллельные A/AAAA запросы (musl) или MTU. | `options timeout:2 attempts:1` в `resolv.conf` (glibc: дополнительно `single-request-reopen`; musl её игнорирует). | Уменьшить `timeout`, проверить MTU. |
| **127.0.0.11:53: i/o timeout** | Ошибка в Docker Network или Firewall. | Проверить цепочки iptables (DOCKER_OUTPUT). | Перезапустить Docker, проверить nftables. |
| **SERVFAIL на cluster.local** | CoreDNS не знает зону или эндпоинты пусты. | `kubectl get endpoints kube-dns`. | Перезапустить CoreDNS, проверить RBAC. |
| **CrashLoopBackOff CoreDNS** | Нехватка памяти/CPU или петля перенаправления. | `kubectl logs kube-dns-...`, `kubectl top pod`. | Увеличить ресурсы, исправить upstream DNS. |
| **ImagePullBackOff (DNS)** | Контейнерный рантайм не может разрешить имя реестра. | `crictl exec <id> nslookup <registry>`. | Добавить stub domain в CoreDNS. |
| **DNS работает, приложение падает** | Запись в `/etc/hosts` перезаписывает DNS. | `getent hosts <name>` vs `dig <name>`. | Очистить `/etc/hosts`. |
| **Медленный DNS (>200ms)** | ndots:5, отсутствие NodeLocal DNSCache, conntrack race. | `time nslookup`, `conntrack -L`. | Уменьшить `ndots`, установить NLDC. |
| **Docker default bridge — нет DNS** | Контейнеры в сети `bridge` по умолчанию. | `docker network inspect bridge`. | Переместить в user-defined network. |

## Best Practices

### По конфигурации

1. **Избегайте `bridge` по умолчанию в Docker.** Размещайте контейнеры в user-defined сетях для поддержки DNS Service Discovery.

2. **Для Kubernetes production-кластеров всегда используйте NodeLocal DNSCache.** Это решает проблемы с UDP conntrack race и снижает p99-латентность DNS с 50мс до 5мс.

3. **Управляйте ndots через `dnsConfig` пода, а не через глобальные изменения CoreDNS.** Это даёт гибкость на уровне приложения.

4. **Для Alpine-образов помните:** musl отправляет A и AAAA параллельно, но опция `single-request-reopen` в ней не поддерживается (игнорируется). При проблемах с firewall/NAT используйте NodeLocal DNSCache или исправьте сеть.

5. **Не редактируйте `/etc/resolv.conf` напрямую в контейнерах.** Используйте флаги `docker run --dns`, `dnsConfig` в pod spec или `daemon.json`.

6. **Для Go-приложений проверяйте разрешение через саму программу.** Go (начиная с 1.5) использует собственный резолвер, который может не читать `/etc/hosts`.

### По мониторингу

1. **DNS Success Rate:** Алерт при < 99.9% успешных запросов за 5 минут.

2. **DNS Latency:** Алерт при p99 > 200мс (или > 5мс при наличии NodeLocal DNSCache).

3. **HTTP 5xx по инстансам:** Разбивка по серверам выявит локальные DNS-проблемы, не видимые глобально.

4. **CoreDNS Pod restarts:** Алерт при любом рестарте CoreDNS — это может указывать на OOM или петлю перенаправления.

5. **Изменение `/etc/hosts` в контейнерах:** Мониторинг через auditd или Tripwire на узлах.

### По безопасности

1. **Включите DNS Rebinding Protection** в Docker (включён по умолчанию в 127.0.0.11). Не отключайте без необходимости.

2. **Ограничьте Egress DNS для подов через NetworkPolicy.** Разрешайте трафик только на `kube-system:53`.

3. **Используйте DNSSEC** для защиты от spoofing, но проверяйте совместимость с вашим upstream.

4. **Изолируйте DNS-трафик** во внутренней VLAN. Публичные резолверы (8.8.8.8) должны быть последним fallback, а не основными.

5. **Ведение логов CoreDNS:** Включите плагин `log` в Corefile для аудита всех запросов.

## Дополнительная информация

- **[Решение проблем с DNS в Docker](../../../../Docker/Docker_network/troubleshooting/dns_resolution_issues.md)** — детальный разбор и SSoT для среды Docker.
- **[DNS в Kubernetes: Глубокое погружение](../../../../Kubernetes/Networking/dns_deep_dive.md)** — архитектура CoreDNS, NodeLocalDNS и политики `dnsPolicy`.
- **[Базовая диагностика DNS](./basic_diagnostics.md)** — общие методы проверки связности и утилиты.
- **[Производительность DNS-резолвинга](./dns_resolution_performance.md)** — оптимизация параметров и решение проблем с `conntrack`.
- **[Инструмент dig](./dig_tool.md)** — анализ флагов и структуры ответов.
