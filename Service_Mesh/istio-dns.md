# DNS в Istio: резолюция, DNS proxy и автоаллокация адресов

**Актуально для:** Istio 1.30+

## Определения

**DNS-резолюция в mesh** — процесс получения IP-адреса для имени сервиса (`host`). В Istio DNS участвует на двух уровнях: резолюция эндпоинтов для `ServiceEntry` (самим прокси или istiod) и резолюция имён приложениями (kube-dns/CoreDNS или DNS-прокси Envoy).

**ServiceEntry** — ресурс (`networking.istio.io/v1`), описывающий внешний (MESH_EXTERNAL) или «почти mesh» (MESH_INTERNAL) сервис. Поле `resolution` определяет, как меш узнаёт адреса хоста: `STATIC`, `DNS` или `NONE`.

**DNS Proxy (DNS capture)** — встроенный DNS-прокси Envoy, включаемый через `ISTIO_META_DNS_CAPTURE=true`. Прокси перехватывает DNS-запросы приложения (iptables-редирект на порт 53), отвечает по именам из реестра Istio, разгружая CoreDNS и позволяя работать автоаллоцированным виртуальным адресам. Для ambient mode включён по умолчанию с Istio 1.25.

**DNS Auto Allocation (IP auto-allocation)** — механизм автоматического выделения виртуального IP-адреса (из диапазона `240.240.0.0/16`) для `ServiceEntry` без явно заданных `spec.addresses`. Обеспечивает стабильный адрес хоста для балансировки и идентификации в меше.

**Виртуальный адрес (Virtual IP, VIP)** — не маршрутизируемый адрес из Class E подсети (`240.240.0.0/16`), назначаемый `ServiceEntry` для стабильного идентификатора эндпоинта вне зависимости от реального DNS. Прокси транслирует трафик с VIP к реальным эндпоинтам.

**Class E subnet** — диапазон `240.0.0.0/4`, зарезервированный IETF для экспериментальных целей. Istio использует подмножество `240.240.0.0/16` для автоаллокации VIP.

**Resolution modes** — три режима разрешения `ServiceEntry`: `STATIC` (эндпоинты в manifest), `DNS` (периодический резолвинг istiod), `NONE` (без эндпоинтов, трафик как к прямому TCP).

## Как это работает: архитектура DNS в mesh

DNS в Istio вовлечён на двух независимых уровнях, которые часто путают:

1. **Резолюция эндпоинтов** (control plane → data plane) — `istiod` (Pilot) периодически резолвит `host` из `ServiceEntry` и рассылает список IP-адресов прокси через xDS. Это происходит независимо от того, включён DNS capture или нет. Интервал фиксирован на 30 секунд и не поддаётся изменению.

2. **Резолюция имён приложениями** (data plane) — приложение запрашивает DNS. Без DNS capture запрос идёт к CoreDNS/kube-dns. С DNS capture запрос перехватывается Envoy, который:
   - отвечает из локального реестра (Kubernetes Services, ServiceEntry, headless Service, StatefulSet);
   - для внешних имён форвардит к реальному DNS-резолверу (из `/etc/resolv.conf`);
   - отвечает VIP из автоаллокации, если хост попадает под правило.

Ключевое правило: **DNS Auto Allocation работает только совместно с DNS capture**. Без capture приложение не получит VIP (240.x) от прокси — оно пойдёт к CoreDNS, которому VIP неизвестен, и соединение не установится.

**Область действия DNS proxy**: прокси влияет только на DNS-запросы, исходящие **от приложений**. Для `ServiceEntry` с `resolution: DNS` резолюцию эндпоинтов всё равно выполняет `istiod`, а не DNS proxy. Это важное различие — включение DNS capture не меняет, как `resolution: DNS` ServiceEntry обновляет список эндпоинтов.

**Envoy DNS proxy** — реализован в Envoy как отдельный listener на UDP/TCP 53. Перехват трафика выполняется init-контейнером или CNI (в ambient mode) через перенаправление iptables/nftables на порт 53.

---

## Предварительные требования

- **Kubernetes** 1.30+ (рекомендуется 1.32–1.37 для Istio 1.30+)
- **Istio** 1.30+ (текущая версия на момен 2026 года — 1.31.x)
- **istioctl** версии, совпадающей или совместимой с версией Istio в кластере
- **Sidecar Injection** включена в неймспейсах, где требуется DNS capture (аннотация `sidecar.istio.io/inject: "true"` или метка `istio-injection: enabled`)
- **CoreDNS/kube-dns** доступен для резолюции внешних имён (DNS proxy форвардит туда, если не может ответить сам)
- **Для портов 53**: UDP и TCP — оба протокола должны быть захвачены. Проверьте, что никакие пользовательские правила iptables/nftables не конфликтуют с перенаправлением на порт 53

## Основные концепции

### Резолюция ServiceEntry: три режима

| `resolution` | Поведение | Когда использовать |
| :--- | :--- | :--- |
| **STATIC** | Эндпоинты указаны явно в `endpoints` (IP:port). Трафик идёт ровно на эти адреса. | Внешние сервисы со стабильными IP (базы, legacy-системы). |
| **DNS** | `istiod` периодически резолвит `host` через DNS и строит список эндпоинтов, раздаёт их прокси через xDS. DNS capture не влияет на этот процесс. | Внешние API со статичными DNS-именами. |
| **NONE** | Эндпоинтов нет: адрес берётся из `addresses`/`hosts`; трафик максимально близок к прямому TCP-подключению, резолюцией занимается приложение (обычно через DNS proxy/пакетный passthrough). | Случаи, когда не нужен реальный эндпоинт-пool; multi-cluster; wildcard-домены. |

### Что происходит без DNS capture

По умолчанию (`ISTIO_META_DNS_CAPTURE=false`):
- приложение резолвит имена через кластерный DNS (CoreDNS) или внешние DNS;
- для `ServiceEntry` с `resolution: DNS` эндпоинты получает Control Plane (istiod), периодически резолвя `host` клиентских DNS, и раздаёт их прокси через xDS;
- автоаллоцированные виртуальные адреса (`240.240.0.0/16`) не маршрутизируются в реальной сети — если приложение «увидит» их, соединение не установится. Именно поэтому **DNS Auto Allocation используется вместе с DNS capture**.

### DNS capture: что делает прокси

С `meshConfig.defaultConfig.proxyMetadata.ISTIO_META_DNS_CAPTURE=true` (или через аннотацию пода):
- DNS-запросы приложения перехватываются (iptables-редирект на порт 53 → Envoy DNS-proxy);
- по именам из реестра сервисов (Kubernetes Services, ServiceEntry, StatefulSet headless) proxy отвечает сам;
- для внешних имён запросы проксируются дальше к реальному DNS-резолверу;
- работает ответ по автоаллоцированному VIP: приложение получает `240.240.x.x`, а прокси транслирует трафик к реальным эндпоинтам.

Проверка исходного значения метаданных:

```bash
kubectl get configmap istio -n istio-system -o jsonpath='{.data.mesh}' | grep -A4 ISTIO_META_DNS_CAPTURE
# → (пусто, если не включено) либо
# → defaultConfig:
# →   proxyMetadata:
# →     ISTIO_META_DNS_CAPTURE: "true"
```

### DNS Auto Allocation: назначение и эволюция

Начиная с Istio 1.23 доступен улучшенный механизм автоаллокации:

- **Istio 1.25+**: используется контроллер на основе статуса (`status.addresses`). Флаг `ISTIO_META_DNS_AUTO_ALLOCATE` в `proxyMetadata` **deprecated** — заменён на `PILOT_ENABLE_IP_AUTOALLOCATE` в env istiod. С 1.25 `PILOT_ENABLE_IP_AUTOALLOCATE` включён по умолчанию.
- **Istio 1.24 и ранее**: использовался `ISTIO_META_DNS_AUTO_ALLOCATE` в `proxyMetadata` sidecar'а.

Функция:
- Присваивает `ServiceEntry` с `resolution: NONE` (или `DNS` без `spec.addresses`) виртуальный адрес из `240.240.0.0/16`;
- Даёт стабильный «идентификатор» сервиса для балансировки и сертификатов;
- Позволяет использовать имя хоста из приложения, не полагаясь на DNS внешней сети;
- Поддерживает метку `networking.istio.io/enable-autoallocate-ip: "true/false"` для точечного контроля на уровне `ServiceEntry`.

Ключевое требование: **включённый DNS capture**, иначе VIP не маршрутизируется.

### DNS для headless-сервисов и StatefulSet

- Headless Service (`clusterIP: None`) не имеет ClusterIP — DNS возвращает IP пода напрямую, а sidecar строит эндпоинты из краткого имени (`pod-0.service.ns.svc.cluster.local`).
- DNS capture корректно разрешает headless: приложения получают адрес нужного пода.
- Детали поведения и маршрутизация к конкретным подам описаны в [Прокси Sidecar](./proxy_sidecar.md).

### DNS в ambient mode

В ambient mode DNS capture включён по умолчанию с Istio 1.25. Активация настраивается на уровне CNI:

- `values.cni.ambient.dnsCapture=true` (включено по умолчанию в 1.25+) — глобальная настройка;
- `ambient.istio.io/dns-capture=false` на поде — точечное отключение (может сломать ServiceEntry и egress waypoint);
- Для VM — включается автоматически при `istioctl workload entry configure`.

Ztunnel работает только на уровне L4 и не имеет доступа к HTTP-заголовкам, поэтому DNS proxy обязателен для разрешения `ServiceEntry` в амбиент-режиме.

### Взаимодействие с egress gateway

- `ServiceEntry` + egress gateway обычно используют `resolution: DNS` или `NONE`.
- При egress-шлюзе резолюция часто делегируется шлюзу — см. [Исходящий шлюз (Egress Gateway)](./istio-egress-gateway.md).

---

## Практические сценарии

### Сценарий 1: ServiceEntry с `resolution: DNS` для внешнего API

```yaml
apiVersion: networking.istio.io/v1
kind: ServiceEntry
metadata:
  name: external-api
spec:
  hosts:
  - api.example.com
  location: MESH_EXTERNAL
  ports:
  - number: 443
    name: https
    protocol: TLS
  resolution: DNS
  endpoints:
  - address: api.example.com
    ports:
      https: 443
```

```bash
# Проверка, что прокси знает эндпоинты хоста
istioctl proxy-config cluster deploy/my-app -n production | grep external-api
# → outbound|443||api.example.com ...

# Проверка резолюции эндпоинтов
istioctl proxy-config endpoint deploy/my-app -n production | grep external-api
# → 82.165.12.34:443   HEALTHY   outbound|443||api.example.com
```

### Сценарий 2: Включение DNS capture глобально (Sidecar mode)

```yaml
apiVersion: install.istio.io/v1alpha1
kind: IstioOperator
metadata:
  name: dns-capture
spec:
  meshConfig:
    defaultConfig:
      proxyMetadata:
        ISTIO_META_DNS_CAPTURE: "true"
```

```bash
# Или через istioctl install
istioctl install --set meshConfig.defaultConfig.proxyMetadata.ISTIO_META_DNS_CAPTURE=true
```

Проверка внутри пода:

```bash
kubectl exec -n production deploy/my-app -- sh -c 'nslookup my-service.production.svc.cluster.local'
# → Server:  <ip пода>
# → Address:  <ip пода>:53
# → Name:   my-service.production.svc.cluster.local
# → Address: 10.244.0.10     ← отвечает DNS-прокси Envoy, а не CoreDNS
```

### Сценарий 3: DNS capture и auto-allocation в одном IstioOperator (Istio 1.25+)

В современной версии DNS capture и автоаллокация настраиваются независимо:

```yaml
apiVersion: install.istio.io/v1alpha1
kind: IstioOperator
metadata:
  name: istio-control-plane
spec:
  values:
    pilot:
      env:
        # Автоаллокация VIP (Istio 1.25+, заменяет ISTIO_META_DNS_AUTO_ALLOCATE)
        PILOT_ENABLE_IP_AUTOALLOCATE: "true"
  meshConfig:
    defaultConfig:
      proxyMetadata:
        # DNS capture в sidecar mode
        ISTIO_META_DNS_CAPTURE: "true"
```

### Сценарий 4: DNS Auto Allocation для ServiceEntry без `spec.addresses`

При включённой автоаллокации каждому хосту будет выделен виртуальный адрес из `240.240.0.0/16`:

```yaml
apiVersion: networking.istio.io/v1
kind: ServiceEntry
metadata:
  name: external-auto
  labels:
    networking.istio.io/enable-autoallocate-ip: "true"  # опционально, включено по умолчанию
spec:
  hosts:
  - api.example.com
  location: MESH_EXTERNAL
  resolution: NONE
  ports:
  - number: 443
    name: https
    protocol: TLS
```

Проверка выделенных виртуальных адресов:

```bash
# Вариант 1: через proxy-config endpoint (устаревший способ)
istioctl proxy-config endpoint deploy/my-app -n production | grep 240.
# → 240.240.0.1:443    HEALTHY   outbound|443||api.example.com

# Вариант 2: через status.addresses (новый способ, Istio 1.23+)
kubectl get serviceentry external-auto -o jsonpath='{.status.addresses}'
# → [{"host":"api.example.com","value":"240.240.0.1"}]
```

> Auto-allocation эффективен только с DNS capture: приложение должно получить VIP от DNS-прокси, иначе `240.240.*` не маршрутизируется.

**Точечное отключение** автоаллокации для конкретного ServiceEntry:

```yaml
apiVersion: networking.istio.io/v1
kind: ServiceEntry
metadata:
  name: external-no-auto
  labels:
    networking.istio.io/enable-autoallocate-ip: "false"
spec:
  hosts:
  - specific.example.com
  location: MESH_EXTERNAL
  resolution: DNS
  ports:
  - number: 443
    name: https
    protocol: TLS
```

### Сценарий 5: DNS capture для отдельного пода (аннотация)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  namespace: production
spec:
  template:
    metadata:
      annotations:
        proxy.istio.io/config: |
          proxyMetadata:
            ISTIO_META_DNS_CAPTURE: "true"
    spec:
      containers:
      - name: my-app
        image: my-app:1.0
```

### Сценарий 6: Диагностика DNS-проблем

```bash
# 1. Какие DNS-сервера использует прокси
istioctl proxy-config bootstrap deploy/my-app -n production | grep -A5 "dns_servers"
# → dns_lookup_family: V4_ONLY
# → servers: ["10.96.0.10", "8.8.8.8"]

# 2. Логи DNS-proxy Envoy (включить debug для DNS)
kubectl logs -n production deploy/my-app -c istio-proxy | grep -i dns | tail

# 3. Проверка доступности кластерного DNS из пода
kubectl exec -n production deploy/my-app -- sh -c 'cat /etc/resolv.conf'

# 4. Разрешение имени из реестра меша
kubectl exec -n production deploy/my-app -- sh -c 'getent hosts my-service.production.svc.cluster.local'
# → 10.244.0.10  my-service.production.svc.cluster.local

# 5. Анализ конфигурации меша
istioctl analyze
# → No validation issues found.

# 6. Dry-run проверка резолюции (istiod резолвит сам)
istioctl proxy-config endpoint deploy/my-app -n production | grep external-api
# → 82.165.12.34:443   HEALTHY   outbound|443||api.example.com
```

### Сценарий 7: Кастомные DNS-серверы для резолюции ServiceEntry

При `resolution: DNS` прокси использует DNS-сервера пода (`/etc/resolv.conf`). Если внешний хост резолвится во внутренней DNS зоне, укажите `dnsRefreshRate` и проверьте цепочку:

```yaml
apiVersion: networking.istio.io/v1
kind: ServiceEntry
metadata:
  name: internal-dns-host
  labels:
    networking.istio.io/enable-autoallocate-ip: "true"
spec:
  hosts:
  - internal-api.corp.internal
  location: MESH_EXTERNAL
  resolution: DNS
  ports:
  - number: 8443
    name: https
    protocol: TLS
```

```bash
# Проверка, что хосты резолвятся именно с теми IP, которые ожидает mesh
kubectl exec -n production deploy/my-app -- sh -c 'getent hosts internal-api.corp.internal || echo NOT_RESOLVED'
# → NOT_RESOLVED  ← нет записи в CoreDNS/pod DNS — добавьте в DNS или используйте standalone DNS capture
```

---

## Операции и команды

### Включение / выключение DNS capture

| Способ | Команда / конфиг |
| :--- | :--- |
| Глобально (Sidecar mode) | `meshConfig.defaultConfig.proxyMetadata.ISTIO_META_DNS_CAPTURE=true` в `IstioOperator` |
| На поде | Аннотация `proxy.istio.io/config` с `proxyMetadata.ISTIO_META_DNS_CAPTURE: "true"` |
| Ambient mode | `values.cni.ambient.dnsCapture=true` (вкл. по умолчанию с 1.25) |
| Отключить на поде (ambient) | Аннотация `ambient.istio.io/dns-capture=false` |

### Автоаллокация VIP

| Флаг | Версия | Статус | Где задаётся |
| :--- | :--- | :--- | :--- |
| `ISTIO_META_DNS_AUTO_ALLOCATE` | до 1.25 | **Deprecated** | `proxyMetadata` sidecar'а |
| `PILOT_ENABLE_IP_AUTOALLOCATE` | 1.25+ | **Рекомендуется** | `values.pilot.env` в `IstioOperator` |
| `networking.istio.io/enable-autoallocate-ip` | 1.25+ | Активна | Метка на `ServiceEntry` |

### Проверка состояния

| Цель | Команда |
| :--- | :--- |
| Проверить, включён ли capture в mesh | `kubectl get configmap istio -n istio-system -o jsonpath='{.data.mesh}' \| grep -A4 ISTIO_META_DNS_CAPTURE` |
| Проверить DNS-серверы прокси | `istioctl proxy-config bootstrap <pod> -o json | jq '.static_config.dns_servers'` |
| Проверить эндпоинты с VIP | `istioctl proxy-config endpoint <pod> | grep 240.` |
| Проверить статус адресов ServiceEntry | `kubectl get serviceentry <name> -o jsonpath='{.status.addresses}'` |
| Проверить резолюцию из пода | `kubectl exec <pod> -- getent hosts <hostname>` |
| Анализировать конфигурацию | `istioctl analyze` |

---

## Типичные ошибки и устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Приложение получает `240.240.0.x` и не подключается | DNS capture выключен, а auto-allocation включён | Включить `ISTIO_META_DNS_CAPTURE=true` или задать `spec.addresses` реальными IP |
| `ServiceEntry` с `resolution: DNS` не ловит резолв | Домен не в DNS-зоне, доступной прокси | Добавить запись в DNS; проверить `istioctl proxy-config endpoint` и `/etc/resolv.conf` пода |
| `getent hosts` возвращает другой IP, чем строит меш | Приложение резолвит мимо прокси (capture off) | Включить capture или перевести `resolution: DNS` (прокси резолвит сам) |
| Wildcard `ServiceEntry` с `resolution: NONE` не работает | Нет DNS capture / перекрывающего правила | Включить capture + использовать SNI-маршрутизацию (см. egress) |
| Медленная резолюция внешних хостов | Прокси резолвит через долгий DNS | Проверить `dnsRefreshRate`, кастомные `dns_servers`, under лимитов |
| `istioctl proxy-config endpoint` не показывает эндпоинты | `resolution: DNS` → эндпоины резолвятся istiod, а не proxy | Использовать `istioctl proxy-config cluster` для проверки кластера, а не endpoint |
| Auto-allocation не работает в ambient mode | `PILOT_ENABLE_IP_AUTOALLOCATE` выключен или DNS capture отключён на поде | Включить `values.pilot.env.PILOT_ENABLE_IP_AUTOALLOCATE=true`; проверить аннотацию `ambient.istio.io/dns-capture=false` |
| DNS capture не работает в sidecar mode | Перехват iptables/nftables не настроен (init-контейнер не запустился) | Проверить `istioctl proxy-config bootstrap` → `dns_servers`; проверить логы init-контейнера; убедиться, что порт 53 не занят |

---

## Лучшие практики эксплуатации

1. **Включяйте DNS capture в новых кластерах** — единообразная резолюция через реестр, быстрее отладка, работает auto-allocation.
2. **В ambient mode** DNS capture включён по умолчанию (Istio 1.25+) — не выключайте без крайней необходимости.
3. **`resolution: NONE` — только с DNS capture**, иначе (для внешнего) трафик может идти напрямую мимо меша.
4. **Auto-allocation используйте сознательно**: при статичных внешних IP предпочтите `STATIC` + `addresses`, это исключает хрупкость DNS. Точки, где IP динамик, — назначайте метку `networking.istio.io/enable-autoallocate-ip: "true"`.
5. **Ограничивайте scope**: если `ServiceEntry` нужен не всем workload'ам, используйте `exportTo` или ресурс `Sidecar` — это снижает нагрузку и время резолюции.
6. **Мониторинг**: следите за метриками Envoy DNS-прокси (`envoy_dns_*`) и TTL-ротациями в больших кластерах. Алёрт на рост `envoy_dns_no_such_zone` и аномальные пики `envoy_dns_query_response_size`.

### Мониторинг

| Метрика | Источник | Что мониторить |
| :--- | :--- | :--- |
| `envoy_dns_.*` | Envoy admin / Prometheus | Количество DNS-запросов, hit/miss ratio, ошибки |
| `envoy_cluster_lb_healthy_panic` | Prometheus | Обезяние попаданий — эндпоины стали недоступны |
| `istiod_prometheus_tcp_probe_failure` | istiod metrics | Сбои резолюции DNS в control plane |
| TTL ротация адресов | — | При низком TTL часто резолвятся внешние хосты → нагрузка на DNS |
7. **Сочетайте с egress**: централизованная резолюция внешних хостов обычно живёт на egress gateway; тогда sidecar максимально «не думает» о DNS.
8. **Проверяйте `getent`/`nslookup` из пода до внедрения политик** — часто причина «меш не резолвит» лежит на стороне CoreDNS, а не Istio.
9. **Увеличивайте TTL** для внешних хостов, если контролируете их DNS — интервал резолюции istiod фиксирован на 30 секунд, но частые TTL приводят к лишним запросам к upstream DNS.
10. **Избегайте wildcard `ServiceEntry`** с `resolution: NONE` без DNS capture — VIP не выделяется, резолюция не работает.

### Очистка

После удаления `ServiceEntry` с автоаллокацией:

```bash
# 1. Удалить ServiceEntry
kubectl delete serviceentry external-auto -n istio-system

# 2. Проверить, что VIP больше не используется
istioctl proxy-config endpoint deploy/my-app -n production | grep 240.240
# → (пусто — адреса больше не назначены)

# 3. Если DNS capture больше не нужен — выключить его
kubectl patch configmap istio -n istio-system --type=json -p='[{"op":"remove","path":"/data/mesh"}]'`
# затем переустановить с ISTIO_META_DNS_CAPTURE: "false"
```

---

## Дополнительная информация

### Как DNS capture взаимодействует с iptables/nftables

DNS capture работает через перенаправление трафика UDP/TCP на порт 53 в init-container (sidecar mode) или через CNI (ambient mode). Если приложение использует собственный DNS-кеш или статические записи в `/etc/hosts`, capture может не работать. Проверяйте:

```bash
# Проверить, что перенаправление на 53 работает
kubectl exec -n production deploy/my-app -- sh -c 'cat /etc/resolv.conf'
# → nameserver 10.96.0.10  ← CoreDNS (без capture)
# → nameserver <ip-пода>     ← сама себя (с capture, proxy отвечает локально)
```

### Связь с другими компонентами

- DNS-поведение headless/StatefulSet и `/etc/hosts` — в [Прокси Sidecar: реализации и сценарии](./proxy_sidecar.md).
- Резолюция в multi-cluster (ServiceEntry для удалённых сервисов, автоаллокация VIP) — в [Мультикластерная архитектура](./istio-multicluster.md).
- Внешний доступ и `ServiceEntry` совместно с egress — в [Исходящий шлюз (Egress Gateway)](./istio-egress-gateway.md).
- Общая модель разрешения DNS и резолюция в mesh — в [Понятие DNS в Istio](https://istio.io/latest/docs/ops/configuration/traffic-management/dns/).

### См. также

- [Управление трафиком в Service Mesh](./traffic_management.md)
- [Service Mesh: основные концепции](./service_mesh_concepts.md)
- [OpenShift/CoreDNS: сущности в Kubernetes](../Kubernetes/Networking/Service/service_type_externalname.md) — ExternalName как альтернатива для простых внешних имён
- [DNS Proxy в Cilium](../Kubernetes/Networking/Network/NetworkPolicy/fqdn_filtering.md) — FQDN-фильтрация и DNS proxy в CNI

### Документация

- [Istio: DNS Proxying](https://istio.io/latest/docs/ops/configuration/traffic-management/dns-proxy/)
- [Istio: Understanding DNS](https://istio.io/latest/docs/ops/configuration/traffic-management/dns/)
- [Istio: ServiceEntry](https://istio.io/latest/docs/reference/config/networking/service-entry/)
- [Istio 1.25 Change Notes](https://istio.io/latest/news/releases/1.25.x/announcing-1.25/change-notes/) — deprecation `ISTIO_META_DNS_AUTO_ALLOCATE`