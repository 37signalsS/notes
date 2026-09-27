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

### Плагины CoreDNS

CoreDNS использует модульную архитектуру, где каждый плагин выполняет определенную функцию. Плагины обрабатывают запросы последовательно, в порядке их объявления в Corefile.

**Основные плагины:**

| Плагин | Назначение | Особенности |
|:---|:---|:---|
| `kubernetes` | Интеграция с Kubernetes API | Создает записи для Service и Pod, поддерживает EndpointSlices |
| `cache` | Кэширование ответов | Снижает нагрузку на API-сервер, поддержка TTL |
| `forward` | Пересылка внешних запросов | Отправляет запросы на upstream DNS-серверы |
| `rewrite` | Модификация имен | Позволяет менять имена "на лету" для миграции или алиасов |
| `autopath` | Оптимизация ndots | Сокращает количество запросов при поиске по суффиксам |
| `prometheus` | Экспорт метрик | Предоставляет метрики на `:9153/metrics` |
| `health` | Health check | Эндпоинт для проверки работоспособности |
| `ready` | Readiness probe | Указывает, что CoreDNS готов принимать трафик |
| `errors` | Логирование ошибок | Агрегация и логирование ошибок DNS |
| `log` | Логирование запросов | Полное логирование всех DNS-запросов |
| `loop` | Обнаружение петель | Предотвращает бесконечные циклы перенаправления |
| `loadbalance` | Балансировка ответов | Перемешивание A/AAAA записей для round-robin |

**Пример конфигурации с расширенными плагинами:**
```text
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
    forward . /etc/resolv.conf {
        max_concurrent 1000
    }
    cache 30
    loop
    reload
    loadbalance
}
```

**Описание ключевых параметров:**
- `pods verified` — CoreDNS проверяет существование пода через API, возвращает NXDOMAIN если под не существует
- `fallthrough` — если запись не найдена, запрос передается следующему плагину
- `ttl 30` — время жизни кэша в секундах для кластерных записей
- `max_concurrent 1000` — ограничение параллельных запросов к upstream
- `lameduck 5s` — время "подыхания" перед остановкой для graceful shutdown

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

### Установка и настройка NodeLocal DNSCache

NodeLocal DNSCache (NLDC) — критически важный компонент для production-кластеров, решающий проблему UDP conntrack race conditions и снижающий задержки DNS-запросов.

**Предварительные требования:**
- Kubernetes v1.18+
- CoreDNS v1.7+ (рекомендуется v1.8+)
- Доступ к реестру образов `registry.k8s.io`

**Установка через DaemonSet:**

1. Скачайте официальный манифест:
```bash
wget https://raw.githubusercontent.com/kubernetes/kubernetes/master/cluster/addons/dns/nodelocaldns/nodelocaldns.yaml
```

2. Отредактируйте переменные в манифесте:
```yaml
# В секции ConfigMap укажите:
# __PILLAR__DNS__SERVER__ — ClusterIP CoreDNS (например, 10.96.0.10)
# __PILLAR__DNS__DOMAIN__ — домен кластера (cluster.local)
# __PILLAR__LOCAL__DNS__ — IP локального кэша (169.254.25.10)
```

3. Примените манифест:
```bash
kubectl apply -f nodelocaldns.yaml
```

4. Проверьте установку:
```bash
kubectl get daemonset -n kube-system node-local-dns
kubectl get pods -n kube-system -l k8s-app=node-local-dns -o wide
```

5. Настройте `/etc/resolv.conf` в подах для использования NLDC:
```yaml
# Kubelet автоматически настроит поды на использование 169.254.25.10
# Для существующих подов необходимо выполнить рестарт
```

**Архитектура NLDC:**
- Каждый узел получает локальный DNS-кэш на IP `169.254.25.10`
- Поды отправляют запросы на локальный IP (UDP)
- NLDC кэширует ответы и отправляет запросы к CoreDNS по TCP (более надежно)
- При отсутствии записи в кэсте, NLDC обращается к CoreDNS

### Кастомизация Corefile

**Добавление stub domains (локальных зон):**
```text
.:53 {
    # ... другие плагины ...
    
    # Stub domain для внутренней БД
    stubDomains {
        "internal.corp.local" = ["10.0.0.53", "10.0.0.54"]
    }
    
    # Upstream DNS для определенного домена
    forward .internal.corp.local 10.0.0.53 10.0.0.54
    
    forward . /etc/resolv.conf
}
```

**Настройка upstream DNS-серверов:**
```text
.:53 {
    # ... другие плагины ...
    
    # Фиксированные upstream-серверы вместо /etc/resolv.conf
    forward . 8.8.8.8 8.8.4.4 {
        force_tcp  # Использовать TCP для upstream
    }
}
```

**Переопределение записей (rewrite):**
```text
.:53 {
    # ... другие плагины ...
    
    # Переопределение имени для миграции
    rewrite name old-service.namespace.svc.cluster.local new-service.namespace.svc.cluster.local
    
    # Переопределение типа записи
    rewrite continue {
        name regex (.*)\.old\.domain\.$ {1}.new.domain.
        answer name (.*)\.new\.domain\.$ {1}.old.domain.
    }
}
```

**Валидация Corefile перед применением:**
```bash
# Проверка синтаксиса
kubectl get configmap -n kube-system coredns -o yaml | yq '.data.Corefile' | coredns -conf stdin -validate
```

**Применение изменений:**
```bash
kubectl edit configmap -n kube-system coredns
# CoreDNS автоматически перезагружает конфигурацию (плагин reload)
# Или выполните рестарт:
kubectl rollout restart deployment -n kube-system coredns
```

### Настройка DNS для внешних ресурсов (ExternalName и ExternalDNS)

**ExternalName Service — создание алиаса для внешнего ресурса:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: external-database
  namespace: production
spec:
  type: ExternalName
  externalName: db.internal.corp.local
```

**Проверка работы ExternalName:**
```bash
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup external-database.production.svc.cluster.local
# → Должен вернуть CNAME на db.internal.corp.local
```

**ExternalDNS — автоматизация создания внешних записей:**

ExternalDNS — отдельный контроллер, который синхронизирует сервисы/ингрессы Kubernetes с внешними DNS-провайдерами. CoreDNS управляет именами внутри кластера, ExternalDNS — снаружи.

#### Статические записи vs ExternalDNS

При выводе сервисов типа `LoadBalancer` наружу IP-адрес известен. Есть два способа сделать его доступным по имени:

1.  **Ручная статическая A-запись:** В корпоративном DNS-сервере создается A-запись, указывающая на External IP сервиса.
    - **Плюсы:** Простота, нет дополнительных зависимостей.
    - **Минусы:** При удалении/пересоздании сервиса IP меняется, и запись становится невалидной. При большом количестве сервисов — рутинная работа, риск забыть удалить или обновить запись.

2.  **ExternalDNS (автоматизация):** Контроллер следит за сервисами/ингрессами Kubernetes и автоматически создает/обновляет/удаляет записи во внешнем DNS-сервере.
    - **Плюсы:** Нет ручной работы, IP всегда актуален.
    - **Минусы:** Требуется развертывание дополнительного контроллера в кластере.

#### Архитектура ExternalDNS

ExternalDNS получает список сервисов/ингрессов из API Kubernetes, фильтрует их по аннотациям и обновляет записи во внешнем DNS-провайдере через соответствующий провайдерский драйвер.

**Пример аннотации на сервисе:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: grafana
  namespace: monitoring
  annotations:
    external-dns.alpha.kubernetes.io/hostname: grafana.k8s.example.com
spec:
  type: LoadBalancer
  selector:
    app: grafana
  ports:
    - port: 3000
      targetPort: 3000
```

#### DNS-стратегия для Kubernetes: почему не CoreDNS

CoreDNS является внутренним DNS-сервером кластера и **не предназначен** для обслуживания внешних пользователей:

- **Назначение:** CoreDNS обеспечивает service discovery *внутри* кластера. Его основная задача — разрешение имен `<svc>.<ns>.svc.cluster.local`.
- **Безопасность:** Делегирование внешней зоны на CoreDNS создает зависимость от работоспособности всего кластера. При проблемах внутри кластера внешнее преобразование имен перестает работать, что может парализовать корпоративную сеть.
- **Управление:** Конфигурация зон в CoreDNS выполняется через ConfigMap и перезапуск деплоя. Для внешнего DNS это неудобно и небезопасно.
- **Разделение ответственности:** Взрослые системы требуют отдельного внешнего DNS для внешних сервисов и отдельного внутреннего DNS для внутренних нужд.

**Рекомендация:** Используйте выделенный корпоративный DNS-сервер (BIND, PowerDNS, Microsoft DNS) для внешних записей. CoreDNS используйте только для внутреннего service discovery кластера.

#### Split-horizon DNS (расщепление зон)

Split-horizon DNS — техника, при которой DNS-сервер возвращает разные ответы в зависимости от источника запроса:

- **Изнутри корпоративной сети:** Возвращаются внутренние IP-адреса (например, `10.0.0.0/8`).
- **Из интернета:** Возвращаются публичные IP-адреса или запрос блокируется.

**Зачем нужно для Kubernetes:**
- Внешние сервисы кластера (`grafana.k8s.example.com`) не должны раскрывать внутренние IP-адреса и структуру сети злоумышленникам.
- Внутренние сервисы кластера не должны быть доступны извне по тем же именам.

BIND поддерживает split-horizon через механизм **views**:
```bash
# В named.conf
view "internal" {
  match-clients { 10.0.0.0/8; 192.168.0.0/16; };
  zone "k8s.example.com" {
    type master;
    file "k8s.internal.db";
  };
};

view "external" {
  match-clients { any; };
  zone "k8s.example.com" {
    type master;
    file "k8s.external.db";
  };
};
```

#### Практика: ExternalDNS с BIND9 через RFC 2136

ExternalDNS поддерживает обновление DNS-записей через протокол **RFC 2136** (Dynamic DNS Updates) без необходимости развертывать полноценный облачный провайдер. Это подходит для корпоративных сред с BIND9.

**Предварительные требования:**
- BIND 9.8+ с поддержкой TSIG (Transaction SIGnature) для аутентификации.
- В зоне, которую будет изменять ExternalDNS, должны быть разрешены динамические обновления (allow-update) для ключевого клиента.

**Шаг 1: Создание TSIG-ключа на стороне BIND9**

```bash
# Генерация ключа
dnssec-keygen -a HMAC-SHA512 -b 512 -n HOST externaldns
```

Это создаст файлы `Kexternaldns.+165+00000.key` и `Kexternaldns.+165+00000.private`. Извлеките секрет:
```bash
# В private-файле находится Base64-секрет
cat Kexternaldns.+165+00000.private | grep -oP '"[^"]*"' | tr -d '"'
# → XXXXXXXXXXXXXX...
```

**Шаг 2: Конфигурация BIND9 (`named.conf.options` или `named.conf.local`)**

```bash
key "externaldns-key" {
  algorithm hmac-sha512;
  secret "XXXXXXXXXXXXXX...";
};

zone "k8s.example.com" {
  type master;
  file "/etc/bind/zones/k8s.example.com.db";
  allow-update { key "externaldns-key"; };
  also-notify { 192.168.1.10; };  # IP вторичного DNS, если есть
};
```

**Важно:** `allow-update` разрешает динамические обновления *только* для указанного ключа. Никакие другие источники не смогут изменять зону.

**Шаг 3: Конфигурация ExternalDNS (Helm values)**

```yaml
# values.yaml для ExternalDNS с BIND9 + RFC2136
provider:
  name: rfc2136
env:
  - name: EXTERNAL_DNS_RFC2136_TSIG_SECRET
    valueFrom:
      secretKeyRef:
        name: external-dns-bind9
        key: tsig-secret
rfc2136:
  host: 192.168.1.5
  port: 53
  zone: k8s.example.com
  tsigSecret: "XXXXXXXXXXXXXX..."
  tsigKeyname: externaldns-key
  tsigSecretAlg: hmac-sha512
```

**Шаг 4: Проверка работы**

```bash
# Создание сервиса с аннотацией
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: grafana
  namespace: monitoring
  annotations:
    external-dns.alpha.kubernetes.io/hostname: grafana.k8s.example.com
spec:
  type: LoadBalancer
  selector:
    app: grafana
  ports:
    - port: 3000
      targetPort: 3000
EOF

# Проверка логов ExternalDNS
kubectl logs -n kube-system -l app=external-dns --tail=50
# → "Adding record grafana.k8s.example.com -> 192.168.10.180"

# Проверка DNS-записи
dig @192.168.1.5 grafana.k8s.example.com A
# → grafana.k8s.example.com. 300 IN A 192.168.10.180
```

#### Best Practices для DNS в Kubernetes

1.  **Выделенный поддомен для Kubernetes:** Используйте отдельную зону (например, `k8s.corp.example.com`) для всех сервисов кластера. Это упрощает управление и позволяет легко отличить записи, созданные ExternalDNS, от статических записей.
2.  **Split-horizon:** Настройте разные ответы для внутренних и внешних клиентов. Внешние клиенты не должны видеть внутренние IP-адреса подов.
3.  **TSIG для безопасности:** Всегда используйте TSIG-ключи для динамических обновлений. Никогда не разрешайте открытые `allow-update { any; };` на корпоративном DNS.
4.  **TTL:** Устанавливайте адекватный TTL (например, 300 секунд) для записей, создаваемых ExternalDNS. Это позволяет быстро переключать трафик при изменении IP.
5.  **Не делегируйте корневые домены на CoreDNS:** CoreDNS предназначен только для внутреннего service discovery. Для внешних имен используйте корпоративный DNS.

### Оптимизация производительности DNS

**Проблема ndots:5 и решение:**
```bash
# Создание пода с оптимизированным ndots
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: optimized-pod
spec:
  containers:
  - name: app
    image: my-app:latest
  dnsConfig:
    options:
    - name: ndots
      value: "2"
    - name: single-request-reopen
      value: ""
    - name: timeout
      value: "2"
    - name: attempts
      value: "3"
EOF
```

**Использование single-request-reopen для conntrack race:**
```yaml
# В dnsConfig пода
dnsConfig:
  options:
  - name: single-request-reopen
    value: ""
```
Эта опция заставляет резолвер отправлять A и AAAA запросы с разных портов, решая проблему UDP race conditions.

**Кэширование на уровне приложения:**
```bash
# Для JVM-приложений настройте TTL кэширования
-Dnetworkaddress.cache.ttl=30
-Dnetworkaddress.cache.negative.ttl=10
```

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
- **OOMKilled CoreDNS:** При большом количестве сервисов или подключений CoreDNS может исчерпать память. Решение: увеличить `resources.limits.memory` в Deployment CoreDNS.

### Диагностика производительности DNS

**Измерение задержки DNS:**
```bash
# Измерение времени резолвинга
kubectl run dns-perf --rm -it --image=busybox:1.37 -- time nslookup kubernetes.default.svc.cluster.local

# Множественные запросы для оценки кэширования
for i in $(seq 1 10); do
  kubectl run dns-test-$i --rm -it --image=busybox:1.37 -- nslookup my-service.namespace.svc.cluster.local
done
```

**Проверка кэширования:**
```bash
# Первый запрос — медленнее (кэш пустой)
# Второй запрос — быстрее (из кэша)
# Сброс кэша в CoreDNS:
kubectl exec -n kube-system <coredns-pod> -- kill -SIGUSR1 1
```

**Анализ DNS-трафика:**
```bash
# tcpdump на узле для анализа DNS-трафика
tcpdump -i any port 53 -n

# Фильтрация по конкретному IP CoreDNS
tcpdump -i any host 10.96.0.10 and port 53 -n
```

---

## Мониторинг и метрики

### Метрики CoreDNS

CoreDNS экспортирует метрики через плагин `prometheus` на порту `:9153/metrics`. Основные метрики:

| Метрика | Описание | Алерт |
|:---|:---|:---|
| `coredns_dns_requests_total` | Общее количество запросов по типу и rcode | Резкий рост при атаках |
| `coredns_dns_response_rcode_count_total` | Распределение ответов по кодам | Рост NXDOMAIN/SERVFAIL |
| `coredns_cache_hits_total` | Попадания в кэш | Низкий cache hit ratio |
| `coredns_cache_misses_total` | Промахи кэша | Высокий miss rate |
| `coredns_forward_request_duration_seconds` | Латентность пересылки в upstream | p99 > 0.5s |
| `coredns_dns_request_duration_seconds` | Общая латентность запросов | p99 > 0.1s |

### Настройка мониторинга

**ServiceMonitor для Prometheus Operator:**
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: coredns
  namespace: monitoring
spec:
  selector:
    matchLabels:
      k8s-app: kube-dns
  namespaceSelector:
    matchNames:
    - kube-system
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
```

**Prometheus Service Discovery для CoreDNS:**
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'coredns'
    kubernetes_sd_configs:
    - role: endpoints
    relabel_configs:
    - source_labels: [__meta_kubernetes_namespace, __meta_kubernetes_service_name]
      action: keep
      regex: kube-system;kube-dns
    - source_labels: [__meta_kubernetes_endpoint_port_name]
      action: keep
      regex: metrics
```

**Grafana Dashboard:**
- ID дашборда `14518` — CoreDNS мониторинг
- Ключевые панели: request rate, response codes, cache hit ratio, latency percentiles

### Алерты для DNS

**Рекомендуемые алерты:**
```yaml
# PrometheusRule для CoreDNS
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: coredns-alerts
spec:
  groups:
  - name: coredns
    rules:
    - alert: CoreDNSDown
      expr: up{job="coredns"} == 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "CoreDNS is down"
        
    - alert: CoreDNSHighErrorRate
      expr: rate(coredns_dns_response_rcode_count_total{rcode="SERVFAIL"}[5m]) > 0.05
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "High CoreDNS error rate"
        
    - alert: CoreDNSHighLatency
      expr: histogram_quantile(0.99, rate(coredns_dns_request_duration_seconds_bucket[5m])) > 0.5
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "CoreDNS p99 latency > 500ms"
```

---

## Безопасность DNS в Kubernetes

### NetworkPolicy для защиты DNS

**Разрешение DNS-трафика только для определенных подов:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-specific
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

**Запрет прямого доступа к внешним DNS:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-external-dns
  namespace: production
spec:
  podSelector:
    matchLabels:
      network-policy: restricted
  policyTypes:
  - Egress
  egress:
  # Разрешить только DNS к CoreDNS
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/name: kube-system
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  # Запретить прямой доступ к внешним DNS
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 10.96.0.0/16  # Исключить ClusterIP CoreDNS
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

### RBAC для CoreDNS

**Минимальные права для CoreDNS ServiceAccount:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: system:coredns
rules:
- apiGroups:
  - ""
  resources:
  - endpoints
  - services
  - pods
  - namespaces
  verbs:
  - list
  - watch
- apiGroups:
  - discovery.k8s.io
  resources:
  - endpointslices
  verbs:
  - list
  - watch
```

### Защита от DNS-атак

**Rate limiting через CoreDNS:**
```text
.:53 {
    # ... другие плагины ...
    
    # Ограничение частоты запросов
    rate_limit {
        zone "."
        rate 1000
        burst 2000
    }
}
```

**Защита от DNS amplification:**
- Ограничение размера ответов
- Отключение рекурсии для внешних клиентов
- Использование Response Policy Zones (RPZ) для блокировки вредоносных доменов

### DNS-over-TLS (DoT) и DNS-over-HTTPS (DoH)

**Настройка CoreDNS для DoT:**
```text
.:853 {
    tls /etc/coredns/certs/tls.crt /etc/coredns/certs/tls.key
    # ... плагины ...
}
```

**Примечание:** В Kubernetes DoT/DoH обычно настраивается на уровне инфраструктуры (например, через NodeLocal DNSCache или внешний DNS-резолвер), а не внутри CoreDNS.

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

4. **Проверка конфигурации CoreDNS:**
   ```bash
   kubectl get configmap -n kube-system coredns -o yaml
   ```

5. **Проверка сетевой связности:**
   ```bash
   # Из пода к CoreDNS
   kubectl exec -it <pod> -- nc -zv <coredns-ip> 53
   ```

### Расширенная диагностика

**Проверка конкретной DNS-записи:**
```bash
# Использование dig для детальной информации
kubectl run dns-debug --rm -it --image=registry.k8s.io/dnsutils:1.3 -- dig +trace my-service.namespace.svc.cluster.local

# Проверка конкретного типа записи
kubectl run dns-debug --rm -it --image=registry.k8s.io/dnsutils:1.3 -- dig SRV _http._tcp.my-service.namespace.svc.cluster.local
```

**Диагностика проблем с upstream:**
```bash
# Проверка доступности upstream из пода CoreDNS
kubectl exec -n kube-system <coredns-pod> -- nslookup google.com 8.8.8.8

# Проверка DNS на узле
dig @8.8.8.8 google.com
```

**Проверка кэша CoreDNS:**
```bash
# Просмотр статистики кэша
kubectl exec -n kube-system <coredns-pod> -- wget -qO- http://localhost:9153/metrics | grep coredns_cache
```

**Диагностика через плагин debug:**
```text
# Добавить в Corefile для детального логирования
.:53 {
    log . "{remote}:{port} - {>id} '{type} {class} {name} {proto} {size} {>do} {>bufsize}' {rcode} {>rflags} {rsize} {duration}"
    # ...
}
```

### Диагностика NodeLocal DNSCache

NodeLocal DNSCache (NLDC) — критически важный компонент для production-кластеров. Проблемы с ним могут привести к невозможности загрузки образов и сбоям в работе приложений.

**Симптомы проблем с NLDC:**
- Поды не могут загрузить образ с ошибкой `dial tcp: lookup registry: no such host`.
- Неконсистентное поведение: на одних нодах поды работают, на других — нет.
- Задержки при резолвинге DNS-имен (1-5 секунд).

**Алгоритм диагностики:**

1.  **Проверка статуса DaemonSet:**
    ```bash
    kubectl get daemonset -n kube-system node-local-dns
    kubectl rollout status daemonset node-local-dns -n kube-system
    ```

2.  **Проверка подов на конкретных нодах:**
    ```bash
    kubectl get pods -n kube-system -l k8s-app=node-local-dns -o wide
    # Обратить внимание на поды в статусе Error, CrashLoopBackOff, Pending
    ```

3.  **Анализ логов:**
    ```bash
    # Логи конкретного пода
    kubectl logs -n kube-system <node-local-dns-pod-name>
    
    # Логи всех подов
    kubectl logs -n kube-system -l k8s-app=node-local-dns --tail=100
    ```

4.  **Проверка конфигурации (ConfigMap):**
    ```bash
    kubectl get configmap -n kube-system node-local-dns -o yaml
    ```
    Убедиться, что указан корректный `ClusterIP` CoreDNS (обычно `10.96.0.10`).

5.  **Проверка сетевой связности:**
    ```bash
    # Из проблемного пода NLDC
    kubectl exec -n kube-system <node-local-dns-pod> -- nc -zv <coredns-ip> 53
    ```

**Типичные ошибки и решения:**

| Ошибка в логах | Причина | Решение |
|:---|:---|:---|
| `connection refused` к CoreDNS | CoreDNS не работает или недоступен | Перезапустить CoreDNS, проверить Service |
| `bind: address already in use` | Конфликт портов на узле | Проверить, что порт 53 не занят другим процессом |
| `no such host` для upstream | Неверный upstream DNS | Исправить Corefile в ConfigMap |
| `OOMKilled` | Нехватка памяти | Увеличить `resources.limits.memory` |
| `CrashLoopBackOff` на конкретных нодах | Проблема с конкретным узлом | Проверить `kubectl describe node`, ресурсы узла |

**Восстановление при массовом сбое NLDC:**
```bash
# Перезапуск DaemonSet
kubectl rollout restart daemonset node-local-dns -n kube-system

# Если не помогло — удалить проблемные поды вручную
kubectl delete pod -n kube-system -l k8s-app=node-local-dns

# В крайнем случае — пересоздать DaemonSet
kubectl delete daemonset -n kube-system node-local-dns
# Затем заново применить манифест
```

**Важно:** При сбое NLDC на всех узлах кластера может пропасть возможность загрузки образов из внешних реестров, что приведет к `ImagePullBackOff` для новых подов. В этом случае временным решением может быть использование IP-адреса реестра вместо DNS-имени (если поддерживается).

> **Совет для интервью:**
> Если под не может разрешить имя сервиса, проверьте цепочку: `Под -> NetworkPolicy (Egress) -> Service kube-dns -> Endpoints CoreDNS -> CoreDNS Logs -> Upstream DNS`. Самая частая причина в защищенных кластерах — отсутствие разрешения на трафик к `kube-system:53`.

---

## Дополнительная информация

### Сравнение с внешним DNS (ExternalDNS)
CoreDNS управляет именами *внутри* кластера. **ExternalDNS** — это отдельный контроллер, который синхронизирует сервисы/ингрессы Kubernetes с внешними провайдерами (Route53, Cloudflare, Google DNS) для создания публичных записей.

### Сравнение версий CoreDNS

| Версия Kubernetes | Версия CoreDNS | Ключевые изменения |
|:---|:---|:---|
| v1.13-v1.21 | v1.6.x-v1.8.x | Переход с kube-dns на CoreDNS |
| v1.22-v1.25 | v1.8.x-v1.9.x | Стабилизация, улучшение производительности |
| v1.26-v1.28 | v1.10.x | Поддержка EndpointSlices, улучшенный кэш |
| v1.29+ | v1.11.x | Улучшенная безопасность, новые плагины |

### Миграция с kube-dns на CoreDNS

**Почему CoreDNS заменил kube-dns:**
- Единый бинарный файл (vs 3 компонента в kube-dns)
- Модульная архитектура с плагинами
- Лучшая производительность и меньшее потребление памяти
- Более гибкая конфигурация

**Процедура миграции:**
```bash
# Проверка текущего DNS
kubectl get deployment -n kube-system -l k8s-app=kube-dns

# Удаление kube-dns
kubectl delete deployment -n kube-system kube-dns

# Установка CoreDNS (обычно включен по умолчанию в новых кластерах)
kubectl apply -f coredns-deployment.yaml
```

### См. также
- [Headless Service — детальный разбор](./Service/service_type_headless.md)
- [Тип Service — ExternalName](./Service/service_type_externalname.md)
- [Диагностика DNS в Linux](../../Linux/Diagnostics/Networking/dns/overview.md)
- [Петли перенаправления DNS](../../Networking/Protocols/DNS/dns_forwarding_loops.md)
- [Мониторинг DNS](../../Networking/Protocols/DNS/dns_monitoring.md)
- [Безопасность DNS](../../Networking/Protocols/DNS/dns_security.md)
- [Официальная документация Kubernetes DNS](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/)
