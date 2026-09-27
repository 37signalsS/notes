**Актуально для:** Kubernetes 1.29+, NGINX Ingress Controller 1.9+, cert-manager 1.14+, Argo CD 2.12+, Flux v2.3+, Cosign v3.1+

# Деплой фронтенда в Kubernetes

## Определения

- **Deployment** — объект Kubernetes для управления ReplicaSet и rolling update.
- **Service** — абстракция для доступа к подам (ClusterIP, NodePort, LoadBalancer).
- **Ingress** — L7 маршрутизация по хосту/пути с TLS termination; legacy-объект, актуально для NGINX Ingress Controller.
- **Gateway API** — современный замена Ingress (CNCF Standard), унифицирует North-South и East-West трафик.
- **HPA (Horizontal Pod Autoscaler)** — автоматическое масштабирование по метрикам CPU/memory или custom metrics.
- **PDB (Pod Disruption Budget)** — ограничение одновременного выбытия подов при voluntary disruption (обновление узлов, drain).
- **NetworkPolicy** — сетевой firewall между неймспейсами/подами.
- **ConfigMap/Secret** — конфигурация и секреты приложения.
- **Probe** — readiness/liveness/startup проверки состояния пода.
- **Argo CD / Flux** — GitOps-контроллеры для declarative деплоя из Git.
- **PodSecurityStandard (PSS)** — встроенная политика безопасности подов (restricted/baseline/privileged).

---

## Предварительные требования

- **Kubernetes:** кластер v1.29+ с включёнными стабильными API-группами (`apps/v1`, `networking.k8s.io/v1`, `autoscaling/v2`).
- **kubectl:** клиент v1.29+, настроенный на контекст кластера с правами `get`, `apply`, `describe`, `rollout`, `delete`.
- **Ingress Controller:** NGINX Ingress Controller 1.9+ или аналогичный; для современного подхода — Gateway API controller (Envoy Gateway, Istio, Traefik).
- **cert-manager:** v1.14+ для автоматической выдачи и ротации TLS-сертификатов (Let's Encrypt, внутренний CA).
- **Registry:** внутренний OCI-реестр (Harbor, GitLab CR, Nexus) с поддержкой OCI 1.1 Referrers API для аттестаций.
- **Секреты:** Vault 1.15+ или External Secrets Operator для доставки секретов в поды; долгоживущие ключи не хранятся в репозитории.
- **CI/CD:** GitLab CI 16+ или аналогичный пайплайн с поддержкой `kubectl apply`, image digest verification, Cosign подписи.
- **RBAC:** сервис-аккаунты с минимальными правами; namespace-изоляция для preview/production.
- **Сеть:** CNI-плагин (Calico, Cilium) поддерживающий NetworkPolicy; egress от подов к Vault/registry разрешён.
- **Документация:** общие принципы Cosign/SBOM описаны в **[Supply Chain Security для фронтенда](./frontend_supply_chain_security.md)**; Vault integration — в **[Secrets Management для фронтенда](./frontend_secrets_management.md)**; этот файл фокусируется на K8s-специфике деплоя.

---

## Основные концепции

### Чем деплой фронтенда в K8s отличается от статики

Для чистой статики достаточно `Deployment` + `Service` + `Ingress`. Для SSR/SSR-процесса (Next.js, Nuxt, Remix) нужен дополнительно:
- **Health checks:** readiness probe проверяет, что процесс поднялся и готов к трафику; startup probe — для тяжёлого прогрева.
- **Resource limits:** ограничение памяти Node.js, чтобы не вытеснять соседние поды при утечках.
- **Graceful shutdown:** ловля `SIGTERM` для завершения активных запросов перед удалением пода.
- **PodDisruptionBudget:** минимум 1 под доступен при voluntary disruption (обновление узла, drain).
- **PodSecurityStandard:** restricted-режим для исключения привилегированных контейнеров.

### Архитектура развёртывания

```
Ingress / Gateway API (TLS termination)
  └── Service (ClusterIP/LoadBalancer)
       └── Deployment
            └── Pod
                 ├── init-container (миграции/проверки)
                 ├── container: SSR/Node.js
                 │    ├── startupProbe: /healthz (тяжёлый прогрев)
                 │    ├── livenessProbe: /healthz
                 │    ├── readinessProbe: /healthz
                 │    └── resources: requests/limits
                 └── sidecar: Vault Agent (опционально)
```

### Rolling Update и zero-downtime

Стратегия обновления:
- `maxSurge: 1` — один дополнительный под создаётся во время обновления.
- `maxUnavailable: 0` — старые поды не удаляются, пока новые не станут Ready.
- `minReadySeconds: 10` — под должен оставаться Ready минимум 10 секунд перед признанием Available.

Для production-critical фронтенда дополнительно:
- Настройте `progressDeadlineSeconds: 600` — таймаут rollout, чтобы зависший обновление не блокировало следующий.
- Используйте `revisionHistoryLimit: 5` — глубина истории ReplicaSets для отката.

### Версионирование и откат

- **Image digest:** используйте digest (`registry.example.com/frontend@sha256:...`) вместо плавающего тега `latest` или `main`.
- **Rollback:** `kubectl rollout undo deployment/frontend-ssr` — мгновенный откат на предыдущий replicaset.
- **History:** `kubectl rollout history deployment/frontend-ssr` — просмотр ревизий.
- **Argo CD / Flux:** откат через `git revert` + синхронизация — без прямого доступа к кластеру.

### Секреты и конфигурация в Kubernetes

- **ConfigMap:** нечувствительная конфигурация (API URL, feature flags, лог-уровень).
- **Secret:** чувствительные данные (API keys, cookies, tokens); хранятся в etcd, base64 — не шифрование.
- **Vault CSI Driver / External Secrets Operator:** синхронизация секретов из Vault в Kubernetes Secret; rotation без передеплоя.
- **Environment vs File:** для SSR-процесса секреты лучше читать из файла (tmpfs) чем из env, чтобы не попасть в логи.

Общие принципы управления секретами — в **[Secrets Management для фронтенда](./frontend_secrets_management.md)**.

### Валидация образа перед деплоем

Перед `kubectl set image` или обновлением манифеста в GitOps:
- Проверьте подпись: `cosign verify registry.example.com/frontend@sha256:...`.
- Проверьте SBOM: `syft` отчёт или attestation прикреплён к образу.
- Проверьте digest: `skopeo inspect docker://registry.example.com/frontend@sha256:...`.

Детали — в **[Supply Chain Security для фронтенда](./frontend_supply_chain_security.md)**.

---

## Практические сценарии

### Сценарий 1: Deployment + Service + Ingress для SSR

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend-ssr
  namespace: production
  labels:
    app.kubernetes.io/name: frontend
    app.kubernetes.io/component: web
spec:
  replicas: 3
  revisionHistoryLimit: 5
  progressDeadlineSeconds: 600
  minReadySeconds: 10
  selector:
    matchLabels:
      app.kubernetes.io/name: frontend
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app.kubernetes.io/name: frontend
    spec:
      serviceAccountName: frontend-ssr
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: ssr
          image: registry.example.com/frontend@sha256:abc123
          ports:
            - containerPort: 3000
              name: http
              protocol: TCP
          env:
            - name: NODE_ENV
              value: "production"
            - name: VAULT_ADDR
              value: "http://127.0.0.1:8200"
          envFrom:
            - configMapRef:
                name: frontend-ssr-config
            - secretRef:
                name: frontend-ssr-secrets
          startupProbe:
            httpGet:
              path: /healthz
              port: http
            failureThreshold: 30
            periodSeconds: 2
          livenessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 10
            periodSeconds: 30
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 5
            periodSeconds: 10
            failureThreshold: 3
          resources:
            requests:
              cpu: "250m"
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
          volumeMounts:
            - name: vault-secrets
              mountPath: /vault/secrets
              readOnly: true
      volumes:
        - name: vault-secrets
          emptyDir:
            medium: Memory
---
# service.yaml
apiVersion: v1
kind: Service
metadata:
  name: frontend-ssr
  namespace: production
spec:
  selector:
    app.kubernetes.io/name: frontend
  ports:
    - port: 80
      targetPort: http
      protocol: TCP
      name: http
  type: ClusterIP
---
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: frontend-ssr
  namespace: production
  annotations:
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "10"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "60"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "60"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - example.com
      secretName: example-com-tls
  rules:
    - host: example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: frontend-ssr
                port:
                  number: 80
```

**Валидация:**
- `kubectl get pods -n production -l app.kubernetes.io/name=frontend` — все pods `Running`.
- `kubectl rollout status deployment/frontend-ssr -n production` → `successfully rolled out`.
- `kubectl get endpoints frontend-ssr -n production` — список готовых подов.
- `curl -I https://example.com` — `200`, заголовок `Server` корректный.
- `kubectl get certificates -n production` — сертификат `Ready`.

**Troubleshooting:**
- *Readiness probe падает:* проверьте `EXPOSE` и путь в probe; убедитесь, что сервер слушает на `0.0.0.0`.
- *Rollout зависает:* проверьте `progressDeadlineSeconds`; смотрите `kubectl describe deployment/frontend-ssr` → `Conditions`.
- *Ingress 503:* проверьте endpoints Service; проверьте readiness probe подов.
- *TLS ошибка:* проверьте `kubectl get certificates`, ACME challenge; проверьте `cert-manager` логи.
- *Pod не видит Vault:* проверьте NetworkPolicy egress к namespace `vault`.

### Сценарий 2: HPA + PDB

```yaml
# hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: frontend-ssr
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: frontend-ssr
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Pods
      pods:
        metric:
          name: nodejs_eventloop_lag_seconds
        target:
          type: AverageValue
          averageValue: "0.1"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
---
# pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: frontend-ssr
  namespace: production
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: frontend
```

**Валидация:**
- `kubectl get hpa frontend-ssr -n production` — `TARGETS` показывает текущую утилизацию.
- `kubectl get pdb frontend-ssr -n production` — `MIN AVAILABLE 2`.
- `kubectl top pods -n production` — метрики CPU/memory доступны.
- При `kubectl drain` — PDB блокирует выселение ниже бюджета.

**Troubleshooting:**
- *HPA не масштабирует:* проверьте `metrics-server` установлен; `kubectl top pods` работает.
- *HPA "дребезг":* добавьте `behavior` с `stabilizationWindowSeconds`.
- *Rollout зависает из-за PDB:* `minAvailable` в PDB несовместим с `maxUnavailable` в Deployment. Для `minAvailable: 2` из 3 реплик, `maxUnavailable` должен быть `0`.
- *HPA "воюет" с ручным scale:* не используйте `kubectl scale` для Deployment, управляемого HPA.

### Сценарий 3: NetworkPolicy для изоляции

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: frontend-ssr-allow
  namespace: production
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: frontend
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
      ports:
        - protocol: TCP
          port: 3000
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: vault
      ports:
        - protocol: TCP
          port: 8200
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: backend
      ports:
        - protocol: TCP
          port: 5432
    # разрешить DNS
    - to: []
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

**Валидация:**
- `kubectl get networkpolicy frontend-ssr-allow -n production` — политика активна.
- `kubectl describe networkpolicy frontend-ssr-allow -n production` — правила корректны.
- Под не может подключиться к запрещённым неймспейсам (проверка через `nslookup` или `curl` изнутри пода).

**Troubleshooting:**
- *Под не может резолвить DNS:* добавьте egress правило на порт 53 (UDP/TCP) к `dns-service`.
- *Ingress не доходит до пода:* проверьте `ingressClassName` и namespace selector.
- *Vault недоступен:* проверьте egress правило к namespace `vault` на порт 8200.
- *CNI не поддерживает NetworkPolicy:* проверьте, что CNI-плагин (Calico, Cilium) установлен и active.

### Сценарий 4: Rolling update и rollback

```bash
# Обновление образа (используем digest)
kubectl set image deployment/frontend-ssr ssr=registry.example.com/frontend@sha256:newdigest -n production

# Просмотр статуса rollout
kubectl rollout status deployment/frontend-ssr -n production
# → deployment "frontend-ssr" successfully rolled out

# Просмотр истории ревизий
kubectl rollout history deployment/frontend-ssr -n production

# Откат при проблемах
kubectl rollout undo deployment/frontend-ssr -n production

# Откат к конкретной ревизии
kubectl rollout undo deployment/frontend-ssr --to-revision=3 -n production
```

**Валидация:**
- `kubectl rollout status` → `successfully rolled out`.
- После отката pods возвращаются к старому образу; `kubectl get pods` → `Running`.

**Troubleshooting:**
- *Rollout зависает:* проверьте `progressDeadlineSeconds`; смотрите events: `kubectl get events -n production --field-selector reason=ReplicaSet`.
- *Откат не работает:* проверьте `revisionHistoryLimit` >= 1; проверьте registry доступность для старого образа.
- *ImagePullBackOff:* проверьте `imagePullSecrets` и registry credentials.
- *Pod не запускается после отката:* проверьте `kubectl describe pod` — секреты/ConfigMap существуют.

### Сценарий 5: GitOps deploy через Argo CD

```yaml
# ApplicationSet для preview-окружений
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: frontend-preview
  namespace: argocd
spec:
  generators:
    - pullRequest:
        github:
          owner: org
          repo: frontend
          tokenRef:
            secretName: github-token
            key: token
  template:
    metadata:
      name: "frontend-preview-{{number}}"
      annotations:
        argocd.argoproj.io/sync-options: Prune=true
    spec:
      project: default
      source:
        repoURL: https://github.com/org/frontend.git
        targetRevision: "{{head_sha}}"
        path: k8s/preview
      destination:
        server: https://kubernetes.default.svc
        namespace: preview
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

Для production используйте Argo CD с manual approval или Image Updater:

```yaml
# argocd-image-updater
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: frontend-production
  namespace: argocd
spec:
  source:
    repoURL: https://github.com/org/frontend.git
    targetRevision: main
    path: k8s/production
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: false
    syncOptions:
      - ApplyOutOfSyncOnly=true
```

**Валидация:**
- `argocd app get frontend-production` → `Sync Status: Synced`, `Health Status: Healthy`.
- `argocd app history frontend-production` — история деплоев соответствует Git.

**Troubleshooting:**
- *OutOfSync после rollout:* проверьте `ignoreDifferences` для `replicas` (HPA управляет replicas).
- *Self-heal конфликтует с manual deploy:* отключите `selfHeal` для production.
- *Image Updater не обновляет:* проверьте `argocd-image-updater-config` и permissions на registry.

---

## Операционные команды

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `kubectl apply -f deployment.yaml` | Применение манифеста | # → deployment/frontend-ssr created/configured |
| `kubectl rollout status deployment/frontend-ssr -n production` | Ожидание rollout | # → successfully rolled out |
| `kubectl rollout undo deployment/frontend-ssr -n production` | Откат deployment | # → rolled back |
| `kubectl rollout history deployment/frontend-ssr -n production` | История ревизий | # → список revision с изменениями |
| `kubectl set image deployment/frontend-ssr ssr=...` | Обновление образа | # → deployment updated, rollout started |
| `kubectl get pods -n production -l app.kubernetes.io/name=frontend` | Список подов | # → все pods Running, READY 1/1 |
| `kubectl describe deployment/frontend-ssr -n production` | Детали deployment | # → Conditions, ReplicaSets, Events |
| `kubectl get hpa frontend-ssr -n production` | Статус HPA | # → TARGETS, текущая утилизация |
| `kubectl get pdb frontend-ssr -n production` | Статус PDB | # → MIN AVAILABLE, ALLOWED DISRUPTIONS |
| `kubectl get networkpolicy frontend-ssr-allow -n production` | Список NetworkPolicy | # → политика активна |
| `kubectl get ingress frontend-ssr -n production` | Статус Ingress | # → ADDRESS, порты, TLS |
| `kubectl get certificates -n production` | Сертификаты cert-manager | # → Ready, срок действия |
| `kubectl get endpoints frontend-ssr -n production` | Endpoints Service | # → список готовых подов с IP |
| `kubectl get events -n production --field-selector reason=ReplicaSet` | События rollout | # → ScalingReplicaSet, new ReplicaSet |
| `kubectl top pods -n production -l app.kubernetes.io/name=frontend` | Метрики pods | # → CPU/memory usage |
| `kubectl auth can-i ...` | Проверка RBAC прав | # → yes/no |
| `argocd app get frontend-production` | Статус GitOps приложения | # → Sync/Health status |
| `cosign verify registry.example.com/frontend@sha256:...` | Верификация образа | # → Verification succeeded |

---

## Валидация

- **Replicas:** `kubectl get pods -n production -l app.kubernetes.io/name=frontend` — все pods `Running`, `READY 1/1`.
- **Rollout status:** `kubectl rollout status deployment/frontend-ssr -n production` → `successfully rolled out`.
- **Readiness probe:** `kubectl get pods -n production` — все pods `READY 1/1` (не `0/1`).
- **Service endpoint:** `kubectl get endpoints frontend-ssr -n production` — список готовых подов, не пустой.
- **Ingress:** `curl -I https://example.com` — `200`, `X-Cache` или `Server` заголовок корректный.
- **HPA:** `kubectl get hpa frontend-ssr -n production` — `TARGETS` показывает текущую утилизацию.
- **PDB:** `kubectl get pdb frontend-ssr -n production` — `MIN AVAILABLE 2`, `ALLOWED 1`.
- **NetworkPolicy:** `kubectl get networkpolicy frontend-ssr-allow -n production` — политика активна.
- **Certificate:** `kubectl get certificates -n production` — `Ready`, срок действия > 30 дней.
- **Argo CD / Flux:** `argocd app get` → `Synced`, `Healthy`.
- **Image signature:** `cosign verify` проходит для production-образа.
- **RBAC:** `kubectl auth can-i create pods -n production` → `yes` для сервис-аккаунта.

---

## Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Pod не проходит readiness probe | Прогрев JIT, тяжёлый модуль | Увеличить `initialDelaySeconds`, добавить `startupProbe` |
| CrashLoopBackOff | Утечка памяти, неверный секрет | `kubectl logs`, `kubectl describe pod` |
| 503 от Ingress | Readiness probe падает, HPA масштабирует | Проверить `/healthz`, resource limits, endpoints |
| OOMKilled | Недостаточно memory limit | Увеличить `limits.memory`, добавить `--max-old-space-size` |
| Rollout зависает | PDB конфликт, imagePullBackOff | Проверить PDB, `kubectl get events`, registry credentials |
| Pod не видит Vault | NetworkPolicy блокирует egress | Добавить egress правило к Vault namespace |
| TLS ошибка | cert-manager не выпустил сертификат | `kubectl get certificates`, ACME challenge, проверка DNS |
| Поды не масштабируются | HPA metrics server не установлен | Установить `metrics-server`, `kubectl top pods` |
| ImagePullBackOff | Неверный digest, нет credentials | Проверить `imagePullSecrets`, registry доступность |
| HPA "дребезг" | Нет `behavior` stabilization | Добавить `stabilizationWindowSeconds` в HPA spec |
| ConfigMap не обновляется | Нет reload в приложении | Использовать `reloader` или SIGHUP graceful reload |
| GitOps OutOfSync | HPA управляет replicas | `ignoreDifferences` в ArgoCD для `/spec/replicas` |
| Pod стартует с привилегиями | Отсутствует PodSecurityStandard | Включить `restricted` PSS в namespace |
| Secret в логах | Env var с секретом попал в stdout | Читать из файла (tmpfs), не из env; настроить log redaction |
| Stale pods после rollout | Старые поды не завершаются | Проверить `terminationGracePeriodSeconds`, preStop hook |

---

## Особые случаи

- **Graceful shutdown и SIGTERM:** Node.js SSR по умолчанию не обрабатывает `SIGTERM`. Добавьте `tini` как PID 1 (`ENTRYPOINT ["/sbin/tini", "--"]`) или обработчик в коде. Установите `terminationGracePeriodSeconds: 30` в Pod spec.
- **Startup probe для тяжёлого SSR:** Если прогрев занимает > 10 секунд (JIT компиляция, подключение к БД), добавьте `startupProbe` с `failureThreshold: 30` и `periodSeconds: 2`. Без startup probe liveness probe убьёт под до готовности.
- **PodDisruptionBudget и Rolling Update конфликт:** PDB не блокирует Rolling Update напрямую, но блокирует `kubectl drain`. Убедитесь, что `maxUnavailable` в Deployment и `minAvailable` в PDB совместимы. Для 3 реплик и `minAvailable: 2`, `maxUnavailable` должен быть `0`.
- **NetworkPolicy default-deny:** Начните с политики, запрещающей весь трафик, и по очереди разрешайте нужные правила. Это предотвращает "шпионские" поды.
- **cert-manager и ACME rate limits:** Let's Encrypt ограничивает 50 сертификатов/неделю на домен. Для preview-окружений используйте внутренний CA или staging environment (`letsencrypt-staging`).
- **Ingress vs Gateway API:** С середины 2026 Gateway API является стандартом CNCF и полностью заменяет Ingress для новых проектов. Для существующих проектов с NGINX Ingress можно мигрировать постепенно через `Gateway` + `HTTPRoute`.
- **Ephemeral containers для отладки:** `kubectl debug -it frontend-ssr-xxx --image=busybox` — безопасная отладка без изменения манифеста. Доступно в K8s 1.18+.
- **Multi-arch образы:** `docker buildx build --platform linux/amd64,linux/arm64` создаёт image index. В K8s на mixed-arch кластере `nodeSelector` или `nodeAffinity` не нужен — scheduler сам выберет подходящий arch.
- **PodSecurityStandard (PSS):** Включите `restricted` PSS для namespace production. Это запрещает привилегированные контейнеры, требует `runAsNonRoot`, `readOnlyRootFilesystem` (с tmpfs исключениями).
- **Resource Quota и LimitRange:** Для preview-окружений установите `ResourceQuota` (CPU/memory лимиты на namespace) и `LimitRange` (дефолтные requests/limits для новых подов), чтобы один большой `dist/` не заполнил кластер.

---

## Инцидент: compromised deployment / secret leak

1. **Немедленный отзыв:** `kubectl set image deployment/frontend-ssr ssr=registry.example.com/frontend@sha256:known-good-digest` — мгновенный откат на проверенный образ.
2. **Изоляция:** `kubectl rollout pause deployment/frontend-ssr` — приостановка автоматических обновлений.
3. **Ротация секретов:** сгенерировать новые секреты в Vault; External Secrets Operator синхронизирует их автоматически.
4. **Аудит:** `kubectl get events -n production --sort-by='.lastTimestamp'`; проверка audit logs кластера; `kubectl describe pod` для подозрительных подов.
5. **Очистка:** удалить скомпрометированные pods; `kubectl delete pods -l app.kubernetes.io/name=frontend` (ReplicaSet создаст новые).
6. **Постмортем:** blameless postmortem; обновление политик PodSecurityStandard, NetworkPolicy, RBAC.

Полный runbook — в **[Supply Chain Incident Response](../../Security/Supply_Chain_Security/supply_chain_incident_response.md)**.

---

## Лучшие практики

1. Используйте image digest вместо тега (`@sha256:...`) для production-деплоя.
2. Настройте RollingUpdate с `maxSurge: 1`, `maxUnavailable: 0` для zero-downtime.
3. Добавьте startup, liveness и readiness probes; без них K8s не знает, когда pod готов.
4. Запускайте контейнер от non-root пользователя (`runAsNonRoot: true`, `runAsUser: 1000`).
5. Ограничьте ресурсы (`requests` + `limits`) и используйте HPA по CPU/memory или custom metrics.
6. Настройте PDB с `minAvailable: N-1` или `minAvailable: 1` для минимум 2 реплик.
7. Используйте NetworkPolicy с default-deny; разрешайте только необходимый трафик.
8. Верифицируйте образ Cosign перед деплоем; используйте digest вместо тега.
9. Для секретов используйте Vault CSI Driver или External Secrets Operator, а не plain Kubernetes Secrets.
10. Настройте cert-manager для автоматической выдачи и rotation TLS-сертификатов.
11. Включайте PodSecurityStandard `restricted` для production namespace.
12. Для GitOps используйте Argo CD или Flux; храните манифесты в Git, а не применяйте `kubectl apply` вручную.
13. Настройте `terminationGracePeriodSeconds` и preStop hook для graceful shutdown SSR-процесса.
14. Используйте Gateway API для новых проектов вместо legacy Ingress.

---

## Дополнительная информация

### См. также

- **[Манифест Deployment](../../Kubernetes/Base/Deployment/deployment_manifest.md)** — production-ready конфигурация Deployment, security context, probes.
- **[Secrets Management для фронтенда](./frontend_secrets_management.md)** — Vault CSI Driver, External Secrets Operator, runtime секреты для SSR.
- **[GitOps для фронтенда](./frontend_gitops.md)** — Argo CD ApplicationSet, Flux, preview-окружения.
