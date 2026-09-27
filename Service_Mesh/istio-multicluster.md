# Мультикластерная и мультисетевая архитектура Istio

## Определения

**Мультикластер (multi-cluster)** — единый логический service mesh, работающий поверх нескольких независимых Kubernetes-кластеров. Сервисы из разных кластеров обнаруживаются друг другом, общаются через mTLS и управляются общими политиками.

**meshID** — идентификатор логического меша (`values.global.meshID`). Одинаковый у всех кластеров одного mesh; используется для объединения и разграничения.

**trustDomain** — домен доверия (например, `cluster.local`), входящий в состав SPIFFE SVID сервиса (`spiffe://<trustDomain>/ns/<ns>/sa/<sa>`). Для сквозного mTLS между кластерами trustDomain (и корневой CA) должны совпадать.

**RemoteSecret** — Kubernetes Secret в `istio-system` primary-кластера с kubeconfig удалённого кластера, используемый для обнаружения сервисов remote-кластера через его API-сервер.

**East-West Gateway** — шлюз (обычно на порту 15443) внутри mesh для межкластерного/межсетевого трафика между сервисами, когда сети кластеров не связаны напрямую (multi-network).

**Network (сеть)** — изолированный сетевой сегмент (`values.global.network`). Кластеры в одной сети общаются напрямую по IP; между разными сетями трафик ходит через east-west gateway.

**Multi-Primary** — модель, в которой каждый кластер имеет собственный istiod, а конфигурация распространяется между ними.

---

## Основные концепции

### Модели развертывания

| Модель | Control Plane | Discovery | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Primary-Remote** | Один istiod (primary) + лёгкий istiod/данные на remote | Primary читает kubeconfig remote через RemoteSecret | Централизованное управление, один «владелец» mesh |
| **Multi-Primary** | Полноценный istiod в каждом кластере | Взаимные RemoteSecret / shared API server | Высокая автономия кластеров, нет единой точки управления |
| **External (mesh expansion)** | istiod + VM-подобные сервисы | WorkloadEntry/WorkloadGroup | VM и bare-metal вне Kubernetes |

**Mixed/primary-remote многосетевой**: для каждого кластера задаётся `network` — если сети разные, требуется east-west gateway для связи между ними.

### Как работает discovery между кластерами

1. На кластере-источнике создаётся kubeconfig с минимальными правами (`system:node` / service-account read API endpoints).
2. `istioctl x create-remote-secret` формирует Secret с этим kubeconfig.
3. Secret применяется на primary (или на каждый кластер в multi-primary).
4. istiod подписывается на изменения API-сервера remote-кластера и строит эндпоинты для сервисов, как если бы они были локальными.
5. Сервисы remote-кластера становятся видимыми в `istioctl proxy-config endpoint` и Kiali.

Перенос конфигурации — отдельно: ресурсы (VirtualService, DestinationRule, Gateway) с `exportTo` и remote secrets; конфиги глобальных политик агрегируются по trust domain.

### mTLS между кластерами

- **Same trust domain + root CA**: поды `cluster-a` и `cluster-b` доверяют друг другу автоматически → mTLS и `AuthorizationPolicy` работают сквозь кластеры.
- **Разные trust domains**: требуется федерация (передача trust anchors и политик), повышается сложность.
- Сертификаты в кластерах продлеваются: в primary-remote сертификаты для remote выдаёт primary; в multi-primary — каждый свой CA (должен быть привязан к общему корню).

### Multi-network и east-west gateway

- **Same network**: эндпоинты remote-кластера видны как обычные IP → трафик идёт напрямую (через sidecar/ztunnel).
- **Different networks** (`network1`/`network2`):
  - объявляется `serviceNetworks` в MeshConfig с CIDR сетей;
  - разворачивается east-west gateway в каждом кластере (listener на порт 15443);
  - cross-network трафик идёт: sidecar → east-west gateway (native) → east-west gateway другого кластера → sidecar;
  - для Ambient: межкластерный трафик также проходит через east-west gateway/ztunnel.

### Failover и locality между кластерами

- Istio поддерживает weighted locality LB через `destinationRule.trafficPolicy.localityLbSetting` (`distribute`, `failover`).
- Каждому кластеру можно задать `region/zone`; при недоступности локальных эндпоинтов Envoy переключается на эндпоинты другой locality (`failover: [{from: <local>, to: <remote>}]`).
- Работает поверх эндпоинтов из разных кластеров (для этого и нужен discovery remote-кластеров).
- Простые варианты failover (без locality) выполняются на уровне HTTPRoute/DNS (например, весовой балансировщик перед шлюзом).

---

## Практические сценарии

### Сценарий 1: Primary-Remote (базовая конфигурация)

Первый кластер — primary (управляющий), второй — remote.

```bash
# 1. Установка primary (cluster-a)
istioctl install --set profile=default \
  --set values.global.meshID=mesh1 \
  --set values.global.multiCluster.clusterName=cluster-a \
  --set values.global.network=network1

# 2. Установка remote (cluster-b) — без собственного istiod (лёгкий)
istioctl install --set profile=remote \
  --set values.global.meshID=mesh1 \
  --set values.global.multiCluster.clusterName=cluster-b \
  --set values.global.network=network2

# 3. Создание remote-secret на primary из контекста cluster-b
istioctl x create-remote-secret --name=cluster-b --context=cluster-b | \
  kubectl --context=cluster-a apply -f - -n istio-system

# 4. Проверка: сервис из cluster-b виден в cluster-a
kubectl --context=cluster-a get endpoints -n istio-system | grep cluster-b
```

### Сценарий 2: Multi-Primary

```bash
# На КАЖДОМ кластере полноценный istiod
istioctl install --context=cluster-a --set profile=default \
  --set values.global.meshID=mesh1 \
  --set values.global.multiCluster.clusterName=cluster-a \
  --set values.global.network=network1 --set values.global.trustDomain=cluster.local

istioctl install --context=cluster-b --set profile=default \
  --set values.global.meshID=mesh1 \
  --set values.global.multiCluster.clusterName=cluster-b \
  --set values.global.network=network2 --set values.global.trustDomain=cluster.local

# Взаимные remote secrets (обязательно в обе стороны)
istioctl x create-remote-secret --name=cluster-b --context=cluster-b | kubectl --context=cluster-a apply -f - -n istio-system
istioctl x create-remote-secret --name=cluster-a --context=cluster-a | kubectl --context=cluster-b apply -f - -n istio-system
```

### Сценарий 3: East-West gateway для multi-network

```bash
# Развертывание east-west gateway в КАЖДОМ кластере (пример из sample-скриптов Istio)
samples/multicluster/gen-eastwest-gateway.sh \
  --mesh mesh1 --cluster cluster-a --network network1 | istioctl install --manifest-files -

# Разрешение cross-network трафика через ServiceEntry/флаг
# В MeshConfig обязательно указать serviceNetworks для сетей обоих кластеров
istioctl install --set meshConfig.defaultConfig.proxyMetadata.ISTIO_META_NETWORK=network1
```

```bash
# Проверка listener'ов east-west gateway (порт 15443)
istioctl proxy-config listener deploy/istio-eastwestgateway -n istio-system --port 15443
# → 0.0.0.0:15443  ... (перехват cross-network трафика)
```

### Сценарий 4: Failover между кластерами по locality

```yaml
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: cross-cluster-failover
spec:
  host: my-service
  trafficPolicy:
    loadBalancer:
      localityLbSetting:
        enabled: true
        failover:
        - from: region-a
          to: region-b
```

```bash
# Настройка locality каждого кластера (пример через --set при установке)
--set meshConfig.outboundTrafficPolicy.mode=ALLOW_ANY \
--set values.pilot.autoscaleEnabled=true

# Проверка, что эндпоинты обоих кластеров в одном cluster'е
istioctl proxy-config endpoint deploy/client -n production | grep my-service
# → 10.244.1.7:8080  HEALTHY  ...  (region-a)
# → 10.245.2.3:8080  HEALTHY  ...  (region-b)
# При отказе region-a Envoy переключится на region-b автоматически
```

### Сценарий 5: Виртуальные сервисы через кластеры

```yaml
apiVersion: networking.istio.io/v1
kind: ServiceEntry
metadata:
  name: remote-svc
spec:
  hosts:
  - my-service.production.svc.cluster.local
  location: MESH_INTERNAL
  addresses:
  - 240.0.0.10
  ports:
  - number: 8080
    name: http
    protocol: HTTP
  resolution: DNS
  endpoints:
  - address: my-service-cluster-b.production.svc.cluster.local
```

```bash
# Трафик к my-service из кластера A направляется в B через east-west
kubectl exec -n production deploy/client -- curl -s http://my-service.production.svc.cluster.local:8080/health
# → {"status":"ok"}
```

### Диагностика мультикластерности

```bash
# 1. Remote secrets в primary
kubectl get remoteistio -n istio-system
# → NAME    STATUS
# → empty   Configured

# 2. Видимость сервисов другого кластера
kubectl --context=cluster-a get endpoints <service>.<ns> -n <ns>

# 3. Синхронизация прокси
istioctl proxy-status | grep -v SYNCED   # не должно быть NOT SYNCED

# 4. Анализ конфигурации
istioctl analyze -A

# 5. Логи istiod при ошибках discovery
kubectl logs -n istio-system deploy/istiod --tail=200 | grep -iE "remote|cluster-b|error"
```

---

## Типичные ошибки и устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Сервис remote не виден в primary | Нет RemoteSecret или права kubeconfig недостаточны | `istioctl x create-remote-secret` повторно; проверить Secret в `istio-system` |
| mTLS между кластерами не работает | Разные trustDomain/root CA | Установить совпадающий `trustDomain`/общий `ROOTCA`; при ином — федерация |
| Slow connections между кластерами в разных сетях | Нет east-west gateway / serviceNetworks | Развернуть east-west gateway; указать `serviceNetworks` |
| Эндпоинты видны, но `connection refused` | Отсутствует cross-network путь (VPN/overlay/NSG) | Проверить связность узлов/сетей; настроить network gateway |
| `404 ServiceEntry not found` у клиента | `ServiceEntry` не создан в namespace клиента | Создать ServiceEntry; проверить `exportTo` |
| Повторяющиеся конфликты в политиках между кластерами | Один и тот же trustDomain, разные политики | Использовать `exportTo` и namespace scoping; согласовать глобальные политики |

---

## Лучшие практики эксплуатации

1. **Единый `meshID` и одинаковый `trustDomain`** — база сквозного mTLS и политик.
2. **Уникальный `clusterName`** на каждый кластер — без него не работают locality и наблюдение.
3. **Минимальные права RemoteSecret**: создавайте remote secrets с ограниченным RBAC (только чтение endpoints/services для mesh).
4. **Разделение сетей**: используйте разные `network` только при реальной сетевой изоляции; иначе лишние hops east-west gateway.
5. **East-west gateway под HPA/PDB** — межкластерный трафик не должен зависеть от одной реплики.
6. **Failover проектируйте по locality**, тестируйте отказ кластера (см. [Chaos Engineering](../Chaos_Engineering/)).
7. **Мониторинг cross-cluster**: отслеживайте метрики east-west gateway отдельно; alert на потерю эндпоинтов remote-кластеров.
8. **Канареечные апгрейды** отдельных кластеров — по ревизиям (см. [istio_canary_upgrades.md](./istio_canary_upgrades.md)), предварительно проверив совместимость версий между кластерами.

---

## Дополнительная информация

### Связь с другими темами

- Общее сравнение подходов multi-cluster (Cilium Cluster Mesh, Submariner, KubeFed) — [Networking: Multi-cluster Networking](../Networking/Concepts/sdn/multi_cluster_networking.md).
- VM/bare-metal вне кластера (mesh expansion) — [Интеграция виртуальных машин в Istio](./istio_vm_workloads.md).
- Cross-cluster DNS/ServiceEntry-адресация — [DNS в Istio](./istio-dns.md).
- Федерация trust anchors и мультикластерная безопасность — [Политики безопасности Istio](./istio-security-policies.md).

### См. также

- [Архитектура и компоненты Istio](./istio_architecture.md)
- [Управление трафиком в Service Mesh](./traffic_management.md)
- [Сравнение Istio и Linkerd](./istio_vs_linkerd.md)

Документация: [Istio: Multicluster](https://istio.io/latest/docs/setup/install/multicluster/).