# Ingress — установка через Helm

> [!WARNING]
> **Статус проектов (2026):** Проект `kubernetes/ingress-nginx` официально перешел в статус **End of Life (EOL)**. Поддержка прекращена, критические патчи безопасности не выпускаются. Для новых инсталляций настоятельно рекомендуется использовать **Traefik v3**, **Envoy Gateway** или другие современные реализации на базе **Gateway API**.

## Предварительные требования

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Kubernetes** | 1.25+ | Кластер с поддержкой актуальных API (Ingress `networking.k8s.io/v1` и Gateway API). |
| **Helm** | 3.10+ | Менеджер пакетов. Проверка: `helm version --short`. |
| **kubectl** | Совпадает с версией кластера | Управление ресурсами. Проверка: `kubectl version --client --short`. |
| **kubeconfig** | — | Настроенный доступ к кластеру. Проверка: `kubectl cluster-info`. |
| **Доступ к OCI-реестру** | — | Чарты хранятся в Helm OCI-реестрах (ghcr.io, Docker Hub, Harbor). Убедитесь, что кластер может загружать образы. |

> **Важно:** Если кластер использует NetworkPolicy, убедитесь, что Ingress-контроллер может принимать входящий трафик на портах 80/443 и отправлять запросы к Service в других неймспейсах.

---

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
  annotations: {}
    # Пример для bare-metal без внешнего LB: используйте MetalLB
    # с аннотацией metallb.universe.tf/address-pool: "ingress-pool"
    # или NodePort при отсутствии балансировщика

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

## Выбор контроллера

Перед установкой определитесь с контроллером. Краткое руководство:

| Сценарий | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **Новый кластер, чистый стек** | Traefik v3 + Gateway API | Нативная поддержка Gateway API, простая конфигурация, встроенный Let's Encrypt. |
| **Высокая производительность, L4/L7** | Envoy Gateway | Масштабируемость на уровне Envoy, строгое соответствие Gateway API. |
| **Минимальные ресурсы, eBPF** | Cilium Ingress | Интеграция с CNI, маршрутизация на уровне ядра. |
| **Legacy-система, быстрый старт** | ingress-nginx | Знакомый API, минимум настройки. **Только для миграции.** |

> **Подробнее:** [Сравнение Ingress-контроллеров](../controllers_comparison.md) — детальный анализ 8 решений с критериями выбора.

---

## Полезные команды Helm

### Управление репозиториями

```bash
# Добавление репозитория
helm repo add traefik https://traefik.github.io/charts
# → "traefik" has been added to your repositories

# Обновление списка чартов
helm repo update
# → ...Successfully got an update from the "traefik" chart repository

# Просмотр доступных версий
helm search repo traefik/traefik
# → NAME              CHART VERSION   APP VERSION   DESCRIPTION
# → traefik/traefik    34.3.0          3.3.4         Traefik helm chart
```

### Установка и обновление

```bash
# Установка (или обновление, если уже установлен)
helm upgrade --install <release> <chart> \
  --namespace <ns> --create-namespace \
  --values values.yaml \
  --wait --atomic
# → STATUS: deployed

# Флаги:
# --atomic      откат при неудачном обновлении
# --wait        ожидание готовности всех подов
# --timeout     таймаут ожидания (по умолчанию 5m0s)
# --cleanup-on-fail удаление новых ресурсов при ошибке
```

### Проверка статуса

```bash
# Список всех установленных релизов
helm list -A
# → NAME        NAMESPACE   REVISION   STATUS     CHART           APP VERSION
# → traefik     ingress     1          deployed   traefik-34.3.0  3.3.4

# Детали конкретного релиза
helm status <release> -n <ns>
# → STATUS: deployed
# → REVISION: 1

# Просмотр значений по умолчанию чарта
helm show values traefik/traefik
```

### История и откат

```bash
# История релиза (последние 10 ревизий)
helm history <release> -n <ns>
# → REVISION   STATUS     CHART           DESCRIPTION
# → 1          superseded traefik-33.2.0  Initial install
# → 2          deployed   traefik-34.3.0  Upgrade

# Откат к предыдущей ревизии
helm rollback <release> <revision> -n <ns>
# → Release "traefik" has been rolled back.

# Откат к конкретной ревизии
helm rollback <release> 1 -n <ns>
```

### Удаление

```bash
# Удаление релиза (ресурсы k8s остаются)
helm uninstall <release> -n <ns>
# → release "traefik" uninstalled

# Удаление вместе с ресурсами k8s
helm uninstall <release> -n <ns> --no-hooks
```

---

## Верификация установки

После `helm upgrade --install` выполните проверку:

### Шаг 1 — Статус релиза

```bash
helm status <release> -n <ns>
# → STATUS: deployed (если всё ОК)
# → STATUS: pending-upgrade / pending-install (если есть проблемы)
```

### Шаг 2 — Podы контроллера

```bash
kubectl get pods -n <ns>
# → NAME                          READY   STATUS    RESTARTS   AGE
# → traefik-abc123-def45          1/1     Running   0          2m
# → traefik-ghi789-jkl01          1/1     Running   0          2m

# Если статус CrashLoopBackOff — проверьте логи:
kubectl logs -n <ns> <pod-name> --tail=50
```

### Шаг 3 — Сервис и внешний IP

```bash
kubectl get svc -n <ns>
# → NAME      TYPE           CLUSTER-IP     EXTERNAL-IP     PORT(S)
# → traefik   LoadBalancer   10.43.100.20   192.168.1.100   80:31234/TCP,443:31235/TCP

# Если EXTERNAL-IP = <pending> — балансировщик не назначен.
# Для bare-metal: установите MetalLB или используйте NodePort.
```

### Шаг 4 — IngressClass

```bash
kubectl get ingressclass
# → NAME      CONTROLLER              PARAMETERS   AGE
# → traefik   traefik.io/ingress       <none>       5m

# Проверка класса по умолчанию
kubectl get ingressclass -o jsonpath='{range .items[?(@.metadata.annotations.ingressclass\.kubernetes\.io/is-default-class=="true")]}{.metadata.name}{"\n"}{end}'
```

### Шаг 5 — Тестовый Ingress

```yaml
# test-ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: test-ingress
  namespace: default
spec:
  ingressClassName: traefik
  rules:
  - host: test.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: kubernetes
            port:
              number: 80
```

```bash
kubectl apply -f test-ingress.yaml
curl -H "Host: test.example.com" http://<EXTERNAL-IP>
# → Should return Kubernetes API response or 403/404 from default backend
```

---

## Пост-установочная настройка

### Настройка Default Backend

Default backend обрабатывает запросы, не соответствующие ни одному правилу Ingress:

```bash
# NGINX Ingress — default backend уже встроен в чарт
# Traefik — deploy, Traefik автоматически возвращает 404 для неизвестных хостов

# Кастомный default backend:
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: default-backend
  namespace: ingress-system
spec:
  selector:
    matchLabels:
      app: default-backend
  template:
    metadata:
      labels:
        app: default-backend
    spec:
      containers:
      - name: default-backend
        image: registry.k8s.io/defaultbackend-amd64:1.5
        ports:
        - containerPort: 8080
        resources:
          requests:
            cpu: 10m
            memory: 20Mi
          limits:
            cpu: 50m
            memory: 64Mi
EOF
```

### Настройка TLS с cert-manager

```bash
# Установка cert-manager (если еще не установлен)
helm repo add jetstack https://charts.jetstack.io
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --set crds.enabled=true

# Интеграция с Ingress через аннотации:
# cert-manager.io/cluster-issuer: "letsencrypt-prod"
```

> **Подробнее:** [Cert-manager: Интеграция с Ingress](../../../ToolsUtilities/cert_manager/ingress/overview.md).

---

## Обновление и откат

### Обновление чарта

```bash
# Обновление с новыми значениями
helm upgrade <release> <chart> \
  --namespace <ns> \
  --values new-values.yaml \
  --wait --atomic

# Обновление репозитория перед обновлением
helm repo update
helm upgrade <release> <chart> --reuse-values  # сохранить текущие значения
```

### Откат при ошибке

```bash
# Автоматический откат (--atomic)
helm upgrade --install <release> <chart> \
  --namespace <ns> --atomic --timeout 5m
# → При ошибке: Release "traefik" has been rolled back.

# Ручной откат
helm history <release> -n <ns>
helm rollback <release> <previous-revision> -n <ns>
```

### Очистка неиспользуемых релизов

```bash
# Удаление релиза в статусе "failed"
helm uninstall <release> -n <ns>

# Очистка ConfigMaps с историями релизов (осторожно!)
kubectl delete configmap -n kube-system -l name=<release>,owner=helm
```

---

## Дополнительная информация

### Типичные ошибки при установке

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `context deadline exceeded` | Контроллер не успел пройти Health Check | Проверьте ресурсы (CPU/RAM). Увеличьте `--timeout`. |
| `Pending` статус LoadBalancer | Балансировщик не назначен | Установите MetalLB (bare-metal) или проверьте квоты облачного провайдера. |
| `CRD mismatch` | Версия CRD в кластере не совпадает с чартом | Обновите CRD вручную перед `helm upgrade`. |
| `OOMKilled` | Контроллер потребляет больше RAM, чем задано | Увеличьте `resources.limits.memory` в values. |
| `ImagePullBackOff` | Кластер не может загрузить образ контроллера | Проверьте доступность OCI-реестра и Secret для pull. |
| `Forbidden (RBAC)` | Недостаточно прав для создания ресурсов | Убедитесь, что ServiceAccount имеет необходимые ClusterRole/ClusterRoleBinding. |

### Дополнительные ресурсы

- **[Сравнение Ingress-контроллеров](../controllers_comparison.md)** — выбор между NGINX, Traefik, Envoy, Cilium и HAProxy.
- **[Миграция на Gateway API](../../gateway_api/migration.md)** — пошаговое руководство по переходу с Ingress.
- **[Ingress в Bare-Metal](./bare-metal-installation.md)** — установка через манифесты без Helm.
