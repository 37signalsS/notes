# Анализ Service Mesh (mTLS, sidecar) в Wireshark

> **SSoT:** Концепции Service Mesh — в **[Service Mesh Concepts](../../../Service_Mesh/service_mesh_concepts.md)**. Sidecar proxy — в **[Proxy Sidecar](../../../Service_Mesh/proxy_sidecar.md)**. Архитектура Istio — в **[Istio Architecture](../../../Service_Mesh/istio_architecture.md)**. TLS расшифровка — в **[Методы расшифровки TLS](./tls_decryption_methods.md)**. Концепции захвата — в **[Основные концепции](./core_concepts.md)**.

## Определения

**Service Mesh** — инфраструктурный слой для управления служебным (service-to-service) трафиком в микросервисной архитектуре. Реализуется через sidecar-прокси (Envoy, linkerd-proxy) или sidecar-less подход (Ztunnel/Ambient Mesh).

**Sidecar Proxy** — контейнер-прокси (Envoy), автоматически инжектируемый в каждый Pod. Перехватывает весь входящий и исходящий трафик через iptables/nftables или eBPF (SOCKMAP), обеспечивая mTLS, маршрутизацию, retry, circuit breaking и observability.

**mTLS (Mutual TLS)** — обоюдная аутентификация через сертификаты. Каждый sidecar имеет X.509 SVID (SPIFFE Verifiable Identity Document), выданный istiod/linkerd-ca. Шифрование East-West трафика между подами.

**Ztunnel** — sidecar-less прокси (Rust, DaemonSet) в Istio Ambient Mesh. Работает на L4, обеспечивая mTLS и базовую маршрутизацию без overhead sidecar-контейнера. Задержка: <0.5 мс L4.

**Waypoint Proxy** — L7 прокси (Envoy) в Istio Ambient Mesh, разворачиваемый per-namespace или per-service. Обеспечивает HTTP/gRPC маршрутизацию, retry, circuit breaking. Задержка: ~2-4 мс L7.

**HBONE (HTTP-Based Overlay Network Environment)** — транспортный протокол Istio Ambient Mesh. Инкапсулирует TCP-трафик внутри HTTP/2 CONNECT для прохождения через промежуточные узлы с сохранением mTLS.

**Envoy** — L4/L7 прокси, используемый как sidecar в Istio и Linkerd. Предоставляет xDS API для динамической конфигурации, admin интерфейс на порту 15090 (метрики) и 15020 (health).

**Traffic Interception** — механизм перехвата трафика sidecar-прокси. В Istio: iptables REDIRECT/TPROXY или eBPF (SOCKMAP). В Linkerd: iptables nat/REDIRECT или eBPF.

## Quick-Start: Чек-лист анализа Service Mesh

| Шаг | Действие | Как проверить |
| :--- | :--- | :--- |
| **1** | Расшифровать mTLS | `SSLKEYLOGFILE` sidecar'а или захват на `lo` |
| **2** | Найти sidecar-задержки | `tcp.time_delta` между app и proxy |
| **3** | Проверить RST/GOAWAY | `http2.type == 3 \|\| http2.type == 7` |
| **4** | Найти 503/502 | `http2.headers.status == 503 \|\| 502` |
| **5** | Проверить cert rotation | `tls.handshake.type == 11` (Certificate) |
| **6** | Найти Envoy errors | `envoy.cluster.*` метрики или access logs |

## Основные концепции

### Методы захвата трафика Service Mesh

| Метод | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Захват на `lo` внутри пода** | Трафик до шифрования sidecar | Анализ plaintext приложения |
| **`kubectl sniff` с расшифровкой** | Захват через ksniff + SSLKEYLOGFILE | Глубокий анализ L7 |
| **Envoy access logs** | Логи sidecar-прокси | Быстрая диагностика HTTP-ошибок |
| **Envoy admin interface** | `curl localhost:15090/stats` | Метрики в реальном времени |
| **eBPF (Inspektor Gadget)** | Захват на уровне ядра | Когда sidecar недоступен |

### Захват трафика на loopback-интерфейсе

Самый простой способ увидеть трафик приложения до шифрования sidecar:

```bash
# Захват на loopback внутри пода (plaintext)
kubectl exec -it <pod> -c app -- \
  tshark -i lo -f "tcp port 8080" -w /tmp/app_traffic.pcapng

# Копирование дампа
kubectl cp <pod>:/tmp/app_traffic.pcapng ./app_traffic.pcapng

# Анализ в Wireshark
wireshark app_traffic.pcapng
```

**Важно:** На интерфейсе `lo` виден только трафик между приложением и sidecar на localhost. Трафик между подами (East-West) зашифрован и виден только на внешнем интерфейсе.

### Захват зашифрованного mTLS трафика

```bash
# Способ 1: Расшифровка через SSLKEYLOGFILE sidecar
# Настройка SSLKEYLOGFILE в sidecar (Envoy):
# В Istio: через EnvoyFilter или ProxyConfig
kubectl exec -it <pod> -c istio-proxy -- \
  tshark -i eth0 -f "tcp port 443" -w /tmp/mesh_traffic.pcapng

# Способ 2: Захват на хосте + расшифровка
sudo tshark -i eth0 -f "tcp port 443" -w /tmp/host_traffic.pcapng
# Затем расшифровка через SSLKEYLOGFILE

# Способ 3: Через ksniff с фильтрацией
kubectl sniff <pod> -n <namespace> -f "tcp port 80" -w http.pcapng
```

### Анализ задержек sidecar-прокси

```bash
# Задержка между приложением и sidecar (Envoy)
# Приложение отправляет данные → sidecar шифрует и отправляет наружу
# Анализ: delta между пакетами на lo и eth0

# tshark: задержка sidecar (Envoy → upstream)
tshark -r mesh_capture.pcapng -Y "tcp.port == 8080 && tcp.len > 0" \
  -T fields -e frame.time_relative -e tcp.time_delta -e ip.src -e ip.dst

# Норма: sidecar overhead < 1 мс (L4), < 4 мс (L7)
# Если > 5 мс → проблема с Envoy конфигурацией или ресурсами
```

### Envoy метрики через admin interface

```bash
# Все метрики Envoy (включая RED: Rate, Errors, Duration)
kubectl exec -it <pod> -c istio-proxy -- \
  curl -s localhost:15090/stats | grep -E "upstream_rq|downstream_rq"

# Ключевые метрики:
# envoy_cluster_upstream_rq_total          → общий запросов
# envoy_cluster_upstream_rq_xx             → по кодам (2xx, 3xx, 4xx, 5xx)
# envoy_cluster_upstream_rq_retry          → retry-попытки
# envoy_cluster_upstream_cx_connect_ms     → время установки соединения
# envoy_cluster_upstream_rq_time_bucket    → распределение задержек

# envoy_cluster_upstream_rq_time_bucket{le="0.5"}  → 50% запросов < 500мс
# envoy_cluster_upstream_rq_time_bucket{le="1.0"}  → 90% запросов < 1с
# envoy_cluster_upstream_rq_time_bucket{le="5.0"}  → 99% запросов < 5с

# Errors (5xx)
kubectl exec -it <pod> -c istio-proxy -- \
  curl -s localhost:15090/stats | grep "upstream_rq_5"
```

## Практические сценарии

### Сценарий 1: Диагностика 503 Service Unavailable

503 в Service Mesh чаще всего означает, что Envoy не может маршрутизировать запрос:

```bash
# Поиск 503 в Wireshark
tshark -r mesh.pcapng -Y "http2.headers.status == 503" -T fields \
  -e frame.number -e ip.src -e ip.dst -e http2.headers.path -e grpc.status

# Проверка envoy access logs
kubectl logs <pod> -c istio-proxy | grep "503"

# Типичные причины 503:
# 1. DestinationRule: trafficPolicy.tls.mode не совпадает с PeerAuthentication
# 2. Сервис не существует или не имеет эндпоинтов
# 3. Circuit breaker сработал (outlierDetection)
# 4. Retry policy исчерпал попытки
```

### Сценарий 2: Диагностика mTLS handshake failures

```bash
# TLS handshake в Service Mesh
tshark -r mesh.pcapng -Y "tls.handshake.type == 1 || tls.handshake.type == 2" \
  -T fields -e frame.number -e ip.src -e ip.dst \
  -e tls.handshake.type -e tls.handshake.extensions_server_name \
  -e tls.handshake.certificate_type

# Типы handshake:
# type 1 = ClientHello
# type 2 = ServerHello
# type 11 = Certificate
# type 12 = ServerKeyExchange
# type 14 = ServerHelloDone

# Поиск ошибок cert validation
tshark -r mesh.pcapng -Y "tls.alert_message" -T fields \
  -e frame.number -e tls.alert_message -e ip.src -e ip.dst

# TLS Alert коды:
# 42 = bad_certificate
# 43 = unsupported_certificate
# 44 = certificate_revoked
# 45 = certificate_expired
# 46 = certificate_unknown
# 48 = unknown_ca
```

### Сценарий 3: Анализ routing через VirtualService/DestinationRule

```bash
# Проверка weight-based routing
# Если 90% трафика идет на v1 и 10% на v2:
tshark -r mesh.pcapng -Y "http2.headers.path == /api/v1/resource" -T fields \
  -e ip.dst | sort | uniq -c | sort -rn

# Проверка retry policy
tshark -r mesh.pcapng -Y "tcp.analysis.retransmission && tcp.port == 80" -T fields \
  -e frame.number -e tcp.stream -e tcp.analysis.retransmission

# Проверка timeout (пакеты после таймаута)
tshark -r mesh.pcapng -Y "http2.type == 3 && http2.rst_stream.errorcode == 4" -T fields \
  -e frame.number -e http2.streamid
```

### Сценарий 4: Ambient Mesh — анализ Ztunnel и Waypoint

```bash
# Ztunnel (L4) трафик на хосте
sudo tshark -i eth0 -f "tcp port 15018" -w ztunnel_traffic.pcapng

# Waypoint (L7) трафик
kubectl exec -it <waypoint-pod> -- \
  tshark -i lo -f "tcp port 8080" -w waypoint_traffic.pcapng

# HBONE инкапсуляция (HTTP/2 CONNECT)
tshark -r ambient.pcapng -Y "http2.headers.method == CONNECT" -T fields \
  -e frame.number -e http2.headers.authority -e ip.src -e ip.dst
```

### Сценарий 5: Корреляция с Istioctl

```bash
# Proxy status
istioctl proxy-status

# Конфигурация envoy для конкретного пода
istioctl proxy-config routes <pod>
istioctl proxy-config clusters <pod>
istioctl proxy-config listeners <pod>

# Анализ конфигурации через dump
kubectl exec -it <pod> -c istio-proxy -- \
  pilot-agent request GET config_dump | python3 -m json.tool

# Проверка xDS sync status
kubectl exec -it <pod> -c istio-proxy -- \
  pilot-agent request GET stats | grep "xds"
```

## Дополнительная информация

### Влияние Service Mesh на задержки

| Компонент | L4 задержка | L7 задержка | Примечание |
| :--- | :--- | :--- | :--- |
| **Envoy sidecar** | 0.5-2 мс | 2-5 мс | Каждый hop (app→proxy) |
| **Ztunnel (Ambient)** | <0.5 мс | — | Только mTLS + L4 auth |
| **Waypoint (Ambient)** | — | 2-4 мс | L7 функции |
| **Linkerd-proxy** | 1-2 мс | — | Rust-based, легковесный |

### Sidecar vs Ambient Mesh: 비교

| Характеристика | Sidecar (Envoy) | Ambient (Ztunnel + Waypoint) |
| :--- | :--- | :--- |
| **Модель** | 1 Envoy на Pod | 1 Ztunnel на ноду + Waypoint на namespace |
| **Overhead CPU** | 0.5-1 core | <0.1 core (Ztunnel) |
| **Overhead Memory** | 40-60 МБ | <10 МБ (Ztunnel) |
| **L7 функции** | Да (в sidecar) | Только через Waypoint |
| **mTLS** | Да | Да (Ztunnel) |
| **Startup latency** | 2-5 сек (инъекция) | <1 сек |

### Типичные проблемы Service Mesh

| Проблема | Симптом в Wireshark | Фильтр | Решение |
| :--- | :--- | :--- | :--- |
| **mTLS mismatch** | TLS handshake alert | `tls.alert_message` | `PeerAuthentication: PERMISSIVE` |
| **503 No Route** | 503 после HEADERS | `http2.headers.status == 503` | Проверить VirtualService/DestinationRule |
| **Circuit Breaker** | 503 + outlier eject | `http2.headers.status == 503` | Увеличить `maxEjectionPercent` |
| **Retry Storm** | Много дублирующихся запросов | `tcp.analysis.retransmission` | Ограничить retry budget |
| **Sidecar overhead** | Задержки > 5 мс на `lo` | `tcp.time_delta > 0.005` | Перейти на Ambient Mesh |
| **GOAWAY Storm** | Много GOAWAY фреймов | `http2.type == 7` | Проверить graceful shutdown |
| **Cert Rotation** | TLS renegotiation | `tls.handshake.type == 11` | Это нормально (auto-rotation) |

### См. также
- **[Service Mesh Concepts](../../../Service_Mesh/service_mesh_concepts.md)** — основы Service Mesh
- **[Proxy Sidecar](../../../Service_Mesh/proxy_sidecar.md)** — Envoy, Ztunnel, injection
- **[Istio Architecture](../../../Service_Mesh/istio_architecture.md)** — архитектура Istio
- **[HTTP/2 и gRPC Analysis](./http2_grpc_analysis.md)** — анализ HTTP/2/gRPC в Wireshark
- **[Методы расшифровки TLS](./tls_decryption_methods.md)** — расшифровка mTLS
- **[eBPF Diagnostics Tools](./ebpf_diagnostics_tools.md)** — Inspektor Gadget, pwru
