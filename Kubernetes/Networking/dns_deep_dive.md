# DNS в Kubernetes

## Определения

**DNS (Domain Name System)** в Kubernetes — распределённая система обнаружения сервисов (Service Discovery), которая позволяет компонентам кластера взаимодействовать друг с другом по стабильным именам вместо динамических IP-адресов.

**CoreDNS** — современный модульный DNS-сервер, являющийся стандартом де-факто в Kubernetes (начиная с версии 1.13). Он работает как `Deployment` и предоставляет `Service` с фиксированным IP (обычно десятый адрес в подсети сервисов, например `10.96.0.10`).

**NodeLocalDNS** — оптимизационный слой в виде `DaemonSet`, который запускает легковесный кэширующий агент на каждом узле. Это снижает нагрузку на центральный CoreDNS и минимизирует задержки при разрешении имён.

**Headless Service** — сервис с параметром `clusterIP: None`. В отличие от обычного сервиса, он не имеет виртуального IP; DNS-запрос к такому сервису возвращает список IP-адресов всех готовых (`Ready`) подов, связанных с этим сервисом.

**FQDN (Fully Qualified Domain Name)** — полное доменное имя, однозначно определяющее ресурс в иерархии DNS. В Kubernetes стандартный формат для сервиса: `<service-name>.<namespace>.svc.<cluster-domain>`.

## Основные концепции

### Роль и архитектура CoreDNS

CoreDNS работает как набор подов в пространстве имён `kube-system`. Он интегрируется с Kubernetes API через плагин `kubernetes`, отслеживая создание и удаление сервисов и эндпоинтов.

Основные функции:
- Генерация A/AAAA записей для сервисов (ClusterIP).
- Генерация SRV записей для именованных портов.
- Генерация записей для подов (особенно в StatefulSet).
- Пересылка (forwarding) запросов к внешним DNS-серверам для доменов, не относящихся к кластеру.

### Формирование DNS-имен

Стандартный домен кластера: `cluster.local`.

#### Для сервисов (Services)
- **A-запись (IPv4):** `<service>.<namespace>.svc.cluster.local` → возвращает ClusterIP.
- **AAAA-запись (IPv6):** аналогично для IPv6 адресов в dual-stack кластерах.
- **SRV-запись:** `_<port-name>._<port-protocol>.<service>.<namespace>.svc.cluster.local` → используется для обнаружения портов.

#### Для подов (Pods)
По умолчанию поды получают DNS-имя в формате:
`<pod-ip-address>.<namespace>.pod.cluster.local`.
IP-адрес записывается через дефисы: `172-17-0-3.default.pod.cluster.local`.

Для подов в **StatefulSet** с использованием **Headless Service** имена более предсказуемы:
`<hostname>.<service>.<namespace>.svc.cluster.local`.
Пример: `web-0.nginx.default.svc.cluster.local`.

### Конфигурация /etc/resolv.conf и параметр ndots

`Kubelet` при запуске пода генерирует файл `/etc/resolv.conf`. Пример типичного содержимого:

```conf
nameserver 10.96.0.10
search default.svc.cluster.local svc.cluster.local cluster.local
options ndots:5
```

**ndots:5** — критически важный параметр. Он означает, что если в запрашиваемом имени меньше 5 точек, DNS-резолвер будет сначала пытаться дополнить его доменами из списка `search`, прежде чем пробовать разрешить как абсолютное имя. Это ускоряет доступ к локальным сервисам по коротким именам, но замедляет внешние запросы.

### Политики DNS для подов (dnsPolicy)

Поле `dnsPolicy` в манифесте пода определяет, как будет настроен `/etc/resolv.conf`:

1. **ClusterFirst** (по умолчанию): Использовать внутрикластерный DNS. Если имя не найдено внутри, запрос пересылается выше (upstream).
2. **ClusterFirstWithHostNet**: Обязателен для подов с `hostNetwork: true`, если им нужен доступ к DNS кластера. Без этой политики поды с `hostNetwork` будут использовать DNS узла.
3. **Default**: Под наследует настройки DNS от узла (традиционно `/etc/resolv.conf` хоста). Название "Default" вводит в заблуждение, так как это НЕ политика по умолчанию для Kubernetes.
4. **None**: Игнорировать все автоматические настройки. Требует обязательного заполнения раздела `dnsConfig`.

### Кастомная настройка DNS (dnsConfig)

Позволяет переопределять параметры DNS на уровне конкретного пода:

```yaml
spec:
  dnsPolicy: "None"
  dnsConfig:
    nameservers:
      - 1.2.3.4
    searches:
      - custom.dns.local
    options:
      - name: ndots
        value: "2"
      - name: edns0
```

## Масштабирование и оптимизация

### NodeLocalDNS

Для решения проблем с задержками (latency) и нагрузкой на CoreDNS рекомендуется использовать **NodeLocalDNS**.

**Механизм работы:**
- Запускается как `DaemonSet` с IP-адресом на loopback-интерфейсе узла (обычно `169.254.20.10`).
- Поды обращаются к локальному агенту вместо того, чтобы идти через `iptables` / `ipvs` к центральным подам CoreDNS.
- Агент кэширует запросы и использует TCP для связи с CoreDNS, что стабильнее UDP при высоких нагрузках.

### Автоскейлинг CoreDNS

В динамических кластерах используется **cluster-proportional-autoscaler**. Он масштабирует количество реплик CoreDNS в зависимости от количества узлов или ядер в кластере.

Пример параметров (обычно 1 реплика на каждые 16-32 узла):
```text
coresPerReplica: 256
nodesPerReplica: 16
```

### Компоненты в кластере

| Компонент | Тип ресурса | Зона ответственности |
| :--- | :--- | :--- |
| `coredns` | `Deployment` | Основной сервер, обработка запросов |
| `nodelocaldns` | `DaemonSet` | Локальный кэш на узлах |
| `coredns-autoscaler` | `Deployment` | Контроль количества реплик |
| `kube-dns` | `Service` | Стабильный IP для доступа из подов |

## Практические сценарии

### Оптимизация ndots и внешние запросы

Если приложение часто обращается к внешним ресурсам (например, `api.example.com`), при `ndots:5` оно порождает лишние запросы:
1. `api.example.com.default.svc.cluster.local` → NXDOMAIN
2. `api.example.com.svc.cluster.local` → NXDOMAIN
3. `api.example.com.cluster.local` → NXDOMAIN
4. `api.example.com` → OK

**Решения:**
- Использовать FQDN с точкой на конце: `api.example.com.`
- Снизить `ndots` в `dnsConfig` до 2 (если не используются сложные короткие имена внутри кластера).
- Использовать плагин `autopath` в CoreDNS.

### Использование плагинов CoreDNS (Corefile)

Конфигурация CoreDNS хранится в `ConfigMap` с именем `coredns`.

```yaml
data:
  Corefile: |
    .:53 {
        errors
        health {
           lameduck 5s
        }
        ready
        kubernetes cluster.local in-addr.arpa ip6.arpa {
           pods verified
           fallthrough in-addr.arpa ip6.arpa
           ttl 30
        }
        prometheus :9153
        forward . /etc/resolv.conf
        cache 30
        loop
        reload
        loadbalance
    }
```

**Полезные плагины:**
- **rewrite:** Позволяет менять имена "на лету" (например, для миграции сервисов).
- **hosts:** Позволяет задавать статические DNS-записи прямо в конфиге.
- **template:** Позволяет динамически формировать ответы на основе шаблонов.

## Диагностика и устранение неполадок

### Типичные проблемы

- **NXDOMAIN:** Имя не найдено. Проверить `search` домены и правильность FQDN.
- **Timeout:** DNS-сервер не отвечает. Проверить доступность подов CoreDNS и правила `NetworkPolicy`.
- **Latency:** Задержки из-за перебора `search` доменов или перегрузки `conntrack` в Linux (решается через NodeLocalDNS).

### Команды для диагностики

```bash
# Проверка статуса подов DNS
kubectl get pods -n kube-system -l k8s-app=kube-dns

# Проверка логов CoreDNS (ищите ошибки NXDOMAIN или сбои API)
kubectl logs -n kube-system -l k8s-app=kube-dns

# Тестирование изнутри кластера (используя временный под)
kubectl run -it --rm --restart=Never dnsutils --image=gcr.io/kubernetes-e2e-test-images/dnsutils:1.3 -- nslookup google.com

# Проверка эндпоинтов сервиса DNS
kubectl get endpoints -n kube-system kube-dns
```

## Дополнительная информация

### Взаимодействие с CoreDNS через iptables

Трафик к CoreDNS (ClusterIP) балансируется через `iptables` (или `ipvs`). Поскольку DNS обычно использует UDP, это может приводить к проблемам с "race condition" в модуле `conntrack` ядра Linux, что вызывает задержки в 1-5 секунд. NodeLocalDNS полностью устраняет эту проблему за счёт использования локального IP.

### Внешний DNS (ExternalDNS)

**ExternalDNS** — инструмент, который синхронизирует сервисы и ингрессы Kubernetes с внешними DNS-провайдерами (AWS Route53, Google Cloud DNS, Cloudflare и др.). Это позволяет автоматически создавать публичные DNS-записи при деплое приложения.

### Работа в Dual-stack кластерах

В кластерах с поддержкой IPv4/IPv6 CoreDNS возвращает:
- **A-записи** для IPv4.
- **AAAA-записи** для IPv6.
Приоритет выбора (IPv4 или IPv6) зависит от настроек операционной системы и резолвера внутри пода.

## См. также
- [Headless Service](./Service/service_type_headless.md) — подробнее о работе сервисов без ClusterIP.
- [Диагностика DNS в Linux](../../Linux/Diagnostics/Networking/dns/overview.md) — общие принципы диагностики задержек в системе.
- [Официальная документация Kubernetes DNS](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/)
