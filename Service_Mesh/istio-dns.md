# DNS в Istio: резолюция, DNS proxy и автоаллокация адресов

## Определения

**DNS-резолюция в mesh** — процесс получения IP-адреса для имени сервиса (`host`). В Istio DNS участвует на двух уровнях: резолюция эндпоинтов для `ServiceEntry` (самим прокси) и резолюция имён приложениями (kube-dns/CoreDNS или DNS-прокси Envoy).

**ServiceEntry** — ресурс, описывающий внешний (MESH_EXTERNAL) или «почти mesh» (MESH_INTERNAL) сервис. Поле `resolution` определяет, как меш узнаёт адреса хоста: `STATIC`, `DNS` или `NONE`.

**DNS Proxy (DNS capture)** — встроенный DNS-прокси Envoy, включаемый через `ISTIO_META_DNS_CAPTURE=true`. Прокси отвечает на DNS-запросы приложения по именам из реестра Istio, разгружая CoreDNS и позволяя работать автоаллоцированным виртуальным адресам.

**DNS Auto Allocation (DNS_AUTO_ALLOCATE_ADDRESS)** — механизм автоматического выделения виртуальному IP-адресу (из диапазона 240.0.0.0/4) для ServiceEntry с `resolution: NONE`, у которого не задан `addresses`. Позволяет присвоить стабильный адрес внешнему хосту для балансировки и идентификации в меше.

**Виртуальный адрес (Virtual IP)** — адрес из зарезервированного диапазона Istio (240.0.0.0/4), назначаемый ServiceEntry для обеспечения стабильности адреса вне зависимости от реального DNS.

---

## Основные концепции

### Резолюция ServiceEntry: три режима

| `resolution` | Поведение | Когда использовать |
| :--- | :--- | :--- |
| **STATIC** | Эндпоинты указаны явно в `endpoints` (IP:port). Трафик идёт ровно на эти адреса. | Внешние сервисы со стабильными IP (базы, legacy-системы). |
| **DNS** | Прокси (или istiod) периодически резолвит `host` через DNS и строит список эндпоинтов. При `ISTIO_META_DNS_CAPTURE=true` резолвит Envoy, иначе — планировщик DNS (control plane). | Внешние API со статичными DNS-именами. |
| **NONE** | Эндпоинтов нет: адрес берётся из `addresses`/`hosts`; трафик максимально близок к прямому TCP-подключению, резолюцией занимается приложение (обычно через DNS proxy/пакетный passthrough). | Случаи, когда не нужен реальный эндпоинт-пул; multi-cluster; wildcard-домены. |

### Что происходит без DNS capture

По умолчанию (`ISTIO_META_DNS_CAPTURE=false`):
- приложение резолвит имена через кластерный DNS (CoreDNS) или внешние DNS;
- для `ServiceEntry` с `resolution: DNS` эндпоинты получает Control Plane (istiod), периодически резолвя `host` клиентских DNS, и раздаёт их прокси через xDS;
- автоаллоцированные виртуальные адреса (240.0.0.0/4) не маршрутизируются в реальной сети — если приложение «увидит» их, соединение не установится. Именно поэтому **DNS Auto Allocation используется вместе с DNS capture**.

### DNS capture: что делает прокси

С `meshConfig.defaultConfig.proxyMetadata.ISTIO_META_DNS_CAPTURE=true` (или через аннотацию пода):
- DNS-запросы приложения перехватываются (iptables-редирект на порт 53 → Envoy DNS-proxy);
- по именам из реестра сервисов (Kubernetes Services, ServiceEntry, StatefulSet headless) proxy отвечает сам;
- для внешних имён запросы проксируются дальше к реальному DNS-резолверу;
- работает ответ по автоаллоцированному VIP: приложение получает 240.x.x.x, а прокси транслирует трафик к реальным эндпоинтам.

Проверка исходного значения метаданных:

```bash
kubectl get configmap istio -n istio-system -o jsonpath='{.data.mesh}' | grep -A4 ISTIO_META_DNS_CAPTURE
# → (пусто, если не включено) либо
# → defaultConfig:
# →   proxyMetadata:
# →     ISTIO_META_DNS_CAPTURE: "true"
```

### DNS Auto Allocation: назначение

- Присваивает ServiceEntry с `resolution: NONE` виртуальный адрес, если `addresses` не задан (аннотации достаточно).
- Даёт стабильный «идентификатор» сервиса для балансировки и сертификатов.
- Позволяет использовать имя хоста из приложения, не полагаясь на DNS внешней сети.
- Ключевое требование: **включённый DNS capture**, иначе VIP не маршрутизируется.

### DNS для headless-сервисов и StatefulSet

- Headless Service (`clusterIP: None`) не имеет ClusterIP — DNS возвращает IP пода напрямую, а sidecar строит эндпоинты из краткого имени (`pod-0.service.ns.svc.cluster.local`).
- DNS capture корректно разрешает headless: приложения получают адрес нужного пода.
- Детали поведения и маршрутизация к конкретным подам описаны в [Прокси Sidecar](./proxy_sidecar.md).

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

### Сценарий 2: Включение DNS capture глобально

```yaml
# Или через istioctl install --set meshConfig.defaultConfig.proxyMetadata.ISTIO_META_DNS_CAPTURE=true
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

Проверка внутри пода:

```bash
kubectl exec -n production deploy/my-app -- sh -c 'nslookup my-service.production.svc.cluster.local'
# → Server:  <ip пода>
# → Address:  <ip пода>:53
# → Name:   my-service.production.svc.cluster.local
# → Address: 10.244.0.10     ← отвечает DNS-прокси Envoy, а не CoreDNS
```

### Сценарий 3: DNS Auto Allocation для wildcard ServiceEntry

```yaml
apiVersion: networking.istio.io/v1
kind: ServiceEntry
metadata:
  name: allowed-wildcard
spec:
  hosts:
  - "*.example.com"
  location: MESH_EXTERNAL
  resolution: NONE
  ports:
  - number: 443
    name: https
    protocol: TLS
```

При включённом `DNS_AUTO_ALLOCATE_ADDRESS` каждому хосту будет выделен виртуальный адрес из 240.0.0.0/4:

```bash
# Проверка выделенных виртуальных адресов
istioctl proxy-config endpoint deploy/my-app -n production | grep 240.
# → 240.0.0.1:443    HEALTHY   outbound|443||api.example.com
```

> Auto-allocation эффективен только c DNS capture: приложение должно получить VIP от DNS-прокси, иначе 240.* не маршрутизируется.

### Сценарий 4: Диагностика DNS-проблем

```bash
# 1. Какие DNS-сервера использует прокси
istioctl proxy-config bootstrap deploy/my-app -n production | grep -A3 "dns_servers"
# → dns_lookup_family: V4_ONLY
# → servers: ["10.96.0.10", "8.8.8.8"]

# 2. Логи DNS-proxy Envoy
kubectl logs -n production deploy/my-app -c istio-proxy | grep -i dns | tail

# 3. Проверка доступности кластерного DNS из пода
kubectl exec -n production deploy/my-app -- sh -c 'cat /etc/resolv.conf'

# 4. Анализ конфигурации меша
istioctl analyze
# → No validation issues found.
```

### Сценарий 5: Кастомные DNS-серверы для резолюции ServiceEntry

При `resolution: DNS` прокси использует DNS-сервера пода (`/etc/resolv.conf`). Если внешний хост резолвится во внутренней DNS зоне, укажите `dnsRefreshRate` и проверьте цепочку:

```yaml
apiVersion: networking.istio.io/v1
kind: ServiceEntry
metadata:
  name: internal-dns-host
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

## Типичные ошибки и устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Приложение получает 240.0.0.x и не подключается | DNS capture выключен, а auto-allocation включён | Включить `ISTIO_META_DNS_CAPTURE=true` или задать `addresses` реальными IP |
| `ServiceEntry` с `resolution: DNS` не ловит резолв | Домен не в DNS-зоне, доступной прокси | Добавить запись в DNS; проверить `istioctl proxy-config endpoint` и `/etc/resolv.conf` пода |
| `getent hosts` возвращает другой IP, чем строит меш | Приложение резолвит мимо проyкси (capture off) | Включить capture или перевести `resolution: DNS` (прокси резолвит сам) |
| Wildcard ServiceEntry не работает | Для `resolution: NONE` нет DNS capture/перекрывающего правила | Включить capture + использовать SNI-маршрутизацию (см. egress) |
| Медленная резолюция внешних хостов | Прокси резолвит через долгий DNS | Проверить `dnsRefreshRate`, кастомные `dns_servers`, under лимитов |

---

## Лучшие практики эксплуатации

1. **Включайте DNS capture в новых кластерах** — единообразная резолюция через реестр, быстрее отладка, работает auto-allocation.
2. **`resolution: NONE` — только с DNS capture**, иначе (для внешнего) трафик может идти напрямую мимо меша.
3. **Не используйте DNS auto-allocation без необходимости**: при статичных внешних IP предпочтите `STATIC`+`addresses`, это исключает хрупкость DNS.
4. **Мониторинг**: следите за метриками Envoy DNS-прокси (`envoy_dns_*`) и ttl-ротациями в больших кластерах.
5. **Сочетайте с egress**: централизованная резолюция внешних хостов обычно живёт на egress gateway; тогда sidecar максимально «не думает» о DNS.
6. **Проверяйте `getent`/`nslookup` из пода до внедрения политик** — часто причина «меш не резолвит» лежит на стороне CoreDNS, а не Istio.

---

## Дополнительная информация

### Связь с другими компонентами

- DNS-поведение headless/StatefulSet и `/etc/hosts` — в [Прокси Sidecar: реализации и сценарии](./proxy_sidecar.md).
- Резолюция в multi-cluster (ServiceEntry для удалённых сервисов, `DNS_AUTO_ALLOCATE_ADDRESS`) — в [Мультикластерная архитектура](./istio-multicluster.md).
- Внешний доступ и `ServiceEntry` совместно с egress — в [Исходящий шлюз (Egress Gateway)](./istio-egress-gateway.md).

### См. также

- [Управление трафиком в Service Mesh](./traffic_management.md)
- [Service Mesh: основные концепции](./service_mesh_concepts.md)
- [OpenShift/CoreDNS: сущности в Kubernetes](../Kubernetes/Networking/Service/service_type_externalname.md) — ExternalName как альтернатива для простых внешних имён

Документация: [Istio: DNS Proxy](https://istio.io/latest/docs/ops/configuration/traffic-management/dns-proxy/).