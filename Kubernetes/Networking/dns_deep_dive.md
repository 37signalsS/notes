# Глубокое погружение в DNS в Kubernetes

## Определения

**DNS в Kubernetes** играет ключевую роль в механизме обнаружения сервисов (Service Discovery), позволяя обращаться к подам и сервисам по их DNS-именам. Это обеспечивает стабильность и гибкость, поскольку IP-адреса подов могут меняться.

**CoreDNS** является DNS-сервером по умолчанию в большинстве современных кластеров Kubernetes, запускающимся как `Deployment` и `Service` в пространстве имен `kube-system`.

**NodeLocalDNS** — это опциональный кеширующий DNS-сервер, запускающийся как `DaemonSet` на всех узлах кластера. Он кеширует DNS-запросы локально, снижая нагрузку на CoreDNS и уменьшая задержку.

## Основные концепции

### Схема работы DNS в кластере

1.  **Клиентский под:** Приложение в клиентском поде инициирует DNS-запрос.
2.  **NodeLocalDNS (опционально):** Запрос может сначала попасть в локальный кеширующий DNS-сервер, такой как **NodeLocalDNS**.
    *   NodeLocalDNS запускается как `DaemonSet` на всех узлах кластера и слушает запросы на специальном IP-адресе (например, `169.254.25.10`).
    *   Если запись найдена в кеше NodeLocalDNS, ответ возвращается немедленно.
    *   Если записи нет, NodeLocalDNS перенаправляет запрос к основному DNS-серверу кластера (CoreDNS).
3.  **CoreDNS:** Основной DNS-сервер кластера.
    *   CoreDNS получает запрос (напрямую или через NodeLocalDNS).
    *   Он разрешает DNS-имя, используя информацию из API-сервера Kubernetes (например, для сервисов).
    *   Ответ отправляется обратно NodeLocalDNS (если используется) или напрямую клиентскому поду.
    *   NodeLocalDNS кеширует полученный ответ для будущих запросов.

### Компоненты DNS в кластере

DNS-компоненты в кластере Kubernetes обычно включают:

*   **Поды `coredns`**: Запускаются как `Deployment` для обеспечения отказоустойчивости.
*   **Поды `nodelocaldns`**: Запускаются как `DaemonSet`, чтобы присутствовать на каждом узле кластера.
*   **Сервис `coredns`**: Использует `ClusterIP` и предоставляет порты 53/UDP, 53/TCP (для DNS-запросов) и 9153/TCP (для метрик).
*   `Deployment` и `ReplicaSet` для `coredns` и `dns-autoscaler`.

Пример вывода `kubectl get all -n kube-system | grep dns`:

```bash
[root@master-1.example.com /]# kubectl get all -n kube-system | grep dns
pod/coredns-56bc6b976d-drgzm                  1/1     Running   0          95d
pod/coredns-56bc6b976d-r7ldl                  1/1     Running   0          95d
pod/dns-autoscaler-56c969bdb8-j4bwk           1/1     Running   1          95d
pod/nodelocaldns-4298p                        1/1     Running   0          95d
pod/nodelocaldns-8bqzg                        1/1     Running   0          95d
pod/nodelocaldns-csprl                        1/1     Running   0          95d
pod/nodelocaldns-gq2el                        1/1     Running   0          95d
pod/nodelocaldns-gk6l7                        1/1     Running   0          95d
pod/nodelocaldns-j4jbd                        1/1     Running   0          95d
pod/nodelocaldns-rfgth                        1/1     Running   0          95d
pod/nodelocaldns-wdxz5                        1/1     Running   0          95d
pod/nodelocaldns-xc79w                        1/1     Running   0          95d

service/coredns              ClusterIP   10.9.3.0     <none>        53/UDP,53/TCP,9153/TCP   95d

daemonset.apps/nodelocaldns   9         9         9         9            9           <none>      95d

deployment.apps/coredns       2/2     2            2           95d
deployment.apps/dns-autoscaler 1/1     1            1           95d

replicaset.apps/coredns-56bc6b976d         2         2         2       95d
replicaset.apps/dns-autoscaler-56c969bdb8  1         1         1       95d
```

Здесь мы видим:

*   Поды `coredns` (обычно несколько для отказоустойчивости).
*   Поды `nodelocaldns` (запущенные как `DaemonSet`, чтобы быть на каждом узле).
*   Сервис `coredns` с портами 53 UDP, 53 TCP и 9153 (для метрик).
*   `Deployment` и `ReplicaSet` для `coredns` и `dns-autoscaler`.

### Конфигурация DNS в подах (`/etc/resolv.conf`)

Внутри каждого пода файл `/etc/resolv.conf` настраивается `kubelet` для использования внутрикластерного DNS.

Пример `cat /etc/resolv.conf` внутри пода:

```conf
[root@centos-test /]# cat /etc/resolv.conf
nameserver 169.254.25.10
search default.svc.example.com svc.example.com example.com
options ndots:5
```

Основные параметры:

*   `nameserver 169.254.25.10`: Указывает на IP-адрес NodeLocalDNS (или CoreDNS, если NodeLocalDNS не используется). Все DNS-запросы из пода сначала идут сюда.
*   `search default.svc.example.com svc.example.com example.com`: Список доменов поиска. Если запрос не является полным доменным именем, к нему последовательно добавляются эти домены. Это позволяет обращаться к сервисам внутри кластера по их коротким именам.
*   `options ndots:5`: Определяет, сколько точек должно быть в имени, чтобы оно считалось полным доменным именем. Если точек меньше `ndots`, имя считается внутренним и к нему применяются домены поиска.

## Практические сценарии

### Проблема с `search` доменами и `ndots`

Настройки `search` доменов и `ndots` могут приводить к неэффективности, особенно для внешних DNS-запросов. Каждый внешний запрос будет сначала прогоняться через все внутренние домены поиска, прежде чем будет разрешен вовне. Это увеличивает задержку и генерирует избыточный трафик.

Пример `nslookup yandex.ru` с `tcpdump`:

```bash
[root@centos-test /]# nslookup yandex.ru
Server:    169.254.25.10
Address:   169.254.25.10#53

Non-authoritative answer:
Name:      yandex.ru
Address:   77.88.55.66
Name:      yandex.ru
Address:   77.88.55.77
...

[root@centos-test /]# tcpdump -n -p -i eth0 port 53
...
12:37:41.915647 IP 10.109.1.22.56099 > 169.254.25.10.domain: 8959+ A? yandex.ru.default.svc.example.com. (53)
12:37:41.917544 IP 10.109.1.22.54469 > 169.254.25.10.domain: 62110+ A? yandex.ru.svc.example.com. (45)
12:37:41.918421 IP 10.109.1.22.54469 > 169.254.25.10.domain: 62110+ A? yandex.ru.example.com. (45)
12:37:41.919596 IP 10.109.1.22.59504 > 169.254.25.10.domain: 17670+ A? yandex.ru. (27)
...
```

Как видно из `tcpdump`, даже для `yandex.ru` сначала выполняются запросы с добавлением внутренних доменов, и только потом происходит внешний запрос.

### Оптимизация DNS-запросов

Для оптимизации и предотвращения избыточного трафика можно настроить `ConfigMap` CoreDNS. Необходимо включить `autopath` и изменить параметр `pods` на `verified`.

Пример изменения в `ConfigMap` CoreDNS:

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
            pods verified # Изменить на 'verified'
            fallthrough in-addr.arpa ip6.arpa
            autopath # Раскомментировать для включения autopath
        }
        prometheus :9153
        forward . /etc/resolv.conf
        cache 30
        loop
        reload
        loadbalance
    }
```

Это изменение позволяет CoreDNS более интеллектуально обрабатывать запросы, избегая ненужного перебора внутренних доменов для внешних имен.

## Дополнительная информация

### Взаимодействие с CoreDNS через Service и IPtables

Запросы к CoreDNS обычно идут через `Service`, который использует `ClusterIP`. Если `Service` реализован через `IPtables`, это может привести к проблемам с производительностью и потерям пакетов, особенно для DNS-запросов, которые часто используют UDP.

Разработчики Kubernetes предложили решения для минимизации этих проблем:

*   **NodeLocalDNS:** Уменьшает количество трафика, проходящего через `Service`, кешируя DNS-запросы локально на каждом узле.
*   **TCP для CoreDNS:** NodeLocalDNS может преобразовывать UDP-запросы в TCP при общении с CoreDNS, что повышает надежность передачи данных.

### Настройки Kubelet для DNS

Настройки DNS в подах (`/etc/resolv.conf`) берутся из конфигурации `kubelet`. Флаги `cluster-dns` и `cluster-domain` при запуске `kubelet` определяют IP-адрес DNS-сервера кластера и доменное имя кластера соответственно.

Пример из `/etc/kubernetes/kubelet.env`:

```bash
[root@master-1.example.com /]# cat /etc/kubernetes/kubelet.env | grep dns
--cluster-dns=169.254.25.10 --cluster-domain=example.com
```

Здесь `cluster-dns=169.254.25.10` указывает на NodeLocalDNS, а `cluster-domain=example.com` определяет домен кластера.