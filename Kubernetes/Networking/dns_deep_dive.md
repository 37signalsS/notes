# DNS в Kubernetes

## Определения

**DNS в Kubernetes** — встроенный механизм обнаружения сервисов (Service Discovery), позволяющий обращаться к подам и сервисам по стабильным DNS-именам вместо изменяющихся IP-адресов.

**CoreDNS** — DNS-сервер по умолчанию в Kubernetes, запускается как `Deployment` и `Service` в пространстве имён `kube-system`. Автоматически создаёт DNS-записи для всех сервисов кластера.

**NodeLocalDNS** — опциональный кеширующий DNS-сервер, запускается как `DaemonSet` на всех узлах. Кэширует запросы локально, снижая нагрузку на CoreDNS и уменьшая задержку.

**Headless Service** — сервис без ClusterIP (`clusterIP: None`), используемый для прямого DNS-discovery подов StatefulSet. Каждый под получает отдельную DNS-запись.

## Основные концепции

### Роль CoreDNS

**CoreDNS** — стандартный DNS-сервер Kubernetes, работает внутри кластера как набор подов. Обрабатывает DNS-запросы от всех подов кластера.

CoreDNS следит за API-сервером Kubernetes и автоматически создаёт DNS-записи для сервисов:

- При создании `Service` → CoreDNS создаёт A-запись (или SRV, если необходимо)
- При запросе имени сервиса → возвращает его ClusterIP
- Для StatefulSet → создаёт записи для каждого пода (через Headless Service)

> **Важно:** Настройки DNS на уровне Docker (`--dns`, `/etc/docker/daemon.json`) **игнорируются** для подов Kubernetes. `Kubelet` самостоятельно генерирует `/etc/resolv.conf` с указанием на CoreDNS.

### Проблема масштабирования CoreDNS

В крупных кластерах CoreDNS испытывает высокую нагрузку от DNS-запросов. Для решения используется **NodeLocalDNS** — кеширующий агент на каждом узле.

### NodeLocalDNS

**Принцип работы:**

1. **Запуск в режиме hostNetwork:** `DaemonSet` на всех узлах кластера
2. **Перехват трафика через iptables:** Запросы к `kube-dns` перехватываются локальным агентом
3. **Локальное кеширование:** Агент слушает адрес `169.254.20.10` или `169.254.25.10`

**Преимущества:**
- Снижение нагрузки на CoreDNS
- Уменьшение задержки разрешения имён
- Повышение надёжности (UDP → TCP конвертация)

**Схема работы:**

```
Под → NodeLocalDNS (кеш) → CoreDNS → API-сервер K8s
            ↓
        Возврат кэша
```

### Компоненты DNS в кластере

| Компонент | Тип | Назначение |
| :--- | :--- | :--- |
| `coredns` | `Deployment` | DNS-сервер кластера |
| `nodelocaldns` | `DaemonSet` | Кеширование на узлах |
| `dns-autoscaler` | `Deployment` | Автоскейлинг CoreDNS |
| `coredns` Service | `ClusterIP` | Доступ к DNS (порты 53/UDP, 53/TCP, 9153/TCP) |

Пример проверки компонентов:

```bash
kubectl get all -n kube-system | grep dns
```

### Формирование DNS-имени ресурса

Домен кластера по умолчанию: `cluster.local` (настраивается флагом `--cluster-domain` у `kubelet`).

**Формат DNS-имён:**

| Тип | Формат | Пример | Использование |
| :--- | :--- | :--- | :--- |
| FQDN | `<service>.<namespace>.svc.cluster.local` | `redis-cash.stage.svc.cluster.local` | Из другого namespace |
| Короткое | `<service>` | `redis-cash` | Из того же namespace |
| С namespace | `<service>.<namespace>` | `redis-cash.stage` | Из другого namespace (сокращённо) |

### Конфигурация `/etc/resolv.conf` в подах

`Kubelet` автоматически настраивает файл для использования внутрикластерного DNS:

```conf
nameserver 169.254.25.10
search default.svc.example.com svc.example.com example.com
options ndots:5
```

**Параметры:**

- `nameserver` — IP NodeLocalDNS или CoreDNS
- `search` — домены поиска (автоматически дополняют короткие имена)
- `ndots:5` — количество точек, после которого имя считается полным FQDN

## Практические сценарии

### Проблема с `search` доменами и `ndots`

При `ndots:5` внешние запросы (например, `yandex.ru`) сначала прогоняются через все домены поиска, что создаёт задержки и избыточный трафик.

**Пример с `tcpdump`:**

```bash
tcpdump -n -p -i eth0 port 53
```

Запрос к `yandex.ru` генерирует 4 DNS-запроса:
1. `yandex.ru.default.svc.example.com`
2. `yandex.ru.svc.example.com`
3. `yandex.ru.example.com`
4. `yandex.ru`

> **См. также:** [Диагностика DNS-блокировок](../../../Linux/Diagnostics/Networking/dns/overview.md) — общие принципы диагностики задержек.

### Оптимизация через ConfigMap CoreDNS

Включение `autopath` и режима `pods verified` устраняет перебор доменов для внешних имён:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: coredns
  namespace: kube-system
data:
  Corefile: |
    .:53 {
        health
        ready
        kubernetes cluster.local in-addr.arpa ip6.arpa {
            pods verified
            fallthrough in-addr.arpa ip6.arpa
            autopath
        }
        prometheus :9153
        forward . /etc/resolv.conf
        cache 30
        loop
        reload
        loadbalance
    }
```

## Дополнительная информация

### Диагностика DNS-проблем

**Типичные симптомы:**

| Симптом | Возможная причина |
| :--- | :--- |
| `Resolving Timeout` | Недоступен CoreDNS |
| `ErrImagePull` | Не разрешается имя registry |
| `nslookup` работает, приложение нет | Проблема на уровне приложения |

**Инструменты:**

```bash
# Статус подов DNS
kubectl get pods -n kube-system | grep dns

# Логи CoreDNS
kubectl logs -n kube-system -l k8s-app=kube-dns

# Проверка разрешения имени
nslookup <service>.<namespace>.svc.cluster.local

# Анализ трафика
tcpdump -n -p -i eth0 port 53
```

> **См. также:** [Диагностика DNS в Linux](../../../Linux/Diagnostics/Networking/dns/overview.md)

### Взаимодействие с CoreDNS через IPtables

Запросы к CoreDNS идут через `Service` с `ClusterIP`. При реализации через `IPtables` возможны потери UDP-пакетов.

**Решения:**
- **NodeLocalDNS** — кеширование локально, уменьшение трафика через Service
- **TCP для CoreDNS** — NodeLocalDNS конвертирует UDP → TCP

### Настройки Kubelet

Параметры DNS задаются флагами `kubelet`:

```bash
--cluster-dns=169.254.25.10 --cluster-domain=example.com
```

- `cluster-dns` — IP DNS-сервера (NodeLocalDNS или CoreDNS)
- `cluster-domain` — домен кластера
