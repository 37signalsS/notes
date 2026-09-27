# cert-manager для Ephemeral/Preview-сред

## Определения

**Ephemeral Environment** — временная среда разработки/тестирования, создаваемая автоматически для каждого pull request или ветки и удаляемая после её закрытия. Требует автоматического выпуска TLS-сертификатов для динамических поддоменов (например, `pr-123.preview.example.com`).

**Preview Environment** — синоним ephemeral environment в контексте preview деплоев. Обычно включает Ingress с уникальным поддоменом, базу данных и TLS-сертификат.

**Wildcard Certificate** — сертификат `*.example.com`, покрывающий все поддомены первого уровня. Используется для ephemeral сред, чтобы избежать выпуска отдельного сертификата для каждого PR.

**External DNS** — контроллер, автоматически создающий/удаляющий DNS-записи в соответствии с ресурсами Ingress. Работает в паре с cert-manager для полной автоматизации TLS + DNS.

---

## Основные концепции

### Архитектура автоматизации для ephemeral сред

```
┌─────────────────────────────────────────────────────────┐
│                    CI/CD Pipeline                       │
│  (GitLab CI / GitHub Actions / ArgoCD Rollout)          │
│                                                         │
│  1. Создание Ingress с аннотациями cert-manager         │
│  2. Создание DNS-записи через external-dns              │
│  3. cert-manager выпускает сертификат (DNS-01)          │
│  4. Ingress-контроллер подхватывает Secret              │
│  5. При удалении PR: удаление Ingress + Secret + DNS    │
└─────────────────────────────────────────────────────────┘
```

### Два подхода к TLS в ephemeral средах

| Подход | Механизм | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Wildcard + DNS-01** | Один `*.preview.example.com` сертификат на весь кластер | Минимальные rate limits, быстрое развёртывание | Один компрометированный ключ → все preview |
| **Отдельные сертификаты** | Каждый Ingress получает свой сертификат через HTTP-01 | Изоляция, безопасность | Высокие rate limits, медленнее |

### Rate Limits при массовом создании

При параллельном создании 50+ ephemeral сред риск превышения rate limits Let's Encrypt:

| Лимит | Значение | Стратегия защиты |
| :--- | :--- | :--- |
| **Certificates per Domain** | 50 / 7 дней | Wildcard-сертификат |
| **Duplicate Certificates** | 5 / 7 дней | Уникальные SAN для каждого PR |
| **Failed Validations** | 5 / 1 час | Staging-first подход |

---

## Практические сценарии

### Сценарий 1: Wildcard-сертификат для preview-сред

Самый эффективный подход для ephemeral сред.

#### Шаг 1: ClusterIssuer с DNS-01

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod-wildcard
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: devops@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-wildcard-account-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
      selector:
        dnsZones:
        - "preview.example.com"
```

#### Шаг 2: Wildcard-сертификат

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: preview-wildcard-tls
  namespace: cert-manager
spec:
  secretName: preview-wildcard-tls
  issuerRef:
    name: letsencrypt-prod-wildcard
    kind: ClusterIssuer
  dnsNames:
  - "*.preview.example.com"
  - "preview.example.com"
  privateKey:
    algorithm: ECDSA
    size: 256
    rotationPolicy: Always
  duration: 2160h
  renewBefore: 360h
```

#### Шаг 3: Ingress для каждого preview-деплоя

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: pr-123-app
  namespace: pr-123
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod-wildcard"
    external-dns.alpha.kubernetes.io/hostname: "pr-123.preview.example.com"
    external-dns.alpha.kubernetes.io/ttl: "300"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - pr-123.preview.example.com
    secretName: pr-123-app-tls
  rules:
  - host: pr-123.preview.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: pr-123-app
            port:
              number: 80
```

> **Примечание:** Если используется wildcard-сертификат, `secretName` в Ingress может ссылаться на уже созданный Secret `preview-wildcard-tls` вместо создания нового.

### Сценарий 2: CI/CD-пайплайн с автоматическим TLS

```yaml
# .gitlab-ci.yml
stages:
- deploy

deploy-preview:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
  - |
    # Уникальное имя для preview
    PREVIEW_ID="pr-${CI_MERGE_REQUEST_IID}"
    NAMESPACE="preview-${PREVIEW_ID}"
    HOST="${PREVIEW_ID}.preview.example.com"
    
    # Создание namespace
    kubectl create namespace ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -
    
    # Применение манифестов приложения
    kubectl apply -f kubernetes/ -n ${NAMESPACE}
    
    # Создание Ingress с аннотацией cert-manager
    cat <<EOF | kubectl apply -f -
    apiVersion: networking.k8s.io/v1
    kind: Ingress
    metadata:
      name: ${PREVIEW_ID}-ingress
      namespace: ${NAMESPACE}
      annotations:
        cert-manager.io/cluster-issuer: "letsencrypt-prod-wildcard"
        external-dns.alpha.kubernetes.io/hostname: "${HOST}"
    spec:
      ingressClassName: nginx
      tls:
      - hosts:
        - ${HOST}
        secretName: ${PREVIEW_ID}-tls
      rules:
      - host: ${HOST}
        http:
          paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: ${PREVIEW_ID}-app
                port:
                  number: 80
    EOF
    
    # Ожидание готовности
    kubectl wait --for=condition=Ready ingress/${PREVIEW_ID}-ingress -n ${NAMESPACE} --timeout=300s
    
    echo "Preview available at: https://${HOST}"
  environment:
    name: preview/${CI_MERGE_REQUEST_IID}
    url: https://pr-${CI_MERGE_REQUEST_IID}.preview.example.com

cleanup-preview:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
  - |
    PREVIEW_ID="pr-${CI_MERGE_REQUEST_IID}"
    NAMESPACE="preview-${PREVIEW_ID}"
    
    # Удаление namespace (каскадно удалит Ingress, Certificate, Secret)
    kubectl delete namespace ${NAMESPACE} --ignore-not-found
    
    echo "Preview ${PREVIEW_ID} cleaned up"
  when: manual
  environment:
    name: preview/${CI_MERGE_REQUEST_IID}
    action: stop
```

### Сценарий 3: ArgoCD ApplicationSet для ephemeral сред

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: preview-appset
  namespace: argocd
spec:
  generators:
  - pullRequest:
      github:
        owner: myorg
        repository: myapp
      requeueDuration: 5m
  template:
    metadata:
      name: 'preview-{{number}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/myorg/myapp
        targetRevision: '{{head_sha}}'
        path: kubernetes/preview
      destination:
        server: https://kubernetes.default.svc
        namespace: 'preview-{{number}}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
        - CreateNamespace=true
```

### Сценарий 4: Автоматическая очистка orphaned Secret

При удалении ephemeral namespace cert-manager не удаляет Secret с wildcard-сертификатом (если он в другом namespace). Настройте автоматическую очистку:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cleanup-stale-preview-secrets
  namespace: cert-manager
spec:
  schedule: "0 */6 * * *"  # Каждые 6 часов
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: cleanup
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              echo "[$(date)] Starting cleanup of stale preview secrets..."
              
              # Найти все preview namespace
              PREVIEW_NS=$(kubectl get ns -o json | jq -r '.items[] | select(.metadata.name | startswith("preview-")) | .metadata.name')
              
              for ns in $PREVIEW_NS; do
                # Проверить, есть ли Ingress в namespace
                INGRESS_COUNT=$(kubectl get ingress -n $ns --no-headers 2>/dev/null | wc -l)
                
                if [ "$INGRESS_COUNT" -eq 0 ]; then
                  echo "Namespace $ns has no Ingress - potential orphan"
                  # Найти и удалить osиротевшие TLS secrets
                  kubectl get secret -n $ns -o json | \
                    jq -r '.items[] | select(.type=="kubernetes.io/tls") | .metadata.name' | \
                    while read secret; do
                      echo "Deleting orphaned secret: $secret in $ns"
                      kubectl delete secret $secret -n $ns
                    done
                fi
              done
              
              echo "[$(date)] Cleanup complete"
          restartPolicy: OnFailure
```

---

## Дополнительная информация

### Ограничения и рекомендации

| Аспект | Рекомендация |
| :--- | :--- |
| **Wildcard vs Individual** | Используйте wildcard для <50 preview, individual для >50 |
| **DNS TTL** | Установите 300 сек для быстрого обновления |
| **Rate Limits** | Мониторьте `certmanager_http_acme_client_request_count` |
| **Очистка** | Настройте ownerReference или CronJob для удаления orphaned Secret |
| **Безопасность** | Не используйте wildcard для production-сред |
| **Staging** | Тестируйте конфигурацию через Let's Encrypt Staging |

### Смотрите также

- **[cert-manager + external-dns](../ingress/scenarios.md#сценарий-9-cert-manager--external-dns)** — полная автоматизация DNS + TLS.
- **[DNS-провайдеры](./dns_providers.md)** — настройка DNS-01 solver.
- **[Операции cert-manager](./operations.md)** — мониторинг rate limits.
- **[Мульти-тенантность](./multi_tenancy.md)** — изоляция preview namespace.
