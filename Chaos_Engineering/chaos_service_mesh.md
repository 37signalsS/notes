# Chaos Engineering для Service Mesh (Istio/Envoy)

## Определения

**Service Mesh Chaos** — направление Chaos Engineering, ориентированное на проверку устойчивости proxy-layer (Envoy, ztunnel), control plane (istiod) и механизмов traffic management в условиях контролируемых сбоев.

**Istio Fault Injection** — встроенный механизм внедрения задержек и abort-ошибок через VirtualService, не требующий внешних инструментов Chaos Engineering. Покрывает только delay/abort на уровне HTTP, но полезен для shift-left тестирования в CI/CD.

**Envoy Outlier Detection** — механизм автоматического исключения нездоровых эндпоинтов из балансировки на основе метрик: успешность, latency, panics. Настраивается в DestinationRule: `consecutive5xx`, `interval`, `baseEjectionTime`, `maxEjectionPercent`.

**mTLS Disruption** — сценарий истечения или отзыва сертификата в условиях активного трафика. Проверяет, что mesh корректно обрабатывает handshake failures, существующие соединения остаются рабочими, новые получают понятную ошибку.

**Sidecar Resource Contention** — соревнование за CPU/memory между istio-proxy и приложением. Проверяет, что resource limits настроены корректно и ни один контейнер не доминирует.

**Ambient Mesh (ztunnel)** — режим Istio без sidecar, где L4 proxy (ztunnel) работает на уровне node. Chaos Engineering проверяет failover ztunnel при отказе узла и корректность перехвата трафика.

## Основные концепции

### Control Plane vs Data Plane chaos

| Плоскость | Компоненты | Типичные сценарии хаоса |
|:---|:---|:---|
| **Control Plane** | istiod, Citadel, Galley | Отказ istiod, истечение CA сертификата, ошибки конфигурации |
| **Data Plane** | Envoy sidecar, ztunnel | Утечка памяти, CPU starvation, crash, network partition |
| **Config Plane** | VirtualService, DestinationRule | Некорректный fault injection, неверные weights |

### Istio fault injection vs external chaos

**Встроенный fault injection (VirtualService):**
- Преимущества: простой declarative config, integrates с traffic management, не требует дополнительных инструментов.
- Ограничения: только delay и abort на уровне HTTP, не покрывает CPU/memory/disk chaos, не поддерживает StatefulSet chaos.

**Внешний chaos (Chaos Mesh/Litmus):**
- Преимущества: полный спектр сбоев (network, compute, kernel), blast radius control, stop-switch, probes.
- Ограничения: требует установки инструмента, дополнительной конфигурации.

**Рекомендация:** комбинируйте оба подхода. VirtualService fault injection для базовых проверок в CI/CD, Chaos Mesh для production Game Days.

### Envoy outlier detection vs Circuit Breaker

| Механизм | Уровень | Триггер | Действие |
|:---|:---|:---|:---|
| **Outlier Detection** | L7 (per-host) | 5xx, latency, panics | Удаляет эндпоинт из lb pool на `outlier_detection.interval` |
| **Circuit Breaker** | L7 (per-host/cluster) | `cb_thresholds` | Блокирует вызовы при превышении порога |
| **Health Checking** | L4/L7 | Active/passive probe | Помечает эндпоинт unhealthy |

Chaos Engineering проверяет, что outlier detection срабатывает при injected fault и эндпоинт возвращается в pool после recovery.

## Практические сценарии

### Сценарий 1: VirtualService fault injection (delay/abort)

**Цель:** Проверить, что VirtualService fault injection работает корректно и клиенты обрабатывают задержки/ошибки.

**Конфигурация VirtualService:**

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api-fault
  namespace: production
spec:
  hosts:
    - api-service
  http:
    - fault:
        delay:
          percentage:
            value: 10.0
          fixedDelay: 500ms
        abort:
          percentage:
            value: 5.0
          httpStatus: 503
      route:
        - destination:
            host: api-service
```

**Проверка:**

```bash
# Генерация трафика
kubectl exec -n production deploy/api-client -- curl -s http://api-service/api/health | jq .

# Проверка метрик Envoy
kubectl exec -n production deploy/api-service -c istio-proxy -- pilot-agent request GET stats | grep -E "(delay|abort|fault)"
# → cluster.api-service.outlier_detection.ejections_active: 0
# → http.istio_controlplane.fault.abort.total: 150
# → http.istio_controlplane.fault.delay.total: 300

# Проверка, что 5% запросов возвращают 503
for i in {1..100}; do curl -s -o /dev/null -w "%{http_code}\n" http://api-service/api/health; done | sort | uniq -c
# → 95 раз 200, 5 раз 503
```

### Сценарий 2: Outlier detection validation

**Цель:** Проверить, что Envoy исключает эндпоинт из пула при 5xx ошибках и возвращает его после recovery.

**Предварительная конфигурация DestinationRule:**

```yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: api-service
  namespace: production
spec:
  host: api-service
  trafficPolicy:
    outlierDetection:
      consecutive5xx: 5
      interval: 10s
      baseEjectionTime: 30s
      maxEjectionPercent: 50
```

**Инжектируем сбой:** abort 100% на один под.

```bash
# Находим под target
TARGET_POD=$(kubectl get pods -n production -l app=api-service -o jsonpath='{.items[0].metadata.name}')

# Инжектируем abort через iptables (прямой подход)
kubectl exec -n production deploy/chaos-runner -- iptables -A OUTPUT -d <TARGET_POD_IP> -p tcp --dport 8080 -j DROP
```

**Наблюдаем:**

```bash
# Envoy должен исключить эндпоинт
kubectl exec -n production deploy/api-client -c istio-proxy -- pilot-agent request GET config_dump | jq '.configs[].dynamic_active_clusters[].lb_endpoints[] | select(.metadata.locality.region == "us-east-1") | .metadata.locality.zone'
# → Здоровые эндпоинты остаются, проблемный исключен

# Проверка ejections
kubectl exec -n production deploy/api-client -c istio-proxy -- pilot-agent request GET stats | grep outlier_detection
# → cluster.api-service.outlier_detection.ejections_active: 1
# → cluster.api-service.outlier_detection.ejections_total: 1

# Восстановление: удаляем iptables правило
kubectl exec -n production deploy/chaos-runner -- iptables -D OUTPUT -d <TARGET_POD_IP> -p tcp --dport 8080 -j DROP

# Через 30s эндпоинт должен вернуться
sleep 35
kubectl exec -n production deploy/api-client -c istio-proxy -- pilot-agent request GET stats | grep outlier_detection
# → cluster.api-service.outlier_detection.ejections_active: 0
```

### Сценарий 3: mTLS disruption (cert expiration mid-flight)

**Цель:** Проверить, что mesh корректно обрабатывает истечение сертификата без каскадного сбоя.

**Предварительные требования:**

```bash
# Проверка текущего сертификата
kubectl exec -n production deploy/api-service -c istio-proxy -- pilot-agent request GET config_dump | jq '.configs[].dynamic_active_clusters[].tls_context'
# → Проверьте ssl_certificates_sds_config

# Проверка срока действия
kubectl get secret istio-ca-secret -n istio-system -o jsonpath='{.data.ca-cert\.pem}' | base64 -d | openssl x509 -noout -dates
# → notBefore=..., notAfter=...
```

**Инжектируем сбой:** отзываем сертификат в CA.

```bash
# Отзываем сертификат (требует доступа к Citadel/istiod)
kubectl exec -n istio-system deploy/istiod -- pilot-agent request GET config_dump | jq '.configs[].static_resources.listener_configs[] | select(.name == "virtualInbound")'
# → Найдите listener SDS

# Альтернативно: перезапустите istiod с отключенным auto-rotation
kubectl rollout restart deployment/istiod -n istio-system
```

**Наблюдаем:**

```bash
# Приложение должно продолжать работать на существующих соединениях
kubectl exec -n production deploy/api-service -c istio-proxy -- curl -s http://localhost:15000/stats | grep ssl
# → ssl.connections: 10 (существующие соединения живы)
# → ssl.handshake_failures: 0 (пока)

# Новые соединения должны падать
kubectl exec -n production deploy/api-client -- curl -v http://api-service/api/health 2>&1 | grep -E "(SSL|TLS|error)"
# → После отзыва сертификата: TLS handshake failure

# Восстановление: верните CA
kubectl rollout restart deployment/istiod -n istio-system

# При следующем connection attempt mTLS должен восстановиться
kubectl exec -n production deploy/api-client -- curl -s http://api-service/api/health
# → 200 OK
```

### Сценарий 4: Sidecar resource starvation

**Цель:** Проверить, что istio-proxy и приложение корректно делят ресурсы и ни один не доминирует.

**Предварительная конфигурация:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: api-service
  namespace: production
spec:
  containers:
    - name: api-service
      resources:
        limits:
          cpu: "500m"
          memory: "256Mi"
    - name: istio-proxy
      resources:
        limits:
          cpu: "500m"
          memory: "256Mi"
```

**Инжектируем сбой:** CPU hog на istio-proxy.

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: sidecar-cpu-starvation
  namespace: chaos-testing
spec:
  mode: one
  selector:
    namespaces:
      - production
    labelSelectors:
      app: api-service
  stressors:
    cpu:
      workers: 2
      load: 90
  target:
    mode: one
    selector:
      namespaces:
        - production
      labelSelectors:
        app: api-service
  duration: "3m"
```

**Наблюдаем:**

```bash
# Проверка CPU подов
kubectl top pods -n production -l app=api-service
# → api-service-xxx                    500m      256Mi
# → api-service-xxx (istio-proxy)      450m      200Mi

# Проверка latency приложения
kubectl exec -n production deploy/api-client -- curl -s http://api-service/api/health | jq .latency
# → Latency может вырасти, но приложение не должно падать

# Проверка, что istio-proxy не потребляет всю CPU
kubectl top pods -n production -l app=api-service -c istio-proxy
# → < 500m (в пределах лимита)
```

### Сценарий 5: Ambient mesh (ztunnel) failure

**Цель:** Проверить, что при отказе ztunnel трафик перенаправляется корректно.

**Предварительные требования:**

```bash
# Проверка ztunnel статуса
kubectl get pods -n istio-system -l app=ztunnel

# Проверка iptables правила (перенаправление трафика в ztunnel)
kubectl exec -n production deploy/api-service -- iptables -t nat -L -v -n | grep ztunnel
```

**Инжектируем сбой:** удаляем ztunnel под на узле.

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: ztunnel-kill
  namespace: chaos-testing
spec:
  action: pod-kill
  mode: one
  selector:
    namespaces:
      - istio-system
    labelSelectors:
      app: ztunnel
  duration: "2m"
```

**Наблюдаем:**

```bash
# Трафик должен продолжать работать (ztunnel перезапускается автоматически)
kubectl exec -n production deploy/api-client -- curl -s http://api-service/api/health
# → 200 OK

# Проверка, что ztunnel перезапущен
kubectl get pods -n istio-system -l app=ztunnel
# → Новый pod запущен, Ready

# Проверка логов ztunnel
kubectl logs -n istio-system -l app=ztunnel --tail=100 | grep -E "(error|connection|reset)"
# → Ошибок нет, соединения восстановлены
```

### Сценарий 6: Control plane unavailability

**Цель:** Проверить, что data plane продолжает работать при отказе istiod.

**Инжектируем сбой:** удаляем istiod.

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: istiod-kill
  namespace: chaos-testing
spec:
  action: pod-kill
  mode: all
  selector:
    namespaces:
      - istio-system
    labelSelectors:
      app: istiod
  duration: "5m"
```

**Наблюдаем:**

```bash
# Существующие соединения должны продолжать работать
kubectl exec -n production deploy/api-client -- curl -s http://api-service/api/health
# → 200 OK (кешированная конфигурация Envoy)

# Новые конфигурации не применяются (новые routes, weights)
# Это ожидаемое поведение: control plane down = no new config

# Проверка метрик istiod
kubectl get pods -n istio-system -l app=istiod
# → Istiod перезапускается (ReplicaSet)

# Восстановление: istiod возвращается, xDS push применяется
kubectl get pods -n istio-system -l app=istiod
# → Ready
```

## Операции и команды

### Istio CLI

```bash
# Проверка конфигурации
istioctl proxy-config cluster deploy/api-service -n production
istioctl proxy-config listener deploy/api-service -n production
istioctl proxy-config route deploy/api-service -n production

# Проверка статуса mesh
istioctl mesh status
istioctl authn status deploy/api-service -n production
```

### Envoy admin API

```bash
# Статистика
kubectl exec -n production deploy/api-service -c istio-proxy -- pilot-agent request GET stats | grep -E "(outlier|circuit|retry|fault)"

# Конфигурация
kubectl exec -n production deploy/api-service -c istio-proxy -- pilot-agent request GET config_dump | jq '.configs[].dynamic_active_clusters[] | select(.name == "outbound|9080||api-service.default.svc.cluster.local")'

# Трассировка
kubectl exec -n production deploy/api-service -c istio-proxy -- pilot-agent request GET tracing | jq .
```

### Cert-manager / Istio CA

```bash
# Проверка сертификатов
kubectl get certificates -n istio-system
kubectl describe certificate istio-ca-secret -n istio-system

# Принудительная ротация
kubectl rollout restart deployment/istiod -n istio-system

# Проверка SDS
kubectl exec -n production deploy/api-service -c istio-proxy -- pilot-agent request GET stats | grep sds
```

### Chaos Mesh: istiod chaos

```yaml
# Удаление istiod
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: istiod-kill
  namespace: chaos-testing
spec:
  action: pod-kill
  mode: all
  selector:
    namespaces:
      - istio-system
    labelSelectors:
      app: istiod
```

### ztunnel chaos

```bash
# Находим ztunnel поды
kubectl get pods -n istio-system -l app=ztunnel

# Удаляем конкретный под
kubectl delete pod ztunnel-xxx -n istio-system

# Проверка reintegration
kubectl get pods -n istio-system -l app=ztunnel
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| **Fault injection не применяется** | VirtualService не синхронизирован | Проверьте `kubectl get virtualservice`, `istioctl proxy-status` |
| **Outlier detection не срабатывает** | Порог слишком высокий или health check мешает | Снизьте `consecutive5xx`, проверьте Active Health Check |
| **mTLS handshake failure** | Сертификат отозван или истек | Проверьте `istioctl authn check`, срок действия сертификата |
| **Sidecar CPU starvation** | Лимиты слишком низкие или conflated с приложением | Увеличьте `resources.limits.cpu` для istio-proxy, используйте отдельные limits |
| **ztunnel не перезапускается** | DaemonSet не может запланировать под | Проверьте `kubectl describe pod`, ресурсы узла, tolerations |
| **Control plane down = data plane down** | Приложение зависит от istiod для каждого запроса | Включите `sidecar.istio.io/rewriteAppHTTPProbers: "true"`, кешируйте конфигурацию |
| **Split-brain в multi-cluster** | Два кластера считают себя primary | Проверьте `primary_cluster_id` в DestinationRule, настройте failover priorities |

## Лучшие практики

### Control Plane

1. **Тестируйте control plane отдельно** — отказ istiod не должен влиять на data plane.
2. **Настройте multi-cluster failover** — DestinationRule с `failover` при отказе remote cluster.
3. **Мониторьте istiod health** — алерт на `istiod_controller_sync_errors_total`, `pilot_xds_pushes_sent_total`.
4. **Имейте каскадный CA** — установите intermediate CA для mesh, чтобы отзыв одного сертификата не затрагивал все сервисы.

### Data Plane

5. **Тестируйте outlier detection** — регулярно проверяйте, что нездоровые эндпоинты исключаются.
6. **Настройте circuit breaking на уровне DestinationRule** — `connection_pool`, `outlier_detection`, `tls`.
7. **Используйте mTLS с auto-rotation** — настройте `caCertificates` в Citadel, monitor `cert_expiry_seconds`.
8. **Тестируйте sidecar resource limits** — chaos experiment с CPU/memory hog.

### Ambient Mesh

9. **Тестируйте ztunnel failure** — DaemonSet должен перезапускать pod автоматически.
10. **Мониторьте ztunnel health** — алерт на `ztunnel_connection_terminations_total`, `ztunnel_tunnel_errors_total`.

### Безопасность

11. **Тестируйте mTLS disruption в staging** — первый эксперимент с cert expiration только в тестовой среде.
12. **Имейте emergency stop для istiod** — откат на предыдущую версию, `kubectl rollout undo`.
13. **Ведите runbook для cert rotation** — как вручную ротировать сертификаты, как откатить.

## Дополнительная информация

### Интеграция с другими инструментами

- **Chaos Mesh + Istio:** Инжекция сетевых задержек через `NetworkChaos` в namespace с sidecar. Istio автоматически применяет retry/timeout.
- **LitmusChaos + Istio:** `ChaosEngine` может таргетить поды с аннотацией `sidecar.istio.io/inject`.
- **Gremlin + Istio:** Gremlin атакует на уровне узла, Istio видит деградацию через outlier detection.

### См. также

- [Chaos Engineering — инструменты](chaos_engineering_tools.md) — обзор Chaos Mesh, Litmus для mesh chaos.
- [Chaos Engineering — практическое руководство](chaos_engineering_practical.md) — Game Days с service mesh.
- [Service Mesh — управление трафиком](../../Service_Mesh/traffic_management.md) — теория fault injection в Istio.
- [Chaos Engineering — resilience patterns](chaos_resilience_patterns_testing.md) — testing Circuit Breaker через mesh.
