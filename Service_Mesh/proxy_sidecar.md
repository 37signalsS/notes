# Прокси Sidecar: реализации и сценарии

**Актуально для:** Istio 1.31.x

## Определения

**Proxy Sidecar (сайдкар-прокси)** — специализированный сетевой прокси, развёртываемый в одном Pod с приложением (в отдельном контейнере) и обрабатывающий весь входящий и исходящий трафик. Этот паттерн является фундаментом плоскости данных (Data Plane) в архитектуре [Service Mesh](./service_mesh_concepts.md).

**Концепция и аналогия:**
Работу сайдкара можно сравнить с дополнительной коляской у мотоцикла или боковыми колесами велосипеда:
- **Разделение обязанностей:** приложение «управляет» бизнес-логикой, а сайдкар берет на себя вспомогательные задачи: навигацию (routing), безопасность (encryption), коммуникацию и мониторинг.
- **Снятие нагрузки:** разработчику не нужно внедрять сложный сетевой код (ретраи, таймауты, разрыв цепи) в каждое приложение; прокси действует как посредник (middleman), перехватывая трафик и обеспечивая его доставку в «самом быстром и безопасном виде».

**Терминология:**
- Понятия **Sidecar** и **Proxy** в контексте Service Mesh часто используются как взаимозаменяемые.
- **Sidecar Injection (инъекция)** — процесс добавления контейнера-прокси в рабочую нагрузку (workload). Может выполняться автоматически (на уровне неймспейса) или вручную.

**Ключевые функции сайдкара:**
- **Traffic Routing:** выбор оптимального пути и балансировка нагрузки.
- **Resilience:** автоматические повторные попытки (retries), таймауты и разрыв цепи (**Circuit Breaking**) для предотвращения каскадных сбоев.
- **Security:** прозрачное шифрование (mTLS), аутентификация и авторизация.
- **Observability:** сбор метрик (RPS, Latency), логирование и трассировка запросов.
- **Advanced Control:** ограничение скорости (**Rate Limiting**), сжатие трафика и зеркалирование запросов (Mirroring).

**Перехват трафика (Interception):** процесс прозрачного перенаправления сетевых пакетов из сетевого пространства имён (Network Namespace) приложения в прокси.
- **iptables:** традиционный метод через правила NAT/REDIRECT. Создаёт накладные расходы на прохождение пакетов через стек ядра. Требует привилегированный init-контейнер (`istio-init`).
- **nftables:** современная альтернатива iptables (в Istio 1.27+ включается параметром `values.global.nativeNftables=true`), более эффективная при большом объёме правил и приоритетная для новых инсталляций.
- **eBPF (SOCKMAP, Experimental):** метод ускорения передачи данных между сокетами приложения и прокси на уровне ядра, минуя TCP/IP-стек. Требует kernel 4.18+, специальной сборки Envoy с `--define=sockmap=enabled` и eBPF-объекта. В Istio используется в амбиентном режиме через Istio CNI (eBPF redirect), а для sidecar mode требует ручной настройки и не является стандартом.
- **CNI-редирект (Istio CNI / Cilium):** редирект выполняется CNI-плагином на уровне сетевого интерфейса пода вместо привилегированного `istio-init`. Это убирает потребность в `NET_ADMIN` для init-контейнера, повышает безопасность и упрощает политики. Подробнее в [Архитектуре Istio](./istio_architecture.md).

**Native Sidecar (нативный сайдкар):** механизм Kubernetes 1.29+ (стабилен в 1.33+), позволяющий запускать прокси как `initContainer` с `restartPolicy: Always`. Это гарантирует, что прокси будет готов *до* старта приложения и завершится *после* него, решая проблему гонки состояний (Race Condition). Дополнительно решает известную проблему «зависших» **Job**: с нативным сайдкаром Job завершается корректно, потому что прокси получает `SIGTERM` после выхода приложения, а не блокирует завершение пода.

**Альтернатива Ambient:** [Ambient Mesh](./istio_architecture.md) достигла статуса GA ещё в Istio 1.24 (ноябрь 2024) и в версиях 1.30+ считается рекомендуемой моделью для новых развёртываний. Это архитектура без sidecar на уровне каждого пода, где функции разделены между Ztunnel (L4 на уровне узла) и Waypoint Proxy (L7 на уровне неймспейса).

**Протокол xDS (Envoy):** сайдкар-прокси получает конфигурацию от Control Plane через семейство протоколов xDS поверх gRPC:
- **CDS (Cluster Discovery Service):** динамические списки upstream-сервисов (кластеров). При изменении сервисов (добавление/удаление эндпоинтов) Istio отправляет обновление CDS, и Envoy перестраивает пулы соединений без перезапуска.
- **LDS (Listener Discovery Service):** конфигурация слушателей (портов и протоколов, на которых прокси принимает соединения). Включает цепочки фильтров (filter chains), определяющие обработку трафика.
- **RDS (Route Discovery Service):** таблицы маршрутизации для L7-запросов (HTTPRoute, VirtualService). Отвечают за выбор upstream на основе заголовков, путей и весов.
- **EDS (Endpoint Discovery Service):** динамические списки эндпоинтов (IP:port) для каждого кластера. EDS — основной механизм обслуживания сервисов в Service Mesh; при обновлении Service Endpoints Control Plane отправляет только дельту, а не полный конфиг.
- **SDS (Secret Discovery Service):** распределение TLS-сертификатов и доверенных корневых CA. В Istio SDS используется для доставки mTLS-сертификатов (SPIFFE-идентификаторы), что исключает необходимость монтирования секретов в том.

**Bootstrap-конфигурация:** при старте Envoy загружает статическую bootstrap-конфигурацию (обычно из `/etc/envoy/envoy.yaml` или через переменные окружения), которая определяет:
- адрес `xds`-сервера (в Istio — `istiod:15012`);
- порты администрирования (обычно `15000` для admin, `15001` для outbound, `15006` для inbound HTTP, `15020` для health checks Istio-агента);
- корневые CA для проверки сертификатов Control Plane;
- параметры лимитов соединений и таймаутов на уровне ядра.

**Hot Restart (горячий перезапуск):** Envoy поддерживает горячую перезагрузку через сигнал `SIGTERM` с флагом `--drain-time-s` и `--parent-shutdown-time-s`. Это позволяет обновлять конфигурацию или образ прокси без потерь соединений:
1. Envoy перестаёт принимать новые соединения на слушателях.
2. Ожидает завершения активных соединений (`drain-time-s`, обычно 5–30 секунд).
3. Запускает новый процесс Envoy с обновлённой конфигурацией.
4. Новый процесс сигнализирует готовность, после чего старый завершается.

В Service Mesh горячий перезапуск управляется Control Plane (istiod), который отправляет дельту xDS-конфигурации. Полный перезапуск пода требуется только при обновлении образа прокси.

**Listener Filter Chains:** каждая цепочка фильтров (filter chain) привязана к слушателю и определяет порядок обработки трафика. Envoy последовательно применяет фильтры:
1. **Сетевые фильтры (Network Filters):** работают на L3/L4 (TCP). Пример: `TcpProxy` для простого проброса, `TlsInspector` для SNI-инспекции.
2. **HTTP-фильтры (HTTP Connection Manager):** активируются для HTTP/1.1, HTTP/2 и gRPC-трафика. Цепочка обычно: `envoy.filters.http.health_check` → `envoy.filters.http.router` + пользовательские фильтры (WASM, Lua, fault injection).
3. **Rate Limit, Fault Injection, CORS:** применяются на уровне HTTP-фильтров.

Filter chains критичны для Service Mesh: Istio генерирует отдельную цепочку для inbound-трафика (с политиками AuthorizationPolicy) и для outbound (с маршрутизацией VirtualService/DestinationRule).

---

## Предварительные требования

- **Kubernetes:** версия 1.29+ (для нативных сайдкаров — 1.29+ с `SidecarContainers` feature gate; стабильно с 1.33+).
- **Istio:** версия 1.27+ (Native Sidecar по умолчанию с 1.27; nftables с 1.27+; Ambient mode GA с 1.24).
- **istioctl:** утилита командной строки для диагностики и управления инъекцией.
- **CNIプラグин:** Istio CNI (`istio-cni`) для перехвата трафика без привилегированного init-контейнера (рекомендуется для production).
- **CoreDNS:** для резолюции внутри пода без DNS capture.
- **Доступ к API Kubernetes:** для проверки статуса подов, логов и конфигурации прокси.

## Основные концепции: Envoy и Linkerd-proxy

### Envoy Proxy: «Золотой стандарт» индустрии
**Envoy** — это высокопроизводительный Open Source прокси-сервер с открытым исходным кодом, изначально созданный компанией **Lyft** и переданный в **CNCF** (Cloud Native Computing Foundation).

**Экосистема:**
Envoy является самой популярной реализацией сайдкар-прокси и используется в:
- **Istio** (использует расширенную версию Envoy).
- **HashiCorp Consul**.
- **Kuma**.
- **AWS App Mesh**.

**Ключевые функции Envoy:**
- **Контроллер трафика:** выбор оптимального пути для сообщений.
- **Балансировщик нагрузки:** распределение запросов между экземплярами сервиса.
- **Безопасность:** прозрачное шифрование трафика (mTLS) и проверка доверия между сервисами.
- **Наблюдаемость:** отслеживание RPS, задержек и состояния здоровья приложений.
- **Расширенные возможности:** ограничение скорости (Rate Limiting), разрыв цепи (Circuit Breaking), сжатие трафика (Compression) и зеркалирование запросов (Mirroring).

### Другие реализации:
- **Linkerd-proxy:** микро-прокси на Rust, созданный специально для Linkerd.
- **Traefik Proxy:** используется в Traefik Mesh.
- **HAProxy:** может использоваться в качестве прокси в HashiCorp Consul (как альтернатива Envoy) или в самописных решениях.

### Proxyless gRPC (без сайдкара)

**Proxyless gRPC** — модель, при которой gRPC-приложение само подключается к Control Plane по протоколу **xDS**, без Envoy-сайдкара: логика маршрутизации, балансировки и mTLS выполняется gRPC-стеком приложения. В Istio доступна как экспериментальная опция с 1.11 (шаблон инъекции `grpc-agent`: в под внедряется только `pilot-agent` с bootstrap-файлом, Envoy не запускается). Требования и ограничения:

- **Версия gRPC ≥ 1.39** с включёнными xDS-функциями; часть функций реализована не во всех языковых имплементациях gRPC (см. gRFC и таблицу feature status).
- **Работает:** service discovery, subsets, `ROUND_ROBIN` балансировка, базовые политики `VirtualService` (маршрутизация), mTLS.
- **Ограничено:** auto-mTLS и PERMISSIVE не поддерживаются — на сервере задаётся `PeerAuthentication: STRICT`, на клиенте `tls.mode: ISTIO_MUTUAL`; fault injection, ретраи, зеркалирование, rewrite и `consistentHash` могут не поддерживаться.
- **Готовность:** серверу нужна аннотация `proxy.istio.io/config` с `holdApplicationUntilProxyStarts: true`, иначе gRPC-сервер стартует до готовности xDS-агента.
- **Health-check'и** при mTLS требуют отдельного порта или клиентских сертификатов.

Для продакшена предпочтительнее sidecar-модель (Envoy) или Ambient: полный набор функций меша и единый data plane. Proxyless интересен для gRPC-only сервисов, где критичен каждый мегабайт RAM сайдкара, — но это компромисс по функциональности и уровню экспериментальности.

### Сравнение реализаций (июль 2026)

| Критерий | Envoy (Istio 1.30+) | Linkerd-proxy (Linkerd 2.20+) |
| :--- | :--- | :--- |
| **Архитектура** | L4/L7-прокси на C++ с модульной архитектурой «filter chain». | Компактный L4/L7-прокси на Rust, фокус на безопасность и минимальный оверхед. |
| **Конфигурация** | Динамическая, через xDS (gRPC). Богатая и гибкая модель. | Централизованная через Control Plane. Минималистичная модель. |
| **Протоколы** | HTTP/1.x, HTTP/2, HTTP/3 (QUIC), gRPC, TCP, UDP, MongoDB, Redis. | HTTP/1.x, HTTP/2, gRPC, TCP. |
| **Расширяемость** | Высокая: кастомные фильтры, Lua, WebAssembly (WASM). | Ограниченная: философия «безопасных настроек по умолчанию». |
| **Ускорение** | eBPF SOCKMAP, XDP для Ingress. | eBPF-оптимизация, нативные сайдкары. |
| **Производительность** | ~2–5 мс задержка, 50–150 МБ RAM на под. | ~1–2 мс задержка, 10–40 МБ RAM на под. |

---

## Практические сценарии

### Внедрение (инъекция) sidecar в Kubernetes

#### Istio (Native Sidecar модель)

Включение автоматической инъекции через метку на namespace. Начиная с Istio 1.27 нативные сайдкары (init-контейнер с `restartPolicy: Always`) внедряются по умолчанию для всех подходящих подов (`ENABLE_NATIVE_SIDECARS=true`); это меняет `istio-proxy` из обычного контейнера в init-контейнер. Отключить для конкретной рабочей нагрузки можно аннотацией `sidecar.istio.io/nativeSidecar: "false"` (указывается на уровне Pod или в шаблоне пода).

```bash
kubectl label namespace my-app istio-injection=enabled
# → namespace/my-app labeled
```

Проверка конфигурации внедренного пода:
```bash
kubectl get pod my-app-pod -n my-app -o jsonpath='{.spec.initContainers[?(@.name=="istio-proxy")].restartPolicy}'
# → Always
```

**Управление готовностью прокси до старта приложения:**
- **Native Sidecar (K8s 1.33+):** основной контейнер не стартует, пока сайдкар не перейдёт в `Ready` (после `startupProbe`). Дополнительных настроек не требуется.
- **Классический контейнер (legacy):** чтобы удержать приложение до готовности Envoy, включается `holdApplicationUntilProxyStarts: true` (настройка `proxy.istio.io/config` на Pod или глобально в `MeshConfig`).
- **Проверка инъекции:** `istioctl x check-inject deploy/my-app -n my-app` — показывает, какой шаблон и политика применились (удобно при работе с ревизиями `istio.io/rev`).

#### Linkerd

Аннотация на уровне Deployment. В Linkerd 2.20 нативные сайдкары переведены из Beta в GA и стали типом инъекции по умолчанию (прокси внедряется как init-контейнер с `restartPolicy: Always`). Для возврата к классической модели используйте Helm-значение `proxy.nativeSidecar: false` или аннотацию `config.linkerd.io/proxy-enable-native-sidecar: "false"` на уровне пода/Deployment.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  annotations:
    linkerd.io/inject: enabled
spec:
  template:
    spec:
      containers:
      - name: app
        image: my-app:latest
```

Проверка состояния инъекции:
```bash
linkerd check -n my-app
# → Status: success

kubectl get pods -n my-app -o jsonpath='{.items[*].spec.initContainers[*].name}'
# → linkerd-proxy (по умолчанию в Linkerd 2.20+ инжектируется как Native Sidecar)
```

Ручная инъекция сайдкара в манифест (без аннотаций и без включённой автоинъекции):
```bash
kubectl get deploy my-app -o yaml | linkerd inject - | kubectl apply -f -
```

### Диагностика и отладка трафика

#### Envoy (Istio / Gateway API)

Просмотр текущих эндпоинтов (endpoints) для приложения:
```bash
istioctl proxy-config endpoints deploy/my-app -n my-app
# → ENDPOINT             STATUS  CLUSTER
# → 10.244.0.10:8080    HEALTHY out.my-app.svc.cluster.local
```

Получение базовой конфигурации (bootstrap) для проверки настроек администрирования:
```bash
istioctl proxy-config bootstrap deploy/my-app -n my-app
```

Прямое обращение к административному интерфейсу Envoy (порт 15000):
```bash
kubectl exec -it my-app-pod -c istio-proxy -- curl http://127.0.0.1:15000/stats | grep upstream_rq_2xx
# → cluster.outbound|8080||my-app.svc.cluster.local.upstream_rq_2xx: 150
```

Просмотр слушателей (listeners) и цепочек фильтров:
```bash
istioctl proxy-config listener deploy/my-app --port 8080 -o json
```

Проверка статуса синхронизации конфигурации с Control Plane:
```bash
istioctl proxy-status
# → NAME CDS LDS EDS RDS
# → my-app-pod SYNCED SYNCED SYNCED SYNCED
```

#### Linkerd

Получение статистики по ресурсам в реальном времени:
```bash
linkerd viz stat deploy -n my-app
# → NAME     MESHED  SUCCESS      RPS  P99_LATENCY
# → my-app      1/1  100.00%    10rps          5ms
```

Топ живых запросов (аналог `top` по RPS и latency):
```bash
linkerd viz top deploy/my-app -n my-app
```

Глубокая диагностика трафика (tap):
```bash
linkerd viz tap deploy/my-app -n my-app
# → req id=0:1 proxy=in src=10.244.1.5:45678 dst=10.244.1.10:8080 method=GET path=/api/v1
```

Открыть веб-дашборд Linkerd (требуется установленный linkerd-viz):
```bash
linkerd viz dashboard
```

### Управление конфигурацией прокси без перезапуска пода

Envoy в sidecar-режиме поддерживает динамическое обновление конфигурации через xDS. Это позволяет применять изменения маршрутизации, политик и кластеров без перезапуска контейнера приложения.

#### Принудительная перезагрузка конфигурации (Istio)

```bash
# Применение изменений VirtualService/DestinationRule/Sidecar:
kubectl apply -f my-rules.yaml

# Проверка, что istioctl получил и отправил дельту:
istioctl proxy-status
# → my-app-pod  SYNCED  ...  lastPushTime: 2026-09-18T16:00:00Z

# Если по какой-то причине дельта не отправлена (например, изменён не triggers-полe), 
# можно принудительно перезапустить прокси через rollout:
kubectl rollout restart deployment/my-app -n my-app
```

#### Прямое обновление через Envoy Admin API (только для отладки)

```bash
# Получение текущего config dump (полный конфиг Envoy):
kubectl exec -it my-app-pod -c istio-proxy -- curl -s http://127.0.0.1:15000/config_dump | jq '.configs[0].dynamic_active_clusters' | less

# Принудительный drain и graceful shutdown прокси (для тестирования):
kubectl exec -it my-app-pod -c istio-proxy -- curl -s http://127.0.0.1:15000/healthcheck/fail
# Прокси перестаёт получать трафик, но остаётся работать для drain существующих соединений.
```

#### Access Logs: включение и анализ

По умолчанию Istio может не писать access-логи в stdout. Для отладки маршрутизации включите их через Telemetry API:

```yaml
apiVersion: telemetry.istio.io/v1alpha1
kind: Telemetry
metadata:
  name: enable-access-logging
  namespace: my-app
spec:
  accessLogging:
  - providers:
    - name: envoy
```

После применения проверьте логи:
```bash
kubectl logs my-app-pod -c istio-proxy -n my-app | grep "my-service"
# → [2026-09-18T16:00:00.000Z] "GET /api/v1 HTTP/1.1" 200 - "-" 0 1234 5 2 "-" "curl/8.0" "my-service.prod.svc.cluster.local:8443" outbound|8443||my-service.prod.svc.cluster.local - 10.244.1.5:8080 10.244.1.10:8443 2026-09-18T16:00:00.000Z 2026-09-18T16:00:00.000Z my-app-pod.my-app.svc.cluster.local
```

Поля access-лога Envoy:
| Поле | Значение |
| :--- | :--- |
| `method` | HTTP-метод (GET, POST) |
| `path` | URI запроса |
| `upstream_cluster` | Имя кластера (сервиса назначения) |
| `upstream_host` | Эндпоинт (IP:port), к которому был направлен запрос |
| `response_code` | HTTP-код ответа (200, 503, 502 и т.д.) |
| `duration` | Время обработки в миллисекундах |
| `x_forwarded_for` | Исходный IP клиента (если прошёл через ingress) |

#### Отключение инъекции для конкретной рабочей нагрузки

Иногда требуется исключить конкретный Deployment или Pod из mesh (например, legacy-приложение без Readiness Probe или Job с одноразовым выполнением).

```bash
# Отключение на уровне Pod/Deployment (Istio):
kubectl patch deployment my-app -n my-app -p '{"spec":{"template":{"metadata":{"annotations":{"sidecar.istio.io/inject":"false"}}}}}'
# → deployment.apps/my-app patched

# Отключение на уровне namespace (откат):
kubectl label namespace my-app istio-injection-
```

После отключения инъекции необходимо перезапустить поды:
```bash
kubectl rollout restart deployment/my-app -n my-app
# → deployment.apps/my-app restarted
```

**Важно:** при отключении инъекции убедитесь, что `PeerAuthentication` в неймспейсе не в режиме `STRICT`, иначе трафик от этого пода к мешеным сервисам будет отклоняться.

### Диагностика производительности прокси

#### Сбор метрик Envoy через admin-интерфейс

```bash
# Общие счётчики:
kubectl exec -it my-app-pod -c istio-proxy -- curl -s http://127.0.0.1:15000/stats | grep -E "cluster\.|listener\.|http\.|connection\."

# Метрики конкретного кластера (upstream):
kubectl exec -it my-app-pod -c istio-proxy -- curl -s http://127.0.0.1:15000/stats | grep "cluster.outbound|8080||my-service"
# → cluster.outbound|8080||my-service.prod.svc.cluster.local.upstream_rq_total: 1500
# → cluster.outbound|8080||my-service.prod.svc.cluster.local.upstream_rq_5xx: 12
# → cluster.outbound|8080||my-service.prod.svc.cluster.local.upstream_cx_connect_timeout: 3

# Пул соединений:
kubectl exec -it my-app-pod -c istio-proxy -- curl -s http://127.0.0.1:15000/stats | grep "cx_"
# → cluster.outbound|8080||my-service.prod.svc.cluster.local.upstream_cx_total: 500
# → cluster.outbound|8080||my-service.prod.svc.cluster.local.upstream_cx_active: 5
```

#### Траблшутинг задержек (Latency)

```bash
# Сбор histograms (если включены в bootstrap):
kubectl exec -it my-app-pod -c istio-proxy -- curl -s http://127.0.0.1:15000/stats?format=histogram | grep "outbound|8080"
# → outbound|8080||my-service.prod.svc.cluster.local: P50=2ms,P99=15ms,P999=50ms

# Проверка listener-ов на наличие дублирующих filter chains:
istioctl proxy-config listener deploy/my-app -n my-app -o json | jq '.dynamicListeners[] | select(.name|contains("inbound"))'
```

### Отладка сетевых проблем

#### Istio

Анализ маршрутов (routes):
```bash
istioctl proxy-config route deploy/my-app -n my-app
```

Проверка корректности конфигурации всего неймспейса:
```bash
istioctl analyze -n my-app
# → Info [IST0102] The namespace is not annotated with istio-injection=enabled
```

Логирование запросов (Access Logs) — включение через Telemetry API или настройку прокси:
```bash
kubectl logs my-app-pod -c istio-proxy -n my-app | grep "GET /health"
```

#### Linkerd

Трассировка ошибок (только запросы с 5xx кодами):
```bash
linkerd viz tap deploy/my-app --error -n my-app
```

Просмотр логов прокси-контейнера:
```bash
kubectl logs my-app-pod -c linkerd-proxy -n my-app
```

### Режим Ambient (Istio 1.30+)

Диагностика в режиме без sidecar через Ztunnel и Waypoint Proxy:

```bash
# Список Waypoint-прокси в неймспейсе
istioctl waypoint list -n my-app

# Проверка сетевого состояния пода (Ambient)
istioctl ztunnel-config workload my-app-pod -n my-app
# → Показывает: ztunnel (L4), waypoint (L7), политики, сертификаты
# → Показывает: ztunnel (L4), waypoint (L7), политики, сертификаты

# Логи Ztunnel (DaemonSet в istio-system)
kubectl logs -n istio-system -l app=ztunnel
```

### Валидация внедрения и проверка работоспособности

После включения инъекции необходимо провести комплексную проверку, что прокси не только присутствует в поде, но и корректно перехватывает трафик, синхронизирует конфигурацию и устанавливает mTLS.

#### 1. Проверка наличия и типа сайдкара

```bash
# Istio: проверка наличия istio-proxy в initContainers (Native Sidecar)
kubectl get pod my-app-pod -n my-app -o jsonpath='{.spec.initContainers[?(@.name=="istio-proxy")].restartPolicy}'
# → Always

# Linkerd: проверка наличия linkerd-proxy
kubectl get pods -n my-app -o jsonpath='{.items[*].spec.initContainers[*].name}'
# → linkerd-proxy

# Альтернативно: проверка через describe pod (должен быть 2/2 Ready или 1/1 для native sidecar)
kubectl describe pod my-app-pod -n my-app | grep -A 3 "Containers:"
```

#### 2. Проверка статуса синхронизации xDS

```bash
# Istio: статус синхронизации всех прокси в кластере
istioctl proxy-status
# → NAME                                      CDS     LDS     EDS     RDS
# → my-app-pod.my-app.svc.cluster.local       SYNCED  SYNCED  SYNCED  SYNCED

# Если статус не SYNCED — проверьте доступность istiod:
kubectl get pods -n istio-system -l app=istiod
# → istiod-6d4f8b9b5-x2abc   1/1     Running   0          2d

# Проверка логов istiod на предмет ошибок доставки конфигурации:
kubectl logs -n istio-system -l app=istiod | grep -i "xds\|push"
```

#### 3. Проверка перехвата трафика (iptables/eBPF)

```bash
# Вход в контейнер приложения и проверка правил iptables/nftables:
kubectl exec -it my-app-pod -c app -- iptables -t nat -L -n | grep 15001
# или для nftables:
kubectl exec -it my-app-pod -c app -- nft list ruleset | grep 15001

# Проверка, что исходящий трафик идёт через localhost:15001 (Envoy outbound):
kubectl exec -it my-app-pod -c app -- curl -v http://127.0.0.1:15001
# Должен вернуться 200 или ответ от Envoy admin (в зависимости от конфигурации)

# Проверка DNS: Istio записывает сервисы в /etc/hosts или использует DNS через proxy:
kubectl exec -it my-app-pod -c app -- cat /etc/hosts | grep my-service
```

#### 4. Проверка mTLS

```bash
# Включение access-логов временно для проверки шифрования:
kubectl exec -it my-app-pod -c istio-proxy -- curl -s http://127.0.0.1:15000/logging?level=info

# Отправка запроса между сервисами и проверка, что трафик зашифрован:
kubectl exec -it my-app-pod -c app -- curl -v https://my-service.prod.svc.cluster.local:8443/api/v1/status
# В ответе заголовков должен отсутствовать downgrade на plaintext (если PeerAuthentication: STRICT)

# Проверка через tcpdump (вside контейнера приложения):
kubectl exec -it my-app-pod -c app -- tcpdump -i any -nn port 8080
# В режиме STRICT трафик между подами должен идти через port 15001 (Envoy), а не напрямую на порт приложения.
```

#### 5. Проверка через istioctl analyze

```bash
# Полный анализ конфигурации меша в неймспейсе:
istioctl analyze -n my-app
# → Info [IST0102] The namespace is not annotated with istio-injection=enabled
# → Warning [IST0162] Pod has no readinessProbe; proxy may receive traffic before app is ready

# Проверка конкретного пода на корректность инъекции:
istioctl x check-inject deploy/my-app -n my-app
# → Pod has sidecar injected: istio-proxy (native: true)
```

### Специальные рабочие нагрузки (Job, CronJob, Headless)

#### Job и CronJob с Native Sidecar

Обычные (классические) sidecar-контейнеры блокируют завершение Job, так как продолжают работать после выхода основного контейнера. Native Sidecar решает эту проблему: контроллер Job ожидает завершения всех init-контейнеров с `restartPolicy: Always` после успешного выполнения основных контейнеров.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: data-migration
spec:
  template:
    spec:
      initContainers:
      - name: istio-proxy
        image: docker.io/istio/proxyv2:1.30.0
        restartPolicy: Always  # Native Sidecar: не блокирует завершение Job
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 128Mi
      containers:
      - name: migration
        image: my-migration:1.0
        command: ["python", "migrate.py"]
```

**Проверка корректного завершения:**
```bash
kubectl get job data-migration
# → NAME           COMPLETIONS   DURATION   AGE
# → data-migration 1/1           2m         5m

kubectl get pods -l job-name=data-migration
# → NAME                     READY   STATUS      RESTARTS   AGE
# → data-migration-abc123    0/1     Completed   0          5m
# Pod Completed, а не Terminating — Native Sidecar корректно завершился.
```

#### Headless Services и sidecar

При использовании Headless Service (`clusterIP: None`) сайдкар-прокси обрабатывает DNS-запросы иначе:
- Envoy получает полный список эндпоинтов через EDS, минуя кластеризацию Kubernetes.
- Для StatefulSet с headless service каждый под получает уникальный DNS-запись (`pod-0.service.namespace.svc.cluster.local`), и сайдкар корректно маршрутизирует трафик напрямую к эндпоинту.
- Важно: при использовании `TrafficPolicy` с `subset` в DestinationRule убедитесь, что headless-сервис имеет соответствующие метки на подах, иначе Envoy вернёт `No Healthy Upstream`.

### Отладка типичных ошибок

#### Ошибка 1: Empty reply from server / UH (No Healthy Upstream)

**Причина:** Сервис назначения отсутствует в списке `egress.hosts` ресурса `Sidecar` в Istio, либо эндпоинт не Ready.

```bash
# Проверка кластеров, известных прокси:
istioctl proxy-config clusters deploy/my-app -n my-app
# Если нужный сервис отсутствует в списке — проверьте ресурс Sidecar:

kubectl get sidecar default -n my-app -o yaml
# Убедитесь, что нужный неймспейс/сервис добавлен в egress.hosts

# Проверка состояния эндпоинтов:
kubectl get endpoints my-service -n my-app
# → NAME          ENDPOINTS          AGE
# → my-service    10.244.0.10:8080   5m
```

**Решение:** добавьте недостающий неймспейс в `egress.hosts` ресурса `Sidecar` или убедитесь, что эндпоинт имеет готовый `readinessProbe`.

#### Ошибка 2: Connection reset by peer

**Причина:** Сработала политика `PeerAuthentication: STRICT` на стороне получателя, а отправитель не имеет сайдкара или использует plain-text.

```bash
# Проверка политик mTLS в неймспейсе:
kubectl get peerauthentication --all-namespaces
# → NAMESPACE   NAME      MODE
# → my-app      default   STRICT

# Проверка, что отправитель имеет инъекцию:
kubectl get pods -n source-ns -o jsonpath='{.items[*].spec.initContainers[*].name}'
# Если istio-proxy отсутствует — включите инъекцию для source-ns
```

**Решение:** либо включите инъекцию для отправителя, либо переведите `PeerAuthentication` в `PERMISSIVE` (не рекомендуется для продакшена).

#### Ошибка 3: Прокси не синхронизируется (proxy-status показывает SYNCED с задержкой или UNAVAILABLE)

**Причина:** `istiod` недоступен, перегружен или между Control Plane и прокси есть сетевая разрыв.

```bash
# Проверка доступности istiod из пода:
kubectl exec -it my-app-pod -c istio-proxy -- curl -s http://istiod:15014/healthz/ready
# → 200 OK

# Проверка времени синхронизации:
istioctl proxy-status
# → my-app-pod  SYNCED  ...  lastPushTime: 2026-09-18T15:30:00Z

# Если lastPushTime значительно старше текущего времени — проверьте логи istiod:
kubectl logs -n istio-system -l app=istiod --tail=100 | grep -i "push\|xds\|error"
```

**Решение:** проверьте ресурсы `istiod` (CPU/memory), убедитесь в отсутствии NetworkPolicy между `istiod` и подами, проверьте целостность сертификатов CA.

#### Ошибка 4: Зависание Pod при удалении (Terminating) из-за sidecar

**Причина:** Native Sidecar не завершается вовремя, или `preStop` хук блокирует завершение.

```bash
# Проверка состояния контейнеров:
kubectl get pod my-app-pod -o jsonpath='{.status.containerStatuses[*].state}'
# Если основной контейнер Terminated, а sidecar Running — проблема с завершением

# Проверка terminationGracePeriodSeconds:
kubectl get pod my-app-pod -o jsonpath='{.spec.terminationGracePeriodSeconds}'
# → 30 (по умолчанию)
```

**Решение:** увеличьте `terminationGracePeriodSeconds` до 60 секунд для долгоживущих соединений, убедитесь, что Envoy корректно обрабатывает `SIGTERM` (не переопределён `ENTRYPOINT` с игнорированием сигналов).

#### Ошибка 5: Elevated resource usage / OOMKilled

**Причина:** Сайдкар потребляет больше ресурсов, чем ожидалось, из-за большого количества сервисов в mesh или неоптимальной конфигурации.

```bash
# Проверка фактического потребления:
kubectl top pod my-app-pod -c istio-proxy
# → NAME                     CPU    MEMORY
# → my-app-pod   500m      250Mi

# Если proxy-config clusters показывает 1000+ кластеров — используйте ресурс Sidecar:
istioctl proxy-config clusters deploy/my-app -n my-app | wc -l
# → 1200
```

**Решение:** создайте ресурс `Sidecar` с ограниченным `egress.hosts` (см. [Конфигурация Sidecar в Istio](./istio-sidecar-configuration.md)), включите `holdApplicationUntilProxyStarts: false` если приложение не требует гарантированной готовности прокси, уменьшите `metadata_exchange` interval.

---

## Операции и команды

### Управление инъекцией sidecar

| Действие | Команда | Примечание |
| :--- | :--- | :--- |
| Включить автоинъекцию (Istio, namespace) | `kubectl label namespace <ns> istio-injection=enabled` | С 1.27 нативные сайдкары по умолчанию |
| Включить автоинъекцию (Linkerd, namespace) | `kubectl annotate namespace <ns> linkerd.io/inject=enabled` | С 2.20 нативные сайдкары по умолчанию |
| Отключить инъекцию (Istio, pod) | `kubectl annotate pod <pod> sidecar.istio.io/inject-`; или `kubectl patch deploy <name> -p '{"spec":{"template":{"metadata":{"annotations":{"sidecar.istio.io/inject":"false"}}}}}}'` | Перезапустить поды после |
| Отключить нативный сайдкар (Istio) | `kubectl annotate pod <pod> sidecar.istio.io/nativeSidecar="false"` | Подменяет `ENABLE_NATIVE_SIDECARS` |
| Отключить нативный сайдкар (Linkerd) | `kubectl annotate namespace <ns> config.linkerd.io/proxy-enable-native-sidecar="false"`; или `helm upgrade linkerd-control-plane linkerd/control-plane --set proxy.nativeSidecar=false` |  |

### Диагностика статуса

| Команда | Что проверяет |
| :--- | :--- |
| `istioctl proxy-status` | Синхронизация xDS (CDS/LDS/EDS/RDS) для sidecar-подов |
| `istioctl ztunnel-config workloads -n <ns>` | Статус амбиентных workloads (zTunnel) |
| `istioctl waypoint list -n <ns>` | Список waypoint-прокси в неймспейсе |
| `istioctl proxy-config endpoints deploy/<name> -n <ns>` | Эндпоинты, известные прокси |
| `istioctl proxy-config bootstrap deploy/<name> -n <ns>` | Bootstrap-конфигурация (admin ports, xDS server) |
| `istioctl proxy-config clusters deploy/<name> -n <ns>` | Upstream-кластеры, известные прокси |
| `istioctl proxy-config listener deploy/<name> -n <ns>` | Слушатели и filter chains |
| `istioctl x check-inject deploy/<name> -n <ns>` | Проверка применения шаблона инъекции |
| `istioctl analyze -n <ns>` | Валидация конфигурации меша |

### Мониторинг и метрики

| Метрика | Источник | Что мониторить |
| :--- | :--- | :--- |
| `envoy_cluster_upstream_rq_total` | Prometheus | Общее количество запросов к upstream |
| `envoy_cluster_upstream_rq_5xx` | Prometheus | Ошибки upstream |
| `envoy_cluster_upstream_cx_active` | Prometheus | Активные соединения |
| `envoy_cluster_upstream_cx_connect_timeout` | Prometheus | Таймауты подключения |
| `istio_requests_total` | Prometheus | RPS по сервисам (через telemetry) |
| `istio_request_duration_milliseconds` | Prometheus | P50/P90/P99 latency |
| `istio_tcp_connections_closed_total` | Prometheus | Частота закрытия соединений |

### Очистка

После удаления workloads из mesh необходимо очистить ресурсы и конфигурацию:

```bash
# 1. Отключить автоинъекцию (Istio):
kubectl label namespace my-app istio-injection-

# 2. Отключить автоинъекцию (Linkerd):
kubectl annotate namespace my-app linkerd.io/inject-

# 3. Перезапустить поды для удаления сайдкара:
kubectl rollout restart deployment -n my-app

# 4. Удалить аннотации нативного сайдкара (если вручную задавались):
kubectl annotate pod <pod> sidecar.istio.io/nativeSidecar- -n my-app

# 5. Проверить, что прокси больше не присутствует в подах:
kubectl get pods -n my-app -o jsonpath='{.items[*].spec.initContainers[*].name}'
# → (пусто, если не включено)
```

Для окончательного удаления Istio из кластера:
```bash
istioctl uninstall --purge
kubectl delete namespace istio-system
```

## Дополнительная информация

### Сравнение производительности (2026)

| Метрика | Envoy (Sidecar) | Linkerd-proxy | Ztunnel (Ambient L4) | Waypoint (Ambient L7) |
| :--- | :--- | :--- | :--- | :--- |
| **Задержка (P50)** | ~3–5 мс | ~1–2 мс | < 0.5 мс | ~2–4 мс |
| **CPU (на под)** | 50–500 mCPU | 20–200 mCPU | ~20 mCPU (shared) | 100–300 mCPU |
| **RAM (на под)** | 50–150 МБ | 10–40 МБ | ~50 МБ (node) | 100–250 МБ |
| **Старт (Native)** | ~0.5–1 сек | ~0.3–0.6 сек | N/A | ~1–2 сек |

### Лучшие практики эксплуатации

1. **Ресурсные квоты:** всегда устанавливать `requests` и `limits` для сайдкаров. В Istio 1.31 Envoy требует ~0.20 vCPU и 60MB RAM на 1,000 RPS. Для Native Sidecar используйте `requests.cpu: 50m` и `requests.memory: 64Mi` как минимум; лимиты — `cpu: 200m`, `memory: 128Mi`.
2. **Scoping конфигурации:** использовать ресурс `Sidecar` (Istio) для ограничения списка сервисов, о которых знает прокси. Это критично для снижения потребления RAM в больших кластерах. Подробнее в [Конфигурации Sidecar в Istio](./istio-sidecar-configuration.md).
3. **eBPF Acceleration:** при использовании CNI (Cilium, Calico VPP) в амбиентном режиме, включайте eBPF redirect для эффективного перенаправления трафика в Ztunnel. Для SOCKMAP-ускорения требует `--define=sockmap=enabled` при сборке Envoy и eBPF-объект; экспериментальная функция.
4. **Безопасность:** ограничивать доступ к административному порту Envoy (15000) и Linkerd (4191) через NetworkPolicies. Разрешайте доступ только из системных неймспейсов и от SRE-инструментов.
5. **Телеметрия:** отключать детальные Access Logs в продакшене, используя `Telemetry` API для выборочного логирования только ошибок и медленных запросов (latency > 1s).
6. **Native Sidecar для Jobs/CronJobs:** всегда используйте нативный сайдкар (`restartPolicy: Always` в `initContainers`) для рабочих нагрузок с завершаемым выполнением. Обычные sidecar-контейнеры блокируют завершение Job.
7. **startupProbe для Native Sidecar:** всегда добавляйте `startupProbe` (или `readinessProbe`) в Native Sidecar, чтобы гарантировать готовность прокси до старта приложения. Это предотвращает race conditions и 5xx-ошибки при холодном старте.
8. **holdApplicationUntilProxyStarts:** включайте эту настройку (`proxy.istio.io/config`) для приложений, которые отправляют трафик сразу после старта (например, health-check внешних систем). Для пакетной обработки (batch jobs) настройку можно отключить для ускорения запуска.
9. **Валидация после изменений:** после изменения ресурсов `Sidecar`, `VirtualService` или `DestinationRule` выполняйте `istioctl analyze` и `istioctl proxy-status` для подтверждения распространения конфигурации.
10. **Мониторинг ресурсов прокси:** настройте алерты на `istio_agent_go_goroutines`, `envoy_cluster_upstream_cx_active` и `envoy_server_memory_allocated` для раннего обнаружения утечек памяти или дедлоков в фильтрах.

### Крайние случаи и ограничения

1. **hostNetwork: true:** поды с включённым `hostNetwork` используют сетевой стек узла напрямую. iptables/eBPF-редирект в этом случае не работает корректно — трафик не попадает в сайдкар. Istio помечает такие поды как `sidecar.istio.io/inject: "false"` по умолчанию.
2. **Пorted Services с нестандартными портами:** убедитесь, что порты приложения совпадают с портами в `Service` и `DestinationRule`. При несовпадении Envoy может вернуть `503 Service Unavailable` с причиной `no healthy upstream`.
3. **StatefulSet с volumeClaimTemplates:** при rolling update StatefulSet Native Sidecar завершается после основного контейнера, но перед отключением PVC. Это гарантирует корректный drain соединений к БД.
4. **Изменение образа прокси (proxyv2):** обновление образа Envoy требует перезапуска подов (`kubectl rollout restart`). Control Plane не выполняет hot-update бинарного файла прокси — только конфигурации через xDS.
5. **Ограничения nftables:** в ядрах Linux < 5.13 nftables поддерживается ограниченно. Istio 1.27+ автоматически определяет поддержку и выбирает iptables как fallback. Проверить можно через: `kubectl get cm istio-cni-config -n istio-system -o jsonpath='{.data.values}' | grep nftables`.
6. **Совместная работа с другими CNI-плагинами:** при использовании Cilium в режиме eBPF-редирек для Istio убедитесь, что `istio-cni` не конфликтует с Cilium CNI. Оба плагина могут устанавливать правила, что приводит к двойному редиректу и задержкам. Рекомендуется использовать либо Cilium-native Istio integration, либо отключить `istio-cni-node`.
7. **Взаимодействие с ServiceEntry:** `ServiceEntry` расширяет видимость меша на внешние сервисы. Если ресурс `Sidecar` ограничивает `egress.hosts` списком `./*` (только текущий неймспейс), доступ к `ServiceEntry` из других неймспейсов будет заблокирован с ошибкой `No Healthy Upstream`.
8. **Liveness Probe и sidecar:** `livenessProbe` приложения должна проверять порт приложения (`localhost:8080`), а не `localhost:15001` (порт Envoy). Иначе при перезагрузке Envoy probe будет падать, и Kubelet перезапустит приложение.
9. **Переполнение inode в emptyDir:** если sidecar использует `emptyDir` для shared volume (например, для логов), убедитесь, что установлен `medium: Memory` для tmpfs, иначе при переполнении дига пода логи перестанут писаться.

### Актуальность и ссылки

- **Istio 1.30.x:** Ambient Mesh стабилен (GA с 1.24), нативные сайдкары включены по умолчанию (с 1.27). Поддержка Kubernetes 1.32–1.36.
- **Envoy 1.40.x:** расширяемость через API `TrafficExtension` (Istio 1.30+) заменяет устаревший `WasmPlugin`; поддержка Lua и WebAssembly (WASM) для кастомной обработки трафика на L4/L7.
- **Linkerd 2.20+:** нативные сайдкары по умолчанию, HAZL с учётом rate-limit-ответов (429) и снижение потребления памяти Control Plane.

**См. также:**
- [Архитектура Istio](./istio_architecture.md)
- [Конфигурация Sidecar в Istio](./istio-sidecar-configuration.md)
- [Политики безопасности Istio](./istio-security-policies.md)
- [Сравнение Istio и Linkerd](./istio_vs_linkerd.md)
- [Паттерны Sidecar в Kubernetes](../Kubernetes/Base/Pod/pod_sidecar_patterns.md)
- [Ограничение скорости (Rate Limiting) в Istio](./istio_rate_limiting.md)
- [Интеграция виртуальных машин (VM Workloads) в Istio](./istio_vm_workloads.md)

Документация: [Envoy Proxy](https://www.envoyproxy.io/docs), [Linkerd Docs](https://linkerd.io/docs/), [Istio Ambient](https://istio.io/latest/docs/ambient/).
