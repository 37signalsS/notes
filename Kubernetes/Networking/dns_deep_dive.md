# DNS в Kubernetes: Глубокое погружение

---

## Определения

**DNS (Domain Name System)** в Kubernetes — критическая системная служба обнаружения сервисов (**Service Discovery**), которая позволяет компонентам кластера взаимодействовать друг с другом по стабильным доменным именам вместо динамических IP-адресов.

**CoreDNS** — современный модульный DNS-сервер, являющийся стандартом де-факто в Kubernetes (начиная с v1.13). Он работает как `Deployment` в пространстве имен `kube-system`, интегрируется с Kubernetes API через плагины и предоставляет сервис `kube-dns` с фиксированным IP-адресом.

**NodeLocal DNSCache** — оптимизационный слой в виде `DaemonSet`, запускающий кэширующий агент на каждом узле. Снижает нагрузку на центральный CoreDNS, минимизирует задержки и решает проблемы с `conntrack` в Linux (UDP race conditions).

**EndpointSlice** — масштабируемый ресурс API, который CoreDNS использует для получения актуальных IP-адресов подов. В отличие от старого ресурса `Endpoints`, `EndpointSlices` позволяют эффективно обрабатывать тысячи эндпоинтов, разбивая их на несколько объектов.

**FQDN (Fully Qualified Domain Name)** — полное доменное имя. В Kubernetes стандартный формат: `<service-name>.<namespace>.svc.<cluster-domain>`.

---

## Основные концепции

### Архитектура CoreDNS

CoreDNS работает как набор подов, которые непрерывно отслеживают изменения в API-сервере Kubernetes (Services, EndpointSlices). Весь функционал CoreDNS реализован через систему плагинов, что делает его крайне гибким.

**Ключевые особенности:**
- **Модульность:** Основная логика (Kubernetes, Cache, Rewrite, Forward) реализована через плагины.
- **Масштабируемость:** Поддержка `EndpointSlices` предотвращает деградацию производительности в больших кластерах (>1000 подов в сервисе).
- **Надежность:** Интегрирован с Control Plane и автоматически восстанавливает записи при сбоях компонентов.

### Типы DNS-записей

| Тип записи | Когда создается | Что содержит |
| :--- | :--- | :--- |
| **A-запись** | Для любого Service с ClusterIP | Сопоставляет имя сервиса с виртуальным IPv4 |
| **AAAA-запись** | В Dual-stack кластерах | Сопоставляет имя сервиса с виртуальным IPv6 |
| **SRV-запись** | Для именованных портов | Содержит номер порта и целевое имя (для протоколов типа gRPC, SIP) |
| **CNAME** | Для сервисов `ExternalName` | Ссылка на внешний домен (например, `db.provider.com`) |
| **PTR** | Обратная зона | Сопоставляет IP-адрес с именем (используется для системной диагностики) |

### Формирование DNS-имен

Стандартный домен кластера: `cluster.local`.

#### Для сервисов (Services)
Имя формируется по шаблону: `<svc>.<ns>.svc.cluster.local`.
- **A-запись:** Возвращает `ClusterIP` сервиса.
- **В Headless Services:** Для сервисов с `clusterIP: None` DNS возвращает список IP-адресов всех готовых (`Ready`) подов.

#### Для подов (Pods)
По умолчанию поды получают имя на основе их IP: `<pod-ip-address>.<ns>.pod.cluster.local`.
Пример: `172-17-0-3.default.pod.cluster.local`.

**Специфические настройки идентификации:**
- **hostname и subdomain:** Если в спецификации пода указаны оба поля, он получает имя `<hostname>.<subdomain>.<ns>.svc.cluster.local`.
- **setHostnameAsFQDN: true:** Устанавливает FQDN пода в качестве системного hostname внутри контейнера (необходимо для legacy-приложений).

#### Идентификация в StatefulSet
В связке с Headless Service каждый под получает предсказуемое и стабильное имя:
`<pod-name>.<svc>.<ns>.svc.cluster.local`. Это критично для кластерных БД (PostgreSQL, MongoDB), где узлы должны знать адреса друг друга.

### Конфигурация /etc/resolv.conf и ndots:5

Kubelet генерирует `/etc/resolv.conf` для каждого пода. Типичное содержимое:
```conf
nameserver 10.96.0.10
search default.svc.cluster.local svc.cluster.local cluster.local
options ndots:5
```

**Проблема ndots:5:**
Параметр указывает резолверу, что если в имени меньше 5 точек, нужно сначала перебрать все домены из списка `search`.
- **Пример:** Запрос `google.com` (1 точка) вызовет попытки разрешить `google.com.default.svc.cluster.local`, затем `google.com.svc.cluster.local`, и только потом само имя `google.com`.
- **Оптимизация:** Использовать абсолютные имена с точкой в конце (`google.com.`) или снизить `ndots` до 2 через `dnsConfig`.

### Политики DNS для подов (dnsPolicy)

Определяет способ формирования `/etc/resolv.conf`:
- **ClusterFirst (по умолчанию):** Сначала ищет внутри кластера. Если не найдено — пересылает внешнему резолверу узла.
- **Default:** Наследует настройки DNS от ОС узла (игнорирует кластерный DNS).
- **ClusterFirstWithHostNet:** Обязателен для подов с `hostNetwork: true`, если им нужен доступ к сервисам кластера.
- **None:** Полностью ручная настройка через `dnsConfig`.

---

## Продвинутая настройка и оптимизация

### Кастомная настройка через dnsConfig

Позволяет переопределять параметры на уровне конкретного пода:
```yaml
spec:
  dnsConfig:
    nameservers: [ "1.2.3.4" ]
    searches: [ "custom.local" ]
    options:
      - name: ndots
        value: "2"
```

### Настройка CoreDNS (Corefile)

Конфигурация хранится в `ConfigMap/coredns`. Пример ключевых блоков:
```text
.:53 {
    errors
    health
    ready
    kubernetes cluster.local in-addr.arpa ip6.arpa {
       pods verified
       fallthrough in-addr.arpa ip6.arpa
       ttl 30
    }
    prometheus :9153
    forward . /etc/resolv.conf
    cache 30
    autopath @kubernetes
}
```

**Важные плагины:**
- **autopath:** Оптимизирует запросы с `ndots`, сокращая количество лишних обращений к DNS при поиске по суффиксам.
- **rewrite:** Позволяет менять имена "на лету" (например, `svc-a.ns1` -> `svc-b.ns2`).
- **k8s_external:** Позволяет CoreDNS отвечать на запросы для внешних доменов, делегированных кластеру.

### NodeLocal DNSCache

Решает проблему race conditions в `conntrack` при использовании UDP и снижает Latency за счет локального кэширования.
- **Механизм:** Запускает локальный агент на IP `169.254.20.10`.
- **Преимущество:** Трафик между подом и локальным кэшем идет по UDP, а от кэша к CoreDNS — по **TCP**, что значительно стабильнее при высоких нагрузках.

### Автомасштабирование CoreDNS

Для поддержания производительности используется `cluster-proportional-autoscaler`.
**Рекомендация:** 1 реплика CoreDNS на каждые 16-32 узла или на каждые 256 ядер CPU в кластере.

---

## Практические сценарии

### Навигация по пространствам имен (Namespace)

| Запрос | Результат | Применение |
| :--- | :--- | :--- |
| `my-svc` | Разрешается в текущем Namespace | Внутренняя связь компонентов одного приложения |
| `my-svc.prod` | Разрешается в Namespace `prod` | Связь между разными приложениями/окружениями |
| `my-svc.prod.svc.cluster.local` | Полное имя (FQDN) | Самый надежный способ, исключающий влияние `ndots` |

### Топологическая осведомленность

1. **Topology Aware Routing:** Если включено (`service.kubernetes.io/topology-mode: Auto`), CoreDNS помечает эндпоинты, направляя трафик на поды в той же зоне (Zone), что и клиент.
2. **Internal Traffic Policy:** При установке `internalTrafficPolicy: Local` сервис будет направлять трафик только на поды, находящиеся на том же узле. Если локальных подов нет, трафик будет отброшен (полезно для минимизации задержек и безопасности).

---

## Диагностика и устранение неполадок

### Алгоритм поиска неисправностей

1. **Проверка из тестового пода:**
   ```bash
   kubectl run dns-debug --image=registry.k8s.io/dnsutils:1.3 --rm -it -- nslookup <svc-name>
   ```
2. **Проверка эндпоинтов DNS:**
   ```bash
   kubectl get endpoints -n kube-system kube-dns
   ```
   Если список пуст — CoreDNS не готов или не может подключиться к API.
3. **Анализ логов CoreDNS:**
   ```bash
   kubectl logs -n kube-system -l k8s-app=kube-dns
   ```
   Ищите ошибки `NXDOMAIN` (неверные записи), `SERVFAIL` (проблемы с upstream) или `Loop` (циклическая пересылка).

### Типичные проблемы

- **DNS Loop (Петля перенаправления):** CoreDNS обнаруживает, что вышестоящий DNS (из `/etc/resolv.conf`) — это он сам (часто через `systemd-resolved` на хосте). Это приводит к `CrashLoopBackOff` или бесконечным рекурсивным запросам. 
  - **Решение:** Указать фиксированный upstream IP (например, `8.8.8.8`) или использовать «чистый» resolv.conf хоста без заглушки: `--resolv-conf /run/systemd/resolve/resolv.conf` в параметрах kubelet.
  - **Подробнее:** См. детальный разбор и методы диагностики в **[Петли перенаправления DNS](../../Networking/Protocols/DNS/dns_forwarding_loops.md)**.
- **Блокировка NetworkPolicy:** Часто "Default Deny" политики забывают разрешить Egress на UDP/TCP порт 53 в неймспейс `kube-system`.
- **UDP Conntrack Race:** Задержки в 1 или 5 секунд при резолвинге. Решение: NodeLocal DNSCache.
- **Размер UDP-пакета:** Если в Headless Service >20 подов, ответ может не влезть в 512 байт UDP. Убедитесь, что клиенты поддерживают переключение на TCP.

> **Совет для интервью:**
> Если под не может разрешить имя сервиса, проверьте цепочку: `Под -> NetworkPolicy (Egress) -> Service kube-dns -> Endpoints CoreDNS -> CoreDNS Logs -> Upstream DNS`. Самая частая причина в защищенных кластерах — отсутствие разрешения на трафик к `kube-system:53`.

---

## Дополнительная информация

### Сравнение с внешним DNS (ExternalDNS)
CoreDNS управляет именами *внутри* кластера. **ExternalDNS** — это отдельный контроллер, который синхронизирует сервисы/ингрессы Kubernetes с внешними провайдерами (Route53, Cloudflare, Google DNS) для создания публичных записей.

### См. также
- [Headless Service — детальный разбор](./Service/service_type_headless.md)
- [Диагностика DNS в Linux](../../Linux/Diagnostics/Networking/dns/overview.md)
- [Service Discovery: Базовые концепции](./Network/dns_service_discovery.md)
- [Официальная документация Kubernetes DNS](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/)
