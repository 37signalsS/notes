# Ingress — ручная установка через манифесты (Bare-Metal)

> [!CAUTION]
> **Внимание (март 2026):** Проект `kubernetes/ingress-nginx` официально перешел в статус **End of Life (EOL)**. Поддержка прекращена. Для новых Bare-metal сред настоятельно рекомендуется использовать решения на базе **Gateway API** (например, **Envoy Gateway**) или современные контроллеры (**Traefik v3**, **Cilium Ingress**).

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

**1. Подготовка `kustomization.yaml`:**

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - https://github.com/traefik/traefik-helm-chart/raw/master/traefik/values.yaml # Пример абстрактный, обычно используются выгруженные манифесты
  - rbac.yaml
  - daemonset.yaml

patches:
  - path: patch-host-network.yaml
    target:
      kind: DaemonSet
      name: traefik
```

**2. Настройка hostNetwork (patch-host-network.yaml):**

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: traefik
spec:
  template:
    spec:
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet # Критично для резолвинга внутри K8s
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
# rbac.yaml (фрагмент)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ingress-controller
rules:
  - apiGroups: [""]
    resources: ["services", "endpoints", "nodes"]
    verbs: ["get", "list", "watch"]
```

## Дополнительная информация

### Рекомендации по оптимизации

-   **Ядро Linux:** При использовании `hostNetwork` убедитесь, что на Edge-нодах оптимизированы параметры `net.core.somaxconn` и `net.ipv4.ip_local_port_range`.
-   **Логирование:** Выносите логи в `stdout` в формате JSON для интеграции с Vector или Fluent Bit.
-   **Автоматизация:** Даже при ручной установке используйте ArgoCD или Flux для отслеживания изменений в репозитории манифестов.

### См. также

-   **[Сравнение Ingress-контроллеров](../controllers_comparison.md)** — актуальные альтернативы на 2026 год.
-   **[Настройка внешнего прокси (Bare-Metal)](../bare_metal_manual_proxy.md)** — архитектура с Nginx перед кластером.
-   **[MetalLB — LoadBalancer для Bare-metal](../../metallb.md)** — решение проблемы External IP.
