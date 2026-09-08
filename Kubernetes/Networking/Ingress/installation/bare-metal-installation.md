# Ingress — ручная установка через манифесты (Bare-Metal)

> [!CAUTION]
> **Внимание (2026):** Проект `kubernetes/ingress-nginx` официально перешел в статус **End of Life (EOL)**. Поддержка прекращена. Для новых Bare-metal сред настоятельно рекомендуется использовать решения на базе **Gateway API** (например, **Envoy Gateway**) или современные контроллеры (**Traefik v3**, **Cilium Ingress**).

## Предварительные требования

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Kubernetes** | 1.25+ | Кластер с поддержкой Ingress `networking.k8s.io/v1`. |
| **kubectl** | Совпадает с версией кластера | Управление ресурсами. Проверка: `kubectl version --client --short`. |
| **kubeconfig** | — | Настроенный доступ к кластеру. Проверка: `kubectl cluster-info`. |
| **Kustomize** | 3.10+ | Управление манифестами. Проверка: `kustomize version` (встроен в `kubectl kustomize`). |
| **Git** | 2.x | Хранение и версионирование манифестов. |
| **Доступ к OCI-реестру** | — | Кластер должен загружать образы контроллера. Для Air-gapped — локальный реестр. |
| **Сетевое оборудование** | — | Для MetalLB L2: коммутатор с поддержкой ARP. Для MetalLB BGP: маршрутизатор с BGP. |

> **Важно:** Если кластер использует NetworkPolicy, убедитесь, что Ingress-контроллер может принимать входящий трафик на портах 80/443 и отправлять запросы к Service в других неймспейсах.

---

## Определения

**Ручная установка (Manifest-based)** — метод развертывания Ingress-контроллера путем прямого применения YAML-манифестов. Этот подход обеспечивает максимальный контроль над ресурсами (`RBAC`, `ServiceAccount`, `DaemonSet`), что критично в изолированных (Air-gapped) сетях или при глубокой кастомизации под специфическое оборудование.

**hostNetwork** — режим работы пода, при котором он использует сетевой стек узла напрямую (порты 80/443 узла). Это исключает накладные расходы на `iptables/ipvs` и `kube-proxy`, обеспечивая максимальную производительность в Bare-Metal.

**Kustomize** — декларативный инструмент для настройки манифестов Kubernetes без их изменения (через наложения/overlays). Является стандартом для управления "сырыми" YAML-файлами.

## Базовые концепции

### Стратегии публикации в Bare-Metal

При отсутствии облачного `LoadBalancer`, выбор стратегии публикации контроллера определяет производительность и видимость клиентских IP:

1.  **NodePort (L4):**
    - **Плюсы:** Стандартный механизм K8s, простота настройки.
    - **Минусы:** Требует `externalTrafficPolicy: Local` для сохранения IP; ограничен диапазоном портов (30000+).
2.  **hostNetwork (L3/L4):**
    - **Плюсы:** Минимальные задержки; использование стандартных портов (80, 443) напрямую на узлах.
    - **Минусы:** Конфликты портов (на узле может быть только один контроллер); риски безопасности (под имеет доступ к сетевым сервисам узла).
3.  **MetalLB (L2/BGP):**
    - **Плюсы:** Эмуляция поведения облачного LoadBalancer.
    - **Минусы:** Требует поддержки со стороны сетевого оборудования или возможности ARP-анонсов.

### Выбор контроллера (DaemonSet vs Deployment)

В Bare-metal рекомендуется использовать **DaemonSet** с `nodeSelector` для запуска контроллера на выделенных "Edge-нодах". Это гарантирует предсказуемость маршрутизации внешнего трафика.

## Практические сценарии

### Сценарий 1 — Установка Traefik v3 через Kustomize

Traefik — современная замена устаревшим контроллерам. Ниже приведен пример структуры для ручной установки.

**1. Структура каталога:**

```
traefik-manifests/
├── base/
│   ├── kustomization.yaml
│   ├── rbac.yaml
│   ├── serviceaccount.yaml
│   ├── daemonset.yaml
│   └── service.yaml
└── overlays/
    └── production/
        ├── kustomization.yaml
        ├── patch-host-network.yaml
        └── patch-resources.yaml
```

**2. Базовый `kustomization.yaml` (base/):**

```yaml
# base/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - rbac.yaml
  - serviceaccount.yaml
  - daemonset.yaml
  - service.yaml
```

**3. Настройка hostNetwork (overlays/production/patch-host-network.yaml):**

```yaml
# overlays/production/patch-host-network.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: traefik
spec:
  template:
    spec:
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet
      containers:
      - name: traefik
        ports:
        - name: web
          containerPort: 80
          hostPort: 80
        - name: websecure
          containerPort: 443
          hostPort: 443
```

**4. Применение:**

```bash
# Просмотр сгенерированных манифестов
kubectl kustomize ./overlays/production

# Применение
kubectl apply -k ./overlays/production
# → namespace/ingress-system created
# → daemonset.apps/traefik created
```

### Сценарий 2 — Обслуживание Legacy Ingress-NGINX

Если миграция невозможна, используйте Kustomize для применения патчей безопасности вручную.

```bash
# Проверка манифестов перед применением
kubectl kustomize ./overlays/production > full-deploy.yaml

# Применение
kubectl apply -f full-deploy.yaml
# → namespace/ingress-nginx created
# → daemonset.apps/ingress-nginx-controller created
```

### Сценарий 3 — Настройка RBAC и лимитов

При ручной установке крайне важно ограничить привилегии контроллера.

```yaml
# rbac.yaml (полный пример)
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ingress-controller
  namespace: ingress-system
  labels:
    app.kubernetes.io/name: traefik
    app.kubernetes.io/part-of: ingress

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ingress-controller
  labels:
    app.kubernetes.io/name: traefik
rules:
  - apiGroups: [""]
    resources: ["services", "endpoints", "nodes", "pods", "secrets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses", "ingressclasses"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses/status"]
    verbs: ["update"]
  - apiGroups: ["traefik.io"]
    resources: ["*"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["create", "patch"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ingress-controller
  labels:
    app.kubernetes.io/name: traefik
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: ingress-controller
subjects:
  - kind: ServiceAccount
    name: ingress-controller
    namespace: ingress-system
```

> **Важно:** Не используйте `cluster-admin` для Ingress-контролера. Минимальные привилегии снижают риски при компрометации контейнера.

## Выбор стратегии публикации

Выбор между NodePort, hostNetwork и MetalLB зависит от требований к производительности, безопасности и сетевой инфраструктуры:

| Критерий | NodePort | hostNetwork | MetalLB |
| :--- | :--- | :--- | :--- |
| **Порты** | 30000–32767 | 80, 443 (стандартные) | 80, 443 (стандартные) |
| **Производительность** | Средняя (iptables/ipvs) | Высокая (прямой доступ) | Высокая (L2: один узел; BGP: ECMP) |
| **Сохранение IP клиента** | Только с `externalTrafficPolicy: Local` | Да | Да (L2 и BGP) |
| **Количество контроллеров** | Несколько (через NodePort) | Один на кластер | Несколько (через LoadBalancer) |
| **Требования к сети** | Нет | Нет | L2: ARP. BGP: маршрутизатор |
| **Конфликты портов** | Нет | Да (только один контроллер) | Нет |
| **Безопасность** | Средняя | Низкая (доступ к хост-сети) | Средняя |
| **Рекомендация** | Простые среды, миграция | Высокопроизводительные, Edge | Production без облачного LB |

> **Подробнее:** [Внешний доступ в Bare-metal](../bare_metal_manual_proxy.md) — архитектура с внешним Nginx-прокси перед кластером.

---

## Верификация установки

После применения манифестов выполните проверку:

### Шаг 1 — Namespace и Podы

```bash
kubectl get pods -n ingress-system
# → NAME                          READY   STATUS    RESTARTS   AGE
# → traefik-abc123-def45          1/1     Running   0          2m

# Если статус CrashLoopBackOff — проверьте логи:
kubectl logs -n ingress-system <pod-name> --tail=50
```

### Шаг 2 — Сервис и внешний доступ

```bash
# Для NodePort:
kubectl get svc -n ingress-system
# → NAME      TYPE       CLUSTER-IP     EXTERNAL-IP   PORT(S)
# → traefik   NodePort   10.43.100.20   <none>        80:31080/TCP,443:31443/TCP

# Доступ: http://<NODE-IP>:31080

# Для hostNetwork:
kubectl get pods -n ingress-system -o wide
# → NODE              IP             READY
# → worker-1          192.168.1.10   1/1

# Доступ: http://192.168.1.10:80
```

### Шаг 3 — IngressClass

```bash
kubectl get ingressclass
# → NAME      CONTROLLER              PARAMETERS   AGE
# → traefik   traefik.io/ingress       <none>       5m

# Проверка класса по умолчанию
kubectl get ingressclass -o jsonpath='{range .items[?(@.metadata.annotations.ingressclass\.kubernetes\.io/is-default-class=="true")]}{.metadata.name}{"\n"}{end}'
```

### Шаг 4 — Тестовый Ingress

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

### Шаг 5 — Проверка логов контроллера

```bash
# Трафик должен проходить через контроллер
kubectl logs -n ingress-system -l app.kubernetes.io/name=traefik --tail=10
# → ... "GET / HTTP/1.1" 200 1034 "-" "curl/8.0"
```

---

## Безопасность в Bare-Metal

### Сетевая изоляция

```yaml
# network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: ingress-allow-external
  namespace: ingress-system
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: traefik
  policyTypes:
  - Ingress
  ingress:
  - from: []  # Весь входящий трафик
    ports:
    - port: 80
      protocol: TCP
    - port: 443
      protocol: TCP
  - from: []  # Разрешить Health Check от kubelet
    ports:
    - port: 10254
      protocol: TCP
```

### Ограничение доступа к хосту

```yaml
# В DaemonSet/Deployment контейнера:
securityContext:
  runAsNonRoot: true
  runAsUser: 100
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL
  seccompProfile:
    type: RuntimeDefault
```

### Защита髓核настроек

```bash
# Запрет изменения sysctl для Ingress-подов
kubectl label pod <pod-name> \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/audit=restricted \
  pod-security.kubernetes.io/warn=restricted
```

---

## Мониторинг и наблюдаемость

### Проверка подов и ресурсов

```bash
# Использование ресурсов
kubectl top pods -n ingress-system
# → NAME                        CPU(cores)   MEMORY(bytes)
# → traefik-abc123              12m          45Mi

# Распределение по узлам
kubectl get pods -n ingress-system -o wide
```

### Логирование

```bash
# Логи контроллера в реальном времени
kubectl logs -n ingress-system -l app.kubernetes.io/name=traefik -f

# Фильтрация по уровню
kubectl logs -n ingress-system -l app.kubernetes.io/name=traefik | grep -i "error"
```

### Метрики (если включены)

```bash
# Traefik: метрики доступны на порту 9100
kubectl port-forward -n ingress-system svc/traefik 9100:9100
curl http://localhost:9100/metrics
# → traefik_config_reloads_total 1
# → traefik_entrypoint_open_connections 0
```

> **Подробнее:** [Настройка Prometheus для Ingress-контроллеров](../overview.md#мониторинг-ingress-контроллеров) — ServiceMonitor и Grafana-дашборды.

---

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Pod в статусе `CrashLoopBackOff`** | Ошибка конфигурации или нехватка прав | `kubectl logs <pod>` — проверьте вывод. Убедитесь, что RBAC и ServiceAccount корректны. |
| **Pod в статусе `ImagePullBackOff`** | Кластер не может загрузить образ | Проверьте доступность OCI-реестра. Для Air-gapped: настройте локальный реестр и `imagePullSecrets`. |
| **NodePort не отвечает** | Firewall блокирует порт 30000–32767 | `ss -ltnp | grep 31080` — проверьте, слушает ли порт. Настройте firewall: `firewall-cmd --add-port=31080/tcp`. |
| **hostNetwork: порт занят** | Другой процесс использует порт 80/443 | `ss -ltnp | grep :80` — найдите процесс. Остановите его или измените порт контроллера. |
| **MetalLB: сервис в `PENDING`** | MetalLB не назначен IP | `kubectl describe svc <name>` — проверьте Events. Убедитесь, что IPAddressPool и L2Advertisement настроены. |
| **Ingress не маршрутизирует трафик** | Неправильный `ingressClassName` или host | `kubectl get ingress <name> -o yaml` — проверьте `spec.ingressClassName` и `spec.rules[].host`. |
| **DNS не резолвит внутри пода с hostNetwork** | Отсутствует `dnsPolicy: ClusterFirstWithHostNet` | Добавьте `dnsPolicy: ClusterFirstWithHostNet` в PodSpec. |

---

## Обновление манифестов

### Пошаговое обновление

```bash
# 1. Обновите манифесты в репозитории
git pull origin main

# 2. Просмотр изменений
kubectl diff -k ./overlays/production

# 3. Применение с контролем
kubectl apply -k ./overlays/production --server-side

# 4. Проверка после обновления
kubectl rollout status daemonset/traefik -n ingress-system
```

### Откат при ошибке

```bash
# Если новая версия нестабильна — откат к предыдущему коммиту
git checkout <previous-commit-hash>
kubectl apply -k ./overlays/production

# Или ручное удаление и повторное применение
kubectl delete -k ./overlays/production
kubectl apply -k ./overlays/production
```

---

## Дополнительная информация

### Рекомендации по оптимизации

-   **Ядро Linux:** При использовании `hostNetwork` убедитесь, что на Edge-нодах оптимизированы параметры `net.core.somaxconn` и `net.ipv4.ip_local_port_range`.
-   **Логирование:** Выносите логи в `stdout` в формате JSON для интеграции с Vector или Fluent Bit.
-   **Автоматизация:** Даже при ручной установке используйте ArgoCD или Flux для отслеживания изменений в репозитории манифестов.
-   **Ресурсы:** Всегда задавайте `resources.requests` и `resources.limits` для контейнера контроллера. Для Traefik: 100m CPU / 128Mi RAM (requests), 500m CPU / 256Mi RAM (limits).

### См. также

-   **[Сравнение Ingress-контроллеров](../controllers_comparison.md)** — актуальные альтернативы на 2026 год.
-   **[Настройка внешнего прокси (Bare-Metal)](../bare_metal_manual_proxy.md)** — архитектура с Nginx перед кластером.
-   **[MetalLB — LoadBalancer для Bare-metal](../../Networking/metallb.md)** — решение проблемы External IP.
-   **[Ingress — установка через Helm](./helm-installation.md)** — альтернатива ручной установке.
-   **[Ingress — обзор](../overview.md)** — базовые концепции, аннотации, мониторинг.
