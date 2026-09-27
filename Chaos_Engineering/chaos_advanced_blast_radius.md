# Продвинутое управление радиусом поражения (Blast Radius)

## Определения

**Advanced Blast Radius Control** — набор техник для точного управления масштабом хаос-экспемента: от traffic mirroring до dependency-aware targeting. Цель — минимизировать риски для production, одновременно получая статистически значимые результаты.

**Traffic Mirroring** — техника копирования production-трафика на experimental-под без влияния на пользователей. Позволяет запускать хаос-тесты на реальном трафике с радиусом поражения 0%. Используется Istio VirtualService `mirror` или Linkerd Traffic Mirror.

**Progressive Rollout** — постепенное увеличение blast radius: 1% → 5% → 20% → 50% → 100%. На каждом этапе проверяется steady state перед переходом к следующему. Критично для критичных сервисов.

**User Segment-Based Blast Radius** — ограничение эксперимента по сегментам пользователей: география, tenant ID, device type, user tier. Реализуется через Istio Request Routing, header-based routing, tenant isolation.

**Dependency-Aware Targeting** — автоматическое исключение критичных зависимостей из blast radius на основе топологии сервисов. Используется для предотвращения каскадных сбоев в критичных путях.

**Canary Experiment** — хаос-тест на канареечном сегменте с автоматическим промоутом или откатом. Аналогично canary deploy, но для fault injection.

**Time-Based Escalation** — увеличение blast radius во времени при отсутствии деградации: начать с 1 пода, через 5 минут добавить еще 1, и так далее. Реализуется через Chaos Mesh Scheduler.

## Основные концепции

### Принципы advanced blast radius

```
1. Минимизация риска: blast radius должен быть минимально возможным.
2. Статистическая значимость: blast radius должен быть достаточным для детекции деградации.
3. Контролируемый рост: возможность увеличивать радиус только при положительных метриках.
4. Dependency awareness: автоматическое исключение критичных путей.
5. Обратимость: каждый этап эксперимента должен быть обратим за <30 секунд.
```

### Классификация техник

| Техника | Blast Radius | Стат. значимость | Сложность | Применение |
|:---|:---|:---|:---|:---|
| **Basic (mode: one)** | 1 под/инстанс | Низкая | Низкая | Первые эксперименты, staging |
| **Fixed percent** | N% трафика | Средняя | Средняя | Production canary |
| **Traffic mirroring** | 0% (read-only copy) | Высокая | Высокая | Первый production эксперимент |
| **Progressive rollout** | Динамический рост | Высокая | Высокая | Production, Critical services |
| **User segment** | Сегмент пользователей | Средняя | Средняя | Multi-tenant, regional |
| **Dependency-aware** | Автоматический | Высокая | Высокая | Микросервисы с复杂ной топологией |

## Практические сценарии

### Сценарий 1: Traffic mirroring + chaos (0% blast radius)

**Цель:** Запустить хаос-тест на реальном production-трафике без влияния на пользователей.

**Инструмент:** Istio Traffic Mirroring + Chaos Mesh.

**Шаги:**

1. **Настройте traffic mirroring:** копируем 100% трафика на experimental-под.
2. **Инжектируем сбой:** только на experimental-под.
3. **Сравниваем:** метрики original vs experimental.
4. **Утверждаем:** если experimental деградирует, а original нет — эксперимент успешен.

**Конфигурация VirtualService:**

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api-service
  namespace: production
spec:
  hosts:
    - api-service
  http:
    - route:
        - destination:
            host: api-service
            subset: v1
          weight: 100
      mirror:
        host: api-service
        subset: v1-chaos
      mirror_percentage:
        value: 100.0
```

**Инжектируем сбой только на experimental:**

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: mirror-chaos
  namespace: chaos-testing
spec:
  action: delay
  mode: one
  selector:
    namespaces:
      - production
    labelSelectors:
      app: api-service
      version: v1-chaos
  delay:
    latency: "500ms"
  duration: "5m"
```

**Наблюдаем:**

```bash
# Original под (v1) должен отвечать <200ms
kubectl exec -n production deploy/load-generator -- curl -s -w "\n%{time_total}\n" http://api-service/api/health
# → time_total: 0.15s

# Experimental под (v1-chaos) должен деградировать
# Метрики experimental собираются отдельно
curl -s http://prometheus:9090/api/v1/query?query=histogram_quantile(0.99,sum(rate(http_request_duration_seconds_bucket{version="v1-chaos"}[5m])))
# → 0.7s (деградация)
```

### Сценарий 2: Progressive rollout blast radius

**Цель:** Постепенно увеличивать blast radius при отсутствии деградации.

**Инструмент:** Chaos Mesh + Prometheus + custom script.

**Этапы:**

| Этап | Blast Radius | Длительность | Критерий перехода |
|:---|:---|:---|:---|
| 1 | 1 под (mode: one) | 5 минут | Error rate < 0.1%, latency p99 < baseline * 1.2 |
| 2 | 5% трафика | 5 минут | Те же метрики |
| 3 | 20% трафика | 10 минут | Те же метрики |
| 4 | 50% трафика | 10 минут | Те же метрики |
| 5 | 100% трафика | 10 минут | Только для non-critical services |

**Automation script:**

```bash
#!/bin/bash
# progressive-chaos.sh

BLAST_RADIUSES=("one" "fixed-percent:5" "fixed-percent:20" "fixed-percent:50")
DURATIONS=("5m" "5m" "10m" "10m")

for i in "${!BLAST_RADIUSES[@]}"; do
  MODE=${BLAST_RADIUSES[$i]}
  DURATION=${DURATIONS[$i]}

  echo "Stage $((i+1)): mode=$MODE, duration=$DURATION"

  # Применяем эксперимент
  kubectl apply -f - <<EOF
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: progressive-chaos-stage-$((i+1))
  namespace: chaos-testing
spec:
  action: delay
  mode: $MODE
  selector:
    namespaces:
      - production
    labelSelectors:
      app: api-service
  delay:
    latency: "200ms"
  duration: "$DURATION"
EOF

  # Мониторим метрики
  sleep 30
  ERROR_RATE=$(curl -s http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{status=~"5.."}[5m]))/sum(rate(http_requests_total[5m])) | jq '.data.result[0].value[1]' -r)

  if (( $(echo "$ERROR_RATE > 0.05" | bc -l) )); then
    echo "FAIL: Error rate $ERROR_RATE exceeds 5%. Stopping."
    kubectl delete -f progressive-chaos-stage-$((i+1)).yaml
    exit 1
  fi

  echo "PASS: Error rate $ERROR_RATE. Proceeding to next stage."
  sleep $((DURATION_IN_SECONDS - 30))
done

echo "All stages passed. Blast radius expanded to 100%."
```

### Сценарий 3: User segment-based blast radius

**Цель:** Ограничить эксперимент конкретными пользователями (география, tenant).

**Инструмент:** Istio Request Routing + Chaos Mesh.

**Шаги:**

1. **Определите сегмент:** пользователи из EU region, tenant_id=123.
2. **Настройте маршрутизацию:** сегмент направляется на experimental-под.
3. **Инжектируем сбой:** только на experimental-под.
4. **Сравниваем:** метрики сегмента vs остальных пользователей.

**Конфигурация EnvoyFilter:**

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: EnvoyFilter
metadata:
  name: segment-routing
  namespace: production
spec:
  workloadSelector:
    labels:
      app: api-gateway
  configPatches:
    - applyTo: HTTP_ROUTE
      match:
        context: SIDECAR_INBOUND
        routeConfiguration:
          vhost:
            name: "inbound_9080"
            route:
              action: ANY
      patch:
        operation: MERGE
        value:
          route:
            cluster: "outbound|9080||api-service.default.svc.cluster.local"
            typed_per_filter_config:
              envoy.router:
                experimental:
                  segment: "eu-west"
```

**Chaos Mesh с сегментом:**

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: segment-chaos
  namespace: chaos-testing
spec:
  action: delay
  mode: fixed-percent
  fixedValue: 10
  selector:
    namespaces:
      - production
    labelSelectors:
      app: api-service
      segment: eu-west
  delay:
    latency: "300ms"
  duration: "10m"
```

### Сценарий 4: Dependency-aware blast radius

**Цель:** Автоматически исключить критичные зависимости из blast radius.

**Инструмент:** Service Mesh topology (Istio, Linkerd) + custom script.

**Шаги:**

1. **Постройте топологию:** какие сервисы зависят от каких.
2. **Определите критичные пути:** payment-service → core-banking (critical), payment-service → analytics (non-critical).
3. **Настройте исключения:** chaos не затрагивает core-banking.
4. **Инжектируем сбой:** только в analytics.

**Topology-based exclusion:**

```bash
# Получаем топологию через Istio
istioctl experimental describe service payment-service -n production

# Извлекаем зависимости
istioctl xpn describe service payment-service -n production | grep "Depends on"
# → analytics (non-critical)
# → core-banking (critical) → EXCLUDE

# Генерируем манифест с исключениями
cat > chaos-exclude-critical.yaml <<EOF
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: dependency-aware-chaos
  namespace: chaos-testing
spec:
  action: delay
  mode: fixed-percent
  fixedValue: 20
  selector:
    namespaces:
      - production
    labelSelectors:
      app: analytics
  # ИСКЛЮЧАЕМ critical path
  exclude:
    - namespaces:
        - production
      labelSelectors:
        app: core-banking
  delay:
    latency: "500ms"
  duration: "5m"
EOF
```

### Сценарий 5: Time-based blast radius escalation

**Цель:** Увеличивать blast radius автоматически при отсутствии деградации.

**Инструмент:** Chaos Mesh Scheduler + Alertmanager.

**Конфигурация:**

```yaml
# Chaos Mesh Scheduler: каждые 5 минут увеличиваем % pods
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: time-escalation
  namespace: chaos-testing
spec:
  action: delay
  mode: fixed-percent
  fixedValue: 5  # Начинаем с 5%
  selector:
    namespaces:
      - production
    labelSelectors:
      app: api-service
  delay:
    latency: "200ms"
  duration: "60m"
  scheduler:
    cron: "@every 10m"  # Каждые 10 минут
```

**Alertmanager: автоматический stop при деградации:**

```yaml
groups:
  - name: blast_radius_escalation
    rules:
      - alert: BlastRadiusEscalationStop
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) > 0.05
        for: 1m
        labels:
          severity: critical
          action: "stop_escalation"
        annotations:
          summary: "Error rate превысил 5%. Остановите увеличение blast radius."
```

### Сценарий 6: Shadow traffic validation (0% blast radius)

**Цель:** Полностью валидировать эксперимент без влияния на пользователей.

**Инструмент:** Istio Mirroring + Prometheus comparison.

**Шаги:**

1. **Настройте mirroring:** 100% трафика копируется на shadow-под.
2. **Инжектируем сбой:** только на shadow-под.
3. **Сравниваем метрики:** original (200 OK, latency <200ms) vs shadow (500ms delay, 5xx).
4. **Утверждаем:** если разница соответствует гипотезе — эксперимент готов для production.

**Манифест VirtualService:**

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api-service-shadow
  namespace: production
spec:
  hosts:
    - api-service
  http:
    - route:
        - destination:
            host: api-service
            subset: stable
          weight: 100
      mirror:
        host: api-service
        subset: shadow
      mirror_percentage:
        value: 100.0
```

## Операции и команды

### Chaos Mesh: режимы blast radius

```bash
# mode: one — 1 случайный под
kubectl apply -f chaos-one.yaml

# mode: all — все поды
kubectl apply -f chaos-all.yaml

# mode: fixed-percent — N% подов
kubectl apply -f chaos-percent.yaml

# mode: fixed-number — конкретное количество подов
kubectl apply -f chaos-number.yaml
```

### Progressive rollout automation

```bash
#!/bin/bash
# progressive-chaos.sh

STAGES=(
  "mode=one|duration=5m|threshold=0.01"
  "mode=fixed-percent,fixedValue=5|duration=5m|threshold=0.02"
  "mode=fixed-percent,fixedValue=20|duration=10m|threshold=0.03"
)

for stage in "${STAGES[@]}"; do
  MODE=$(echo $stage | cut -d'|' -f1)
  DURATION=$(echo $stage | cut -d'|' -f2 | cut -d'=' -f2)
  THRESHOLD=$(echo $stage | cut -d'|' -f3 | cut -d'=' -f2)

  kubectl apply -f - <<EOF
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: progressive-$RANDOM
  namespace: chaos-testing
spec:
  action: delay
  $MODE
  selector:
    namespaces:
      - production
    labelSelectors:
      app: api-service
  delay:
    latency: "200ms"
  duration: "$DURATION"
EOF

  # Мониторинг
  sleep 30
  ERROR_RATE=$(curl -s http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{status=~"5.."}[5m]))/sum(rate(http_requests_total[5m])) | jq '.data.result[0].value[1]' -r)

  if (( $(echo "$ERROR_RATE > $THRESHOLD" | bc -l) )); then
    echo "FAIL: Error rate $ERROR_RATE > $THRESHOLD"
    kubectl delete networkchaos -n chaos-testing --all
    exit 1
  fi
done
```

### Traffic mirroring verification

```bash
# Проверка, что mirroring работает
kubectl exec -n production deploy/api-client -- curl -s http://api-service/api/health
# → 200 OK (original)

# Проверка метрик experimental
curl -s http://prometheus:9090/api/v1/query?query=sum(rate(http_request_duration_seconds_bucket{version="v1-chaos"}[5m]))
# → Должно быть > original (из-за injected delay)
```

### Dependency-aware targeting

```bash
# Получение топологии через Istio
istioctl experimental describe service payment-service -n production

# Фильтрация critical dependencies
istioctl xpn describe service payment-service -n production | grep "critical" | awk '{print $1}'
# → core-banking
# → fraud-detection

# Исключаем из blast radius
kubectl apply -f chaos-exclude-critical.yaml
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| **Traffic mirroring не работает** | VirtualService не синхронизирован | Проверьте `kubectl get virtualservice`, `istioctl proxy-status` |
| **Progressive rollout останавливается** | Порог слишком низкий или сезонный пик | Настройте `for:` длительность, используйте baseline comparison |
| **User segment не работает** | Header/cookie не передается или маршрутизация сломана | Проверьте `istioctl proxy-config route deploy/api-gateway`, убедитесь, что header присутствует |
| **Dependency-aware исключает слишком много** | Топология неполная или over-filtering | Проверьте `istioctl xpn describe`, обновите labels |
| **Time-based escalation не работает** | Scheduler не настроен или эксперимент завершается | Проверьте `kubectl get networkchaos`, настройте `duration` и `scheduler.cron` |
| **Shadow traffic создает нагрузку** | Mirroring включен на 100% для тяжелого трафика | Используйте `mirror_percentage.value: 10` для начала |
| **Blast radius слишком широкий** | fixed-percent включает критические сервисы | Добавьте `exclude` в selector, проверьте labelSelectors |

## Лучшие практики

### Progressive Rollout

1. **Начинайте с 1 пода** — первый эксперимент всегда с минимальным blast radius.
2. **Устанавливайте пороги** — error rate < 1%, latency p99 < baseline * 1.2 на каждом этапе.
3. **Автоматизируйте остановку** — Alertmanager rule при превышении порога.
4. **Фиксируйте метрики** — baseline, error rate, latency на каждом этапе.
5. **Не пропускайте этапы** — даже если staging прошел, production может вести себя иначе.

### Traffic Mirroring

6. **Используйте для первого production эксперимента** — 0% blast radius, максимальная безопасность.
7. **Сравнивайте original vs shadow** — разница в метриках = эффект хаоса.
8. **Ограничивайте mirroring** — 100% mirroring для тяжелого трафика может создать нагрузку. Начните с 10%.
9. **Очищайте shadow-поды** — после эксперимента удалите experimental subset.

### Dependency-Aware Targeting

10. **Постройте топологию ДО экспериментов** — используйте Istio, Linkerd, или custom service discovery.
11. **Маркируйте critical services** — label `critical: true` для исключения из blast radius.
12. **Тестируйте exclusion** — убедитесь, что критичные сервисы не затрагиваются.
13. **Обновляйте топологию** — при добавлении новых сервисов обновляйте dependency graph.

### Безопасность

14. **Имейте emergency stop** — один человек с доступом к `kubectl delete -f`.
15. **Уведомляйте команду** — все должны знать о progressive rollout.
16. **Не проводите эксперименты во время релизов** — blast radius может пересечься с новым кодом.
17. **Ведите runbook** — для каждого этапа progressive rollout.

## Дополнительная информация

### Интеграция с другими инструментами

- **Istio Traffic Mirroring** — declarative mirroring через VirtualService.
- **Linkerd Traffic Mirror** — `mirror` в ServiceProfile.
- **Chaos Mesh Scheduler** — cron-based escalation blast radius.
- **Gremlin Blast Radius** — UI для управления радиусом.

### См. также

- [Chaos Engineering — обзор](chaos_engineering_overview.md) — blast radius basics.
- [Chaos Engineering — инструменты](chaos_engineering_tools.md) — Chaos Mesh modes.
- [Chaos Engineering — практическое руководство](chaos_engineering_practical.md) — Game Days с progressive rollout.
