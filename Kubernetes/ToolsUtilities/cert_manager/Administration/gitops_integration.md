# Cert-manager: Интеграция с GitOps (ArgoCD / Flux)

## Определения

**GitOps для cert-manager** — подход к управлению конфигурацией сертификатов, при котором Ingress, Issuer и ClusterIssuer описываются в Git и автоматически синхронизируются с кластером через контроллеры (ArgoCD или Flux). Ресурсы, управляемые cert-manager автоматически (Certificate, Order, Challenge), НЕ экспортируются в Git.

**Server-Side Apply (SSA)** — механизм Kubernetes API, позволяющий нескольким контроллерам управлять одним ресурсом без конфликтов. При совместном управлении Ingress cert-manager'ом и GitOps-контроллером SSA предотвращает гонки за запись полей.

**managedFieldsManagers** — список контроллеров, владеющих определенными полями ресурса. Настройка этого параметра в GitOps-контроллере позволяет игнорировать изменения, вносимые cert-manager в TLS-секреты.

**Auto-Healing** — способность GitOps-контроллера обнаруживать drift (расхождение между желаемым состоянием в Git и текущим в кластере) и автоматически восстанавливать конфигурацию. Критично для cert-manager: если Secret будет удален вручную, GitOps вернет его из Git.

---

## Основные концепции

### Проблема совместного управления

При использовании GitOps и cert-manager возникает конфликт: cert-manager автоматически управляет Secret и部分 полями Ingress, а GitOps-контроллер пытается вернуть ресурс в состояние из Git.

**Цепочка конфликтов:**
1. GitOps применяет Ingress с аннотацией `cert-manager.io/cluster-issuer`
2. cert-manager создает ресурс `Certificate` и Secret
3. cert-manager обновляет `status` Ingress и управляет Secret
4. GitOps-контроллер обнаруживает "drift" и пытается вернуть ресурс
5. Возникает цикл конфликтов (reconcile loop)

### Решение: Игнорирование автоматически управляемых полей

Оба GitOps-контроллера (ArgoCD и Flux) поддерживают механизм игнорирования определенных полей или ресурсов.

**Принцип:** В Git хранятся ТОЛЬКО Ingress и Issuer/ClusterIssuer. Certificate, Order, Challenge, Secret — управляются cert-manager автоматически и исключаются из GitOps.

### Что хранится в Git, а что нет

| Ресурс | В Git | Кто управляет |
| :--- | :--- | :--- |
| **Ingress** | Да (с аннотациями cert-manager) | GitOps + cert-manager (статус) |
| **Issuer / ClusterIssuer** | Да | GitOps |
| **Certificate** | Нет | cert-manager автоматически |
| **Secret (TLS)** | Нет | cert-manager автоматически |
| **Order** | Нет | cert-manager автоматически |
| **Challenge** | Нет | cert-manager автоматически |

---

## Практические сценарии

### Сценарий 1: ArgoCD — Игнорирование изменений cert-manager

#### Настройка IgnoreDifferences на уровне Application

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/k8s-manifests
    targetRevision: main
    path: apps/my-app
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
  ignoreDifferences:
  # Игнорирование managedFields от cert-manager
  - group: networking.k8s.io
    kind: Ingress
    jqPathExpressions:
    - '.metadata.managedFields[] | select(.manager == "cert-manager")'
  # Игнорирование tls.secretName, если cert-manager управляет Secret
  - group: networking.k8s.io
    kind: Ingress
    jsonPointers:
    - /spec/tls/0/secretName
  # Игнорирование статуса Ingress
  - group: networking.k8s.io
    kind: Ingress
    jsonPointers:
    - /status
```

#### Настройка на уровне проекта (проактивно для всех Applications)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production
  namespace: argocd
spec:
  description: Production applications
  sourceRepos:
  - https://github.com/org/k8s-manifests
  destinations:
  - namespace: production
    server: https://kubernetes.default.svc
  clusterResourceWhitelist:
  - group: ''
    kind: Namespace
  # Глобальные правила игнорирования для cert-manager
  sourceNamespaces:
  - '*'
  ignoreDifferences:
  - group: networking.k8s.io
    kind: Ingress
    jqPathExpressions:
    - '.metadata.managedFields[] | select(.manager == "cert-manager")'
```

#### Автоматический prune Managed Resources

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  annotations:
    # ArgoCD не будет пытаться удалить ресурсы, которых нет в Git
    argocd.argoproj.io/prunePropagationPolicy: foreground
    argocd.argoproj.io/prune-last: "true"
spec:
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    # Не создавать namespace через ArgoCD (cert-manager может создать свой)
    - CreateNamespace=false
    # Server-side apply для избежания конфликтов managedFields
    - ServerSideApply=true
```

### Сценарий 2: Flux — Игнорирование изменений cert-manager

#### Kustomization с игнорированием specific fields

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: my-app
  namespace: flux-system
spec:
  interval: 5m
  path: ./apps/my-app
  prune: true
  sourceRef:
    kind: GitRepository
    name: k8s-manifests
  healthChecks:
  - apiVersion: networking.k8s.io/v1
    kind: Ingress
    name: my-app-ingress
    namespace: production
  timeout: 3m
  # Игнорирование изменений cert-manager
  patches:
  - target:
      group: networking.k8s.io
      kind: Ingress
      name: my-app-ingress
      namespace: production
    patch: |
      - op: remove
        path: /metadata/managedFields/0
      - op: replace
        path: /spec/tls/0/secretName
        value: ""
```

#### Дополнительный файл с патчем (выделенный)

```yaml
# patches/ignore-cert-manager-fields.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
patches:
- target:
    group: networking.k8s.io
    kind: Ingress
    labelSelector: "cert-manager.io/cluster-issuer"
  patch: |
    - op: add
      path: /metadata/annotations/ignore-cert-manager~1managed-fields
      value: "true"
    - op: remove
      path: /status
```

### Сценарий 3: Контроль Certificate через GitOps (Vs ArgoCD)

Если требуется декларативное управление Certificate (вместо автоматического через ingress-shim), создайте его явно в Git:

```yaml
# certificates/my-app.yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-app-tls
  namespace: production
  annotations:
    # Отключаем ingress-shim для этого Certificate
    cert-manager.io/issuer: ""
spec:
  secretName: my-app-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - my-app.example.com
  - www.my-app.example.com
  privateKey:
    algorithm: ECDSA
    size: 256
    rotationPolicy: Always
  duration: 2160h    # 90 дней
  renewBefore: 360h  # 15 дней
```

```yaml
# ingress/my-app.yaml (без ingress-shim)
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-ingress
  namespace: production
  annotations:
    # НЕТ аннотации cert-manager.io — Certificate управляем через Git
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - my-app.example.com
    - www.my-app.example.com
    secretName: my-app-tls-secret  # Уже существует от Certificate
  rules:
  - host: my-app.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-app
            port:
              number: 80
```

**Преимущества:** Полный контроль над конфигурацией сертификата через Git.
**Недостатки:** Потеря автоматизации ingress-shim (нужно поддерживать Certificate в Git).

### Сценарий 4: ArgoCD Resource Hook для пред-деплойной очистки

Используйте ArgoCD hooks для удаления osиротевших Secret перед деплоем:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: cleanup-stale-secrets
  namespace: production
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  serviceAccountName: cert-manager-cleanup
  containers:
  - name: cleanup
    image: bitnami/kubectl:1.31
    command:
    - /bin/sh
    - -c
    - |
      # Удаление Secret, связанных с удаляемыми Ingress
      kubectl get secret -n production -o json | \
        jq -r '.items[] | select(.type=="kubernetes.io/tls") | .metadata.name' | \
        while read secret; do
          if ! kubectl get certificate -n production -o json | \
             jq -e ".items[] | select(.spec.secretName==\"$secret\")" > /dev/null 2>&1; then
            echo "Deleting orphaned secret: $secret"
            kubectl delete secret "$secret" -n production
          fi
        done
  restartPolicy: Never
```

---

## Дополнительная информация

### Diagnostics: GitOps конфликты

**Симптом:** ArgoCD показывает "OutOfSync", но манифест валиден.

```bash
# Проверка managedFields конфликтов
kubectl get ingress my-app -n production -o jsonpath='{.metadata.managedFields}' | jq .

# Проверка последнего коммита в Git
argocd app get my-app --hard-refresh

# Просмотр diff в ArgoCD UI
argocd app diff my-app
```

**Симптом:** Flux не применяет изменения из-за health check timeout.

```bash
# Проверка статуса Kustomization
kubectl get kustomization my-app -n flux-system -o yaml

# Просмотр событий
kubectl get events -n flux-system --field-selector involvedObject.name=my-app
```

### Best Practices

1. **Минимальные аннотации:** Используйте только необходимые аннотации cert-manager в Ingress.
2. **Server-Side Apply:** Включайте SSA в ArgoCD (`ServerSideApply=true`) для избежания конфликтов managedFields.
3. **Prune Politика:** Настройте `prune: true` и `selfHeal: true` для автоматического восстановления.
4. **Health Checks:** Добавьте health checks для Ingress и Certificate в ArgoCD/Flux.
5. **Мониторинг:** Настройте алерты на sync failures в ArgoCD/Flux.
6. **Тестирование:** Используйте staging-окружение для проверки GitOps + cert-manager перед production.

### Смотрите также

- **[Cert-manager: Операции](./operations.md)** — мониторинг и алертинг.
- **[Cert-manager: Диагностика](./troubleshooting.md)** — troubleshooting интеграции.
- **[Cert-manager: Мульти-тенантность](./multi_tenancy.md)** — изоляция tenant'ов в GitOps-среде.
- **[GitOps Overview](../../../../GitOps/GitOps_overview.md)** — общие принципы GitOps.
