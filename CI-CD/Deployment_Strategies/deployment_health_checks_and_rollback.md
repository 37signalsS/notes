# Deployment Health Checks and Rollback

## Definitions

**Health Check** — автоматизированный сигнал, сообщающий CI/CD-системе о состоянии новой версии приложения. На основе сигнала принимается решение о продолжении развертывания или откате.

**Rollback** — автоматизированный или ручной процесс возврата к предыдущей стабильной версии при обнаружении критической ошибки или деградации производительности.

## Basic Concepts

### Health Check Types in Kubernetes

Kubernetes предоставляет три типа проб (probes) для управления развертыванием:

| Probe Type | Signal | Purpose | Reaction to Failure |
| :--- | :--- | :--- | :--- |
| **`readinessProbe`** | "Готов ли под принимать трафик?" | Безопасный ввод в эксплуатацию | Под исключается из Service, не перезапускается |
| **`livenessProbe`** | "Работает ли приложение или зависло?" | Обнаружение deadlock, зависаний | Контейнер перезапускается |
| **`startupProbe`** | "Завершился ли долгий запуск?" | Защита от преждевременных рестартов | Перезапуск при превышении `failureThreshold` |

Подробное описание проб — в [Probes](../../Kubernetes/Base/probes.md).

Дополнительный сигнал для CI/CD — **анализ метрик наблюдаемости** (ошибки, задержка) через [Canary Monitoring and Gating](./canary_monitoring_and_gating.md).

### Rollback Principles

| Principle | Description |
| :--- | :--- |
| **Automation** | Решение об откате принимается на основе метрик, а не человеком |
| **Speed** | Процесс должен быть быстрым для минимизации влияния на пользователей |
| **Data Safety** | Стратегия должна учитывать совместимость схемы БД |

### Rollback Strategies by Deployment Type

| Strategy | Rollback Mechanism | Speed | Downtime |
| :--- | :--- | :--- | :--- |
| **Recreate** | Развертывание старой версии после остановки новой | Медленно | Гарантированный простой |
| **Rolling Update** | `kubectl rollout undo deployment/<name>` | Средняя (поэтапный) | Нет |
| **Blue-Green** | Мгновенное переключение трафика на Blue | Мгновенно | Нет (требуется `drain` соединений) |
| **Canary** | Возврат веса трафика к 100% на stable | Быстро | Нет |
| **Feature Flags** | Отключение функции без переразвертывания | Мгновенно | Нет |

### Database Migration Rollback

Откат миграций БД — критически сложная операция.

**Опасно:** Прямой откат DDL (`ALTER TABLE DROP COLUMN`) после применения новой версией кода может привести к **потере данных**.

**Безопасный подход (код → данные):**

1. **Откат приложения** → возврат к версии, работающей со старой схемой
2. **Совместимость через Expand-Contract** → старый код работает с расширенной схемой
3. **Ручная корректировка данных** → при необходимости восстановления совместимости
4. **Откат миграции** → только после стабилизации системы

Подробнее — [Database Rollback Strategies](../../Databases/Concepts/rollback_strategies.md), [Migration Rollback](../../Databases/Concepts/migrations/rollback_strategies.md).

## Practical Scenarios

### Scenario 1: Kubernetes Probe Configuration

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: app
          image: registry/myapp:2.3.1
          ports:
            - containerPort: 8080
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 5
            failureThreshold: 3
          livenessProbe:
            httpGet:
              path: /health/live
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 10
          startupProbe:
            httpGet:
              path: /health/startup
              port: 8080
            failureThreshold: 30
            periodSeconds: 5
```

### Scenario 2: Automatic Rollback Based on Metrics

```bash
set -e

ERROR_RATE=$(curl -s "$PROM_URL/api/v1/query" \
  --data-urlencode "query=rate(http_requests_errors_total{app=\"myapp\",version=\"canary\"}[5m]) / rate(http_requests_total{app=\"myapp\",version=\"canary\"}[5m])" \
  | jq -r '.data.result[0].value[1]')

P95=$(curl -s "$PROM_URL/api/v1/query" \
  --data-urlencode "query=histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{app=\"myapp\",version=\"canary\"}[5m])) by (le))" \
  | jq -r '.data.result[0].value[1]')

if (( $(echo "$ERROR_RATE > 0.01 || $P95 > 0.3" | bc -l) )); then
  echo "Degradation detected. Rolling back..."
  kubectl rollout undo deployment/myapp
  exit 1
fi
```

## Additional Information

### Common Mistakes

| Mistake | Consequence |
| :--- | :--- |
| `readinessProbe` проверяет только HTTP 200 без проверки зависимостей (БД, кэш) | Трафик идет на неготовые поды |
| Слишком агрессивные пороги (`failureThreshold`, `periodSeconds`) | Каскадные перезапуски (`flip-flop`) |
| Отсутствие прогрева кэша перед Blue-Green переключением | Ошибки пользователей после переключения |
| Откат схемы БД до отката приложения | Потеря данных |
| Игнорирование сезонности трафика при оценке Canary | Ложные срабатывания алертов |

### Связанные документы

- [Probes in Kubernetes](../../Kubernetes/Base/probes.md)
- [Blue-Green Deployment](./blue_green_deployment.md)
- [Canary Deployments](./canary_deployment.md)
- [Rolling Update](./rolling_update.md)
- [Canary Monitoring and Gating](./canary_monitoring_and_gating.md)
- [Database Rollback Strategies](../../Databases/Concepts/rollback_strategies.md)
