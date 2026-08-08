# Ingress — установка через Helm

> [!WARNING]
> **Статус проектов (2026):** Проект `kubernetes/ingress-nginx` официально перешел в статус **End of Life (EOL)**. Поддержка прекращена, критические патчи безопасности не выпускаются. Для новых инсталляций настоятельно рекомендуется использовать **Traefik v3**, **Envoy Gateway** или другие современные реализации на базе **Gateway API**.

## Определения

**Helm** — стандартный менеджер пакетов для Kubernetes, использующий концепцию чартов (Charts) для описания, установки и обновления сложных приложений. Обеспечивает версионирование конфигураций и атомарность операций.

**Ingress-контроллер** — управляющее приложение, которое реализует правила маршрутизации L7, описанные в ресурсах `Ingress` или `HTTPRoute`. Он выступает точкой входа (Edge Proxy) для внешнего трафика.

## Базовые концепции

### Почему Helm является стандартом для Ingress

Установка Ingress-контроллера через Helm предоставляет ряд преимуществ по сравнению с обычными манифестами:

1.  **Декларативное управление:** Все настройки хранятся в файле `values.yaml`, что позволяет использовать подходы GitOps.
2.  **Атомарность обновлений:** Флаг `--atomic` гарантирует, что в случае сбоя при обновлении (например, если контроллер не прошел Readiness check), система автоматически вернется к предыдущему рабочему состоянию.
3.  **Управление зависимостями:** Многие чарты (например, Traefik) автоматически устанавливают необходимые CRD и роли RBAC.
4.  **Жизненный цикл:** Простое масштабирование и обновление версий прокси-движка одной командой.

## Практические сценарии

### Сценарий 1 — Установка Traefik v3 (Рекомендуемый Ingress)

Traefik v3 является предпочтительным выбором в 2026 году благодаря нативной поддержке Gateway API и простоте конфигурации.

**Добавление репозитория:**

```bash
helm repo add traefik https://traefik.github.io/charts
helm repo update
# → ...Successfully got an update from the "traefik" chart repository
```

**Создание конфигурации `traefik-values.yaml`:**

```yaml
# Оптимизация для промышленной эксплуатации
deployment:
  replicas: 3
  podAntiAffinity:
    enabled: true # Распределение подов по разным узлам

service:
  type: LoadBalancer
  annotations:
    # Пример для облака: включение Proxy Protocol
    service.beta.kubernetes.io/aws-load-balancer-proxy-protocol: "*"

metrics:
  prometheus:
    enabled: true # Сбор метрик для Prometheus

providers:
  kubernetesIngress:
    enabled: true # Поддержка классического Ingress
  kubernetesGateway:
    enabled: true # Активация Gateway API
```

**Развертывание:**

```bash
helm upgrade --install traefik traefik/traefik \
  --namespace ingress-system \
  --create-namespace \
  --values traefik-values.yaml \
  --wait --atomic
# → STATUS: deployed
```

### Сценарий 2 — Установка Envoy Gateway (Gateway API)

Envoy Gateway — это официальное решение CNCF для реализации Gateway API.

**Установка (актуально на 2026 год):**

```bash
helm repo add envoygateway https://envoyproxy.github.io/gateway-helm/
helm repo update

# Установка CRD (обязательный шаг перед основным чартом)
helm install eg-crds envoygateway/gateway-helm-crds \
  --namespace envoy-gateway-system --create-namespace

# Установка контроллера
helm install eg envoygateway/gateway-helm \
  --namespace envoy-gateway-system
# → NAME: eg
# → STATUS: deployed
```

### Сценарий 3 — Поддержка устаревших систем (Ingress-NGINX)

*Использовать только для миграции или поддержки legacy-проектов.*

```bash
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.replicaCount=2 \
  --wait
```

## Дополнительная информация

### Типичные ошибки при установке

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `context deadline exceeded` | Контроллер не успел пройти Health Check | Проверьте доступность портов и наличие ресурсов (CPU/RAM). Увеличьте `--timeout`. |
| `Pending` статус LoadBalancer | Облачный провайдер не смог выделить IP | Проверьте квоты в облаке и аннотации сервиса. |
| `CRD mismatch` | Версия CRD в кластере не совпадает с чартом | Обновите CRD вручную перед `helm upgrade`. |

### См. также

- **[Сравнение Ingress-контроллеров](../controllers_comparison.md)** — выбор между Envoy, Traefik и Cilium.
- **[Миграция на Gateway API](../../gateway_api/migration.md)** — переход с классических Ingress на современный стандарт.
- **[Ingress в Bare-Metal](./bare-metal-installation.md)** — особенности установки без облачного LoadBalancer.
