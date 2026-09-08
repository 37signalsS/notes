# Глубокая диагностика Gateway API

## Определения

**Envoy Admin Interface** — HTTP API Envoy Proxy (порт 19000 по умолчанию), предоставляющий доступ к конфигурации, статистике и кластерам в runtime. Основной инструмент диагностики Envoy-based Gateway API контроллеров.

**config_dump** — endpoint Envoy Admin Interface, возвращающий полную текущую конфигурацию прокси в JSON-формате. Позволяет проверить какие роуты, кластеры и listener'ы реально применены.

**Ephemeral Container** — временный контейнер в поде Kubernetes, используемый для отладки без изменения основного контейнера. Позволяет запускать утилиты диагностики (netshoot, tcpdump) в сетевом namespace проблемного пода.

**Packet Capture** — захват сетевых пакетов для анализа трафика. Используется для диагностики проблем на транспортном уровне (TCP, DNS, TLS handshake).

## Предварительные требования

| Компонент | Минимальная версия | Проверка |
|:---|:---|:---|
| kubectl | 1.25+ | `kubectl version --client --short` |
| Gateway API контроллер | Зависит от реализации | `kubectl get pods -n <controller-ns>` |
| netshoot (опционально) | latest | `kubectl run netshoot --image=nicolaka/netshoot --rm -it --restart=Never -- /bin/bash` |

## Базовые концепции

### Алгоритм диагностики "сверху вниз"

Проблема "трафик не работает" решается поэтапно:

```
1. Клиент не может достучаться до сервиса
   └── Проверка DNS и внешнего IP
       └── Проверка Gateway (Programmed: True?)
           └── Проверка HTTPRoute (Accepted: True?)
               └── Проверка ReferenceGrant (ResolvedRefs: True?)
                   └── Проверка Service/Endpoints
                       └── Проверка подов бэкенда
                           └── Проверка NetworkPolicy
```

### Уровни диагностики

| Уровень | Инструменты | Что проверяем |
|:---|:---|:---|
| **L7 (HTTP)** | curl, httpie, access logs | HTTP-коды, заголовки, пути |
| **L4 (TCP)** | nc, telnet, tcpdump | TCP-соединения, порты |
| **L3 (IP)** | ping, traceroute, ip route | Маршрутизация, сетевая доступность |
| **K8s** | kubectl, gwctl | Статусы ресурсов, события |

## Практические сценарии

### Шаг 1: Проверка статусов всех ресурсов

```bash
# Массовая проверка Gateway API ресурсов
kubectl get gateway,httproute,gatewayclass,referencegrant,backendtlspolicy -A

# Проверка что все ресурсы в состоянии True
kubectl get gateway -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\t"}{range .status.conditions[*]}{.type}={.status}{" "}{end}{"\n"}{end}'

# Пример вывода:
# → envoy-gateway-system/external-gw    Accepted=True Programmed=True ResolvedRefs=True
# → Если какое-то условие False — проблема найдена
```

### Шаг 2: Диагностика Gateway

```bash
# Проверка Gateway
kubectl describe gateway <name> -n <namespace>

# Ищите:
# - Conditions: Accepted=True, Programmed=True
# - Addresses: должен быть внешний IP
# - Listeners: Attached Routes должно быть > 0

# Если Programmed=False — проблема с Data Plane
kubectl logs -n envoy-gateway-system -l control-plane=envoy-gateway-controller --tail=100 | grep -i error

# Если нет внешнего IP — проблема с MetalLB/LoadBalancer
kubectl get svc -n envoy-gateway-system -l gateway.envoyproxy.io/owning-gateway-name=<name>
```

### Шаг 3: Диагностика HTTPRoute

```bash
# Проверка HTTPRoute
kubectl describe httproute <name> -n <namespace>

# Ищите:
# - Status.Parents[].Conditions: Accepted=True, ResolvedRefs=True
# - Если ResolvedRefs=False — проверьте ReferenceGrant

# Проверка ReferenceGrant
kubectl get referencegrant -A
# → Убедитесь что есть разрешение для кросс-namespace ссылок

# Проверка что бэкенд существует
kubectl get svc <backend-name> -n <backend-namespace>
kubectl get endpoints <backend-name> -n <backend-namespace>
```

### Шаг 4: Диагностика через Envoy Admin Interface

```bash
# Проброс порта Envoy admin interface
kubectl port-forward -n envoy-gateway-system <envoy-pod> 19000:19000

# Получение полной конфигурации
curl -s http://localhost:19000/config_dump | jq '.configs[] | select(.["@type"] == "type.googleapis.com/envoy.config.bootstrap.v3.Bootstrap")'

# Проверка listener'ов
curl -s http://localhost:19000/config_dump | jq '.configs[] | select(.["@type"] == "type.googleapis.com/envoy.config.listener.v3.Listener") | .name'

# Проверка маршрутов (Route Configuration)
curl -s http://localhost:19000/config_dump | jq '.configs[] | select(.["@type"] == "type.googleapis.com/envoy.config.route.v3.RouteConfiguration") | .routes[]'

# Проверка кластеров (backends)
curl -s http://localhost:19000/clusters | grep "EXTERNAL-NAME"
# → Проверьте что кластеры в состоянии HEALTHY

# Проверка статистики
curl -s http://localhost:19000/stats | grep "cluster.backend"
# → Ищите envoy_cluster_upstream_rq_xx с кодами ошибок
```

### Шаг 5: Проверка сетевой доступности изнутри кластера

```bash
# Запуск отладочного пода с утилитами
kubectl run netshoot --image=nicolaka/netshoot --rm -it --restart=Never \
  --overrides='{"spec":{"tolerations":[{"operator":"Exists"}]}}' \
  -- /bin/bash

# Изнутри пода:
# Проверка DNS
nslookup <service-name>.<namespace>.svc.cluster.local

# Проверка TCP-доступности
nc -zv <service-name>.<namespace>.svc.cluster.local 8080

# Проверка HTTP
curl -v http://<service-name>.<namespace>.svc.cluster.local:8080/health

# Проверка TLS
openssl s_client -connect <service-name>.<namespace>.svc.cluster.local:443 -servername <hostname>
```

### Шаг 6: Packet Capture (tcpdump)

```bash
# Запуск tcpdump в ephemeral container
kubectl debug -it <envoy-pod> \
  --image=nicolaka/netshoot \
  --target=envoy \
  -- /bin/bash

# Внутри контейнера:
# Захват трафика на порту 80
tcpdump -i eth0 port 80 -nn -vv

# Захват DNS-запросов
tcpdump -i eth0 port 53 -nn

# Захват TLS- handshake
tcpdump -i eth0 port 443 -nn -vv

# Сохранение в файл для анализа в Wireshark
tcpdump -i eth0 port 80 -w /tmp/capture.pcap
```

### Шаг 7: Анализ access logs

**Envoy access logs:**
```bash
# Включение access logs (если не настроены)
kubectl port-forward -n envoy-gateway-system <envoy-pod> 19000:19000

# Просмотр логов Envoy
kubectl logs -n envoy-gateway-system <envoy-pod> -c envoy --tail=100

# Поиск ошибок
kubectl logs -n envoy-gateway-system <envoy-pod> -c envoy | grep "503"
```

**NGINX access logs:**
```bash
# Просмотр access logs NGINX Gateway Fabric
kubectl logs -n nginx-gateway <ngf-pod> --tail=100

# Проверка наличия ошибок
kubectl logs -n nginx-gateway <ngf-pod> | grep -E "5[0-9]{2}"
```

### Шаг 8: Проверка конфигурации Envoy через API

```bash
# Получение информации о сервере
curl -s http://localhost:19000/server_info | jq

# Проверка ready probes
curl -s http://localhost:19000/ready | jq
# → {"state":"LIVE"}

# Проверка outstanding dumps
curl -s http://localhost:19000/STATS | head -20

# Проверка rates
curl -s http://localhost:19000/stats | grep "cluster\." | head -20
```

## Troubleshooting

### Типичные сценарии и решения

| Сценарий | Симптомы | Диагностика | Решение |
|:---|:---|:---|:---|
| **Трафик не доходит** | curl timeout, 502 | Проверить `Programmed`, endpoints | Восстановить бэкенд, проверить NetworkPolicy |
| **502 Bad Gateway** | Ответ 502 от Envoy | `config_dump`, проверить кластер | Исправить backendRefs, проверить порты |
| **404 Not Found** | Ответ 404 | Проверить route matching, hostnames | Исправить path/header в HTTPRoute |
| **TLS handshake failure** | `SSL_ERROR`, `certificate verify failed` | Проверить Secret, ReferenceGrant | Восстановить сертификат, создать ReferenceGrant |
| **DNS resolution failed** | `nslookup` не работает | Проверить CoreDNS, service | Проверить DNS-политики, CoreDNS логи |
| **Высокая задержка** | Slow responses | Envoy stats, Prometheus | Настроить таймауты, проверить бэкенды |
| **Connection refused** | TCP refused | `nc -zv`, NetworkPolicy | Добавить egress/ingress правила |

### Глубокая диагностика 502 Bad Gateway

```bash
# 1. Проверка что Envoy видит кластер
kubectl port-forward -n envoy-gateway-system <envoy-pod> 19000:19000
curl -s http://localhost:19000/clusters | grep "my-service"
# → Если кластер не найден — проблема в конфигурации

# 2. Проверка health checks
curl -s http://localhost:19000/clusters | grep "my-service.*HEALTHY"
# → Если unhealthy — бэкенд не проходит health check

# 3. Проверка endpoints
kubectl get endpoints my-service -n my-namespace
# → Если пусто — нет готовых подов

# 4. Проверка логов Envoy
kubectl logs -n envoy-gateway-system <envoy-pod> -c envoy | grep "503"
# → Ищите upstream connection failure
```

### Глубокая диагностика TLS-проблем

```bash
# 1. Проверка что сертификат существует
kubectl get secret <tls-secret> -n <namespace> -o jsonpath='{.type}'
# → Должно быть kubernetes.io/tls

# 2. Проверка 내용а сертификата
kubectl get secret <tls-secret> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -text | head -20
# → Subject, Not Before, Not After, DNS Names

# 3. Проверка что ReferenceGrant разрешает доступ
kubectl get referencegrant -n <namespace> -o yaml | grep -A10 "from:"

# 4. Проверка статуса Gateway listener
kubectl get gateway <name> -n <namespace> -o jsonpath='{.status.listeners[*].conditions}'
```

## Best Practices

### Инструментарий для диагностики

1. **Всегда держите netshoot под рукой:**
   ```bash
   # Быстрый запуск отладочного пода
   kubectl run debug --image=nicolaka/netshoot --rm -it --restart=Never -- /bin/bash
   ```

2. **Настройте access logs:**
   - Envoy: через EnvoyProxy CRD
   - NGINX: через NginxProxy CRD

3. **Используйте ephemeral containers для отладки подов контроллера:**
   ```bash
   kubectl debug -it <pod> --image=busybox --target=<container> -- /bin/sh
   ```

4. **Собирайте diagnostics bundle при проблемах:**
   ```bash
   #!/bin/bash
   # diagnostics.sh
   kubectl get gateway,httproute,gatewayclass,referencegrant -A > resources.txt
   kubectl describe gateway -A > gateway-describe.txt
   kubectl describe httproute -A > httproute-describe.txt
   kubectl logs -n envoy-gateway-system -l control-plane=envoy-gateway-controller --tail=500 > controller-logs.txt
   kubectl logs -n envoy-gateway-system -l gateway.envoyproxy.io/owning-gateway-name="" -c envoy --tail=500 > envoy-logs.txt
   ```

5. **Автоматизируйте базовую диагностику:**
   ```bash
   # Быстрая проверка всех ресурсов
   kubectl get gateway,httproute,referencegrant -A -o wide | grep -v "True"
   # → Должно быть пусто (все ресурсы в True)
   ```

## Дополнительная информация

### Связанные ресурсы

- [Envoy Gateway](./envoy_gateway.md) — Envoy admin interface, config_dump
- [Traefik](./traefik.md) — Dashboard Traefik, API diagnostics
- [NGINX Gateway Fabric](./nginx_gateway_fabric.md) — diagnostics для NGF
- [Мониторинг](./monitoring.md) — PromQL для диагностики
- [Определения Gateway API](./definitions.md) — статусы Conditions

**Родительская тема:** [Gateway API](./definitions.md)
