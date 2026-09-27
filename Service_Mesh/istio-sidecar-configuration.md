# Конфигурация Sidecar в Istio

## Определения

**Sidecar (ресурс)** — пользовательский ресурс Istio (`networking.istio.io/v1beta1`), позволяющий тонко настраивать поведение [сайдкар-прокси](./proxy_sidecar.md) для конкретных рабочих нагрузок или неймспейсов. В архитектуре 2026 года ресурс Sidecar остается основным инструментом оптимизации для классической модели инъекции, сосуществуя с [Ambient Mesh](./istio_architecture.md).

**Egress Control (управление исходящим трафиком)** — механизм ограничения видимости сервисов для прокси. По умолчанию прокси знает обо всех эндпоинтах кластера, что создает нагрузку на Control Plane и увеличивает потребление RAM прокси-сервером.

**Ingress Control (управление входящим трафиком)** — настройка параметров приема трафика прокси-сервером, включая привязку к портам, протоколам и режимам TLS для входящих соединений.

**Permissive Mode (поверхностный режим)** — режим работы меша по умолчанию, при котором разрешён как зашифрованный (mTLS), так и открытый (Plain Text) трафик. Это позволяет постепенно внедрять Istio в существующие неймспейсы.

---

## Основные концепции

### Видимость и xDS-оптимизация
По умолчанию каждый `istio-proxy` получает информацию обо всех сервисах во всех неймспейсах кластера. В крупных инсталляциях (1000+ сервисов) это приводит к критическим проблемам:
- **Потребление RAM:** до 200MB–1GB на каждый прокси-контейнер.
- **Задержки обновлений:** увеличение времени распространения xDS-конфигурации от `istiod` к прокси.
- **Нагрузка на Control Plane:** `istiod` вынужден вычислять полный граф зависимостей для каждого сайдкара.

Использование ресурса `Sidecar` ограничивает **Discovery Scope** (область обнаружения), сокращая объем конфигурации на 80–90%.

### Поведение по умолчанию
При включении автоматической инъекции (`istio-injection=enabled`) применяется стандартное поведение:
1.  **Перехват:** прокси перехватывает весь входящий и исходящий трафик пода через `iptables` или eBPF.
2.  **Полная видимость:** прокси получает конфигурацию для всех сервисов кластера (`hosts: ["*/*"]`).
3.  **Безопасность:** mTLS включен в режиме `PERMISSIVE`.
4.  **Функции:** доступны балансировка, таймауты, ретраи, сбор метрик и логирование.

### Жизненный цикл и нативные сайдкары
В Kubernetes 1.33+ прокси запускаются как **Native Sidecar Containers** (`initContainers` с `restartPolicy: Always`). Это гарантирует:
- Запуск прокси строго до старта приложения.
- Завершение прокси только после остановки основных контейнеров (решает проблему зависших Job).
- Использование `holdApplicationUntilProxyStarts: true` (по умолчанию в 1.29+) для предотвращения race conditions.

### API и стабильность
Ресурс `Sidecar` поддерживается в API `networking.istio.io/v1beta1`. В текущих версиях Istio 1.30+ API является стабильным и обратно совместимым. Прямое редактирование `spec` поля `egress` или `ingress` не требует перезапуска пода — `istiod` отправляет дельту xDS-конфигурации.

### Взаимодействие с MeshConfig и outboundTrafficPolicy
Поведение прокси также зависит от глобального параметра `MeshConfig.outboundTrafficPolicy`:
- **ALLOW_ANY (по умолчанию):** трафик к сервисам, не описанным в mesh (нет `DestinationRule`/`ServiceEntry`), проходит через прокси в режиме passthrough. Sidecar ресурс не блокирует такой трафик.
- **REGISTRY_ONLY:** трафик только к известным сервисам кластера. Для внешних сервисов необходимо создавать `ServiceEntry`.

Комбинация `REGISTRY_ONLY` + ограничительный `Sidecar` (только `./*` и `istio-system/*`) создает default-deny для всего, что не разрешено явно.

### Аннотация proxy.istio.io/config
Помимо ресурса `Sidecar`, конфигурацию прокси можно переопределить через аннотацию `proxy.istio.io/config` на Pod или Deployment в формате JSON. Используется для тонкой настройки параметров, не покрываемых ресурсом Sidecar (например, `holdApplicationUntilProxyStarts`, `tracing`, `accessLogFile`).

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  annotations:
    proxy.istio.io/config: |
      {
        "holdApplicationUntilProxyStarts": true,
        "accessLogFile": "/dev/stdout"
      }
```

### Иерархия и wildcards в hosts
Поле `hosts` поддерживает иерархическую нотацию:
- `*/*` — все сервисы во всех неймспейсах.
- `./*` — все сервисы в текущем неймспейсе (содержащем ресурс Sidecar).
- `istio-system/*` — сервисы в неймспейсе управления.
- `external/*` — сервисы, добавленные через `ServiceEntry` в неймспейсе `istio-system`.

При пересечении правил более специфичное правило имеет приоритет. Resource `Sidecar` в неймспейсе `istio-system` с `hosts: ["./*"]` не даст эффекта для workload в других неймспейсах.

---

## Практические сценарии

### 1. Глобальная конфигурация по умолчанию
Рекомендуется создать базовый ресурс `Sidecar` в неймспейсе `istio-system`. Он ограничит видимость для всех подов в кластере, у которых нет специфичных настроек.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: Sidecar
metadata:
  name: default
  namespace: istio-system
spec:
  egress:
  - hosts:
    - "./*"            # Видимость сервисов внутри своего неймспейса
    - "istio-system/*" # Видимость управляющих компонентов Istio
```

### 2. Ограничение исходящего трафика для неймспейса
В этом примере поды в неймспейсе `payments` смогут обращаться только к сервисам в своем неймспейсе, в `istio-system` и в неймспейсе `app`.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: Sidecar
metadata:
  name: default
  namespace: payments
spec:
  egress:
  - hosts:
    - "./*"            # Текущий неймспейс
    - "istio-system/*"
    - "app/*"          # Дополнительный разрешенный неймспейс
```

**Важные примечания:**
- `*/*` — wildcard для всех сервисов (поведение по умолчанию).
- Если сервис не входит в список `hosts`, попытка обращения к нему приведет к ошибке **Empty reply from server** (в логах Envoy — код `UH`, No Healthy Upstream).

### 3. Настройка входящего трафика (Ingress)
Позволяет переопределить способ обработки входящих соединений, например, для изоляции портов.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: Sidecar
metadata:
  name: ingress-restriction
  namespace: prod
spec:
  ingress:
  - port:
      number: 9090
      protocol: HTTP
      name: metrics
    defaultEndpoint: 127.0.0.1:9090
```

### 4. Таргетинг на конкретные поды (Workload Selector)
Выборочное применение политики только к подам с определенной меткой.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: Sidecar
metadata:
  name: restrict-test-egress
  namespace: test
spec:
  workloadSelector:
    labels:
      run: test
  egress:
  - hosts:
    - "istio-system/*"
    - "./*"
```

### 5. Per-service scoping для критичного deployment
Ограничение видимости для конкретного deployment в неймспейсе `prod` только его базой данных и Istio-компонентами. Это исключает утечку информации о других сервисах и снижает нагрузку на xDS.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: Sidecar
metadata:
  name: payment-service-scope
  namespace: prod
spec:
  workloadSelector:
    matchLabels:
      app: payment-service
  egress:
  - hosts:
    - "prod/*"              # Сервисы в том же неймспейсе
    - "prod/payment-db/*"   # Конкретный сервис БД
    - "istio-system/*"
```

**Проверка:**
```bash
istioctl proxy-config clusters deploy/payment-service -n prod
# → Список должен содержать только payment-db и istio-system сервисы
```

### 6. Блокировка внешнего трафика через outboundTrafficPolicy
Использование `MeshConfig.outboundTrafficPolicy: REGISTRY_ONLY` вместе с ресурсом `Sidecar` создает default-deny для всех неизвестных сервисов. Это предотвращает случайные исходящие вызовы к внешним API.

```yaml
# meshConfig в IstioOperator или Helm values
meshConfig:
  outboundTrafficPolicy:
    mode: REGISTRY_ONLY
```

```yaml
# Sidecar ресурс для namespace frontend
apiVersion: networking.istio.io/v1beta1
kind: Sidecar
metadata:
  name: default
  namespace: frontend
spec:
  egress:
  - hosts:
    - "./*"
    - "backend/*"
    - "istio-system/*"
```

### 7. Взаимодействие с ServiceEntry
Если Sidecar ограничивает `egress.hosts`, доступ к внешним сервисам через `ServiceEntry` должен быть добавлен явно. Иначе прокси вернет `No Healthy Upstream`.

```yaml
# ServiceEntry для внешнего API
apiVersion: networking.istio.io/v1beta1
kind: ServiceEntry
metadata:
  name: external-api
  namespace: payments
spec:
  hosts:
  - api.external-provider.com
  ports:
  - number: 443
    name: https
    protocol: TLS
  location: MESH_EXTERNAL
```

```yaml
# Sidecar ресурс с явным разрешением внешнего хоста
apiVersion: networking.istio.io/v1beta1
kind: Sidecar
metadata:
  name: default
  namespace: payments
spec:
  egress:
  - hosts:
    - "./*"
    - "istio-system/*"
    - "external/api.external-provider.com/*"  # Явное разрешение
```

### 8. Миграция с полной видимости на scoped конфигурацию
Поэтапный переход без прерывания трафика. Сначала создайте ресурс Sidecar в отдельном неймспейсе и проверьте работу. Затем распространите на продакшен.

```bash
# 1. Создайте Sidecar в тестовом неймспейсе
kubectl apply -f sidecar-scoped.yaml -n test

# 2. Проверьте, что сервисы доступны
istioctl proxy-config clusters deploy/my-app -n test | wc -l
# → Должно быть меньше, чем до применения

# 3. Проверьте доступность критичных сервисов
kubectl exec -it deploy/my-app -n test -- curl -s http://payment-db.prod.svc.cluster.local/health

# 4. Если всё ок — примените в продакшен неймспейсах
kubectl apply -f sidecar-scoped.yaml -n prod
```

### 9. GitOps-автоматизация применения Sidecar
В инфраструктуре с ArgoCD или Flux ресурсы Sidecar хранятся в Git-репозитории и применяются автоматически. Это обеспечивает reproducible конфигурацию и аудит изменений.

```yaml
# ArgoCD Application для управления Sidecar ресурсами
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: istio-sidecar-config
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/istio-config.git
    targetRevision: HEAD
    path: overlays/prod/sidecars
  destination:
    server: https://kubernetes.default.svc
    namespace: istio-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### 10. Взаимодействие с AuthorizationPolicy
Ресурс `Sidecar` ограничивает видимость сервисов для прокси, но не заменяет `AuthorizationPolicy`. После применения scoped Sidecar убедитесь, что политики авторизации применяются только к видимым сервисам. Иначе запрос к невидимому сервису завершится `No Healthy Upstream` до проверки политик.

```bash
# Проверка: какой сервис возвращает 503
istioctl proxy-config log deploy/my-app -n prod | grep -i "uh\|no healthy upstream"

# Если нужный сервис не виден — добавьте его в Sidecar.egress.hosts
```

---

## Взаимодействие с PeerAuthentication

Поведение сайдкар-прокси при приеме трафика зависит от политик аутентификации.

| Режим PeerAuthentication | Поведение Sidecar | Совместимость |
| :--- | :--- | :--- |
| **PERMISSIVE** (default) | Принимает mTLS и Plain Text. | Разрешает входящий трафик от подов БЕЗ сайдкара. |
| **STRICT** | Принимает ТОЛЬКО mTLS. | Блокирует трафик от подов БЕЗ сайдкара (**Connection reset by peer**). |

**Сценарий отладки:**
Если в неймспейсе `default` установлена политика `STRICT`, а из неймспейса `test` (где инъекция выключена) идет запрос к `default`, запрос завершится ошибкой, так как клиент не может инициировать mTLS-соединение.

---

## Диагностика

### 1. Проверка инъекции
`kubectl get pods -n <ns>` — в колонке `READY` должно быть `2/2` (или `1/1` для native sidecar при наличии двух контейнеров в `describe pod`).

### 2. Анализ конфигурации прокси
```bash
# Проверка кластеров (сервисов), известных прокси
istioctl proxy-config clusters <pod-name>.<ns>

# Проверка слушателей (портов)
istioctl proxy-config listeners <pod-name>.<ns>
```
Если используется ресурс `Sidecar` с ограничениями, список кластеров будет значительно короче.

### 3. Проверка видимости и hosts
```bash
# Проверка, что ресурс Sidecar применен
kubectl get sidecar -n <ns>

# Проверка egress.hosts в ресурсе
kubectl get sidecar <name> -n <ns> -o jsonpath='{.spec.egress[*].hosts}'
```

### 4. Проверка outboundTrafficPolicy
```bash
# Проверка глобального режима трафика
kubectl -n istio-system get cm istio -o jsonpath='{.data.mesh}' | grep -A2 outboundTrafficPolicy
# → "mode": "REGISTRY_ONLY" или "ALLOW_ANY"
```

### 5. Логи Envoy
- `Empty reply from server` / `UH` — скорее всего, сервис назначения не добавлен в список `egress.hosts` ресурса `Sidecar`.
- `Connection reset by peer` — сработала политика `PeerAuthentication: STRICT`, а у отправителя нет прокси.
- `No Healthy Upstream` — эндпоинт не Ready или отсутствует в `egress.hosts`.

### 6. Проверка статуса синхронизации
```bash
istioctl proxy-status
```

### 7. Проверка ресурсов сайдкара
```bash
# Фактическое потребление CPU и RAM
kubectl top pod <pod-name> -n <ns> -c istio-proxy

# Количество известных кластеров (индикатор перегрузки xDS)
istioctl proxy-config clusters <pod-name> -n <ns> | wc -l
```

---

## Типичные ошибки и устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **mTLS handshake failure** | `PeerAuthentication: STRICT` на сервере, а клиент без сайдкара | Включите инъекцию для клиента или переведите в `PERMISSIVE` |
| **Pods не получают IP из меша** | CNI не перехватывает трафик | Проверьте метки CNI DaemonSet; убедитесь, что `istio-cni-node` Ready |
| **Waypoint не создаётся** | Нет Gateway API CRD или недостаточно прав | Установите Gateway API; проверьте RBAC для `istiod` |
| **Высокий CPU на ноде от Ztunnel** | Конфликт правил iptables/nftables | Переключите на `nftables`; проверьте количество правил |
| **Сервис не обнаруживается (No Healthy Upstream)** | Эндпоинт не Ready или отсутствует в `egress.hosts` | Добавьте namespace в `Sidecar.egress.hosts`; проверьте readiness probe |
| **Сертификат истёк (certificate expired)** | CA не выпустил новый сертификат | Проверьте `istioctl proxy-config secret`; перезапустите istiod при необходимости |
| **xDS синхронизация отстаёт** | `istiod` перегружен или сетевой разрыв | Проверьте CPU/memory istiod; убедитесь в отсутствии NetworkPolicy |
| **Access-логи не пишутся** | Telemetry API не настроен | Примените ресурс `Telemetry` с `accessLogging` |
| **JWT не проверяется (401 без логов)** | `RequestAuthentication` не совпадает с заголовком | Проверьте `issuer`, `jwksUri`, `audiences` |
| **L7-политика не применяется в Ambient** | Waypoint не создан или неймспейс не аннотирован | Создайте Waypoint; проверьте `istio.io/use-waypoint` |
| **AuthorizationPolicy позволяет больше, чем нужно** | Правило `ALLOW` слишком широкое | Уточните `matchLabels`/`matchExpressions` в `selector` |
| **Ресурс Sidecar не применяется** | Неверный namespace или имя | Проверьте `metadata.namespace` и `metadata.name` |

---

## Лучшие практики эксплуатации

1.  **Ресурсные квоты:** всегда устанавливайте `requests` и `limits` для сайдкаров. В 2026 году Envoy требует ~0.5 vCPU и 50MB RAM на 1,000 RPS. Для Native Sidecar используйте `requests.cpu: 50m` и `requests.memory: 64Mi` как минимум; лимиты — `cpu: 200m`, `memory: 128Mi`.
2.  **Gateway API стандартизация:** используйте Gateway API (GAMMA) как основной интерфейс для управления трафиком. Legacy API (`VirtualService`, `DestinationRule`) поддерживается, но новые проекты должны использовать Gateway API.
3.  **Scoping:** ограничивайте `egress.hosts` до минимально необходимого набора. Избегайте `*/*` в продакшене.
4.  **Постепенное внедрение:** начинайте с Ambient L4 (mTLS) для всего кластера, затем добавляйте Waypoint Proxy только для сервисов, требующих L7. При переходе с Sidecar оставляйте оба режима параллельно 2–4 недели.
5.  **Мониторинг Ztunnel:** настройте алерты на использование ресурсов Ztunnel, так как он обслуживает все поды на ноде.
6.  **eBPF-акселерация:** при использовании CNI (Cilium, Calico VPP), включайте SOCKMAP для обхода TCP-стека ядра между приложением и прокси. Это снижает задержки на 15–20%.
7.  **Ротация сертификатов:** настройте автоматическую ротацию trust anchors перед истечением срока (рекомендуемый срок — 90 дней для промежуточных CA). Используйте `istioctl proxy-config secret` для проверки.
8.  **Валидация после изменений:** после изменения ресурсов `Sidecar`, `VirtualService` или `DestinationRule` выполняйте `istioctl analyze` и `istioctl proxy-status` для подтверждения распространения конфигурации.
9.  **Бэкап конфигурации:** регулярно экспортируйте ресурсы Istio и ConfigMap `istio` в `istio-system`.
10. **Изоляция сред:** разделяйте кластеры по окружениям (dev/staging/prod) разными неймспейсами или отдельными кластерами.
11. **Namespace-scoped политики:** применяйте ресурс `Sidecar` на уровне неймспейса, а не кластера, для упрощения управления и отката.
12. **Проверка селекторов:** перед применением ресурса с `workloadSelector` убедитесь, что метки существуют и не конфликтуют с другими политиками.

---

## Дополнительная информация

- [Прокси Sidecar: реализации и сценарии](./proxy_sidecar.md) — детали нативных сайдкаров и архитектуры Envoy.
- [Архитектура Istio и Ambient Mesh](./istio_architecture.md) — обзор альтернативной модели без сайдкаров.
- [Политики безопасности Istio](./istio-security-policies.md) — mTLS, авторизация и аутентификация.
- [Установка Istio и базовый troubleshooting](./istio_installation.md) — инъекция, миграция на Ambient, проверка CNI.
- [Ограничение скорости (Rate Limiting) в Istio](./istio_rate_limiting.md) — rate limiting через EnvoyFilter.
- [Интеграция виртуальных машин (VM Workloads) в Istio](./istio_vm_workloads.md) — WorkloadEntry/WorkloadGroup.

Документация: [Istio Sidecar Resource Reference](https://istio.io/latest/docs/reference/config/networking/sidecar/).
