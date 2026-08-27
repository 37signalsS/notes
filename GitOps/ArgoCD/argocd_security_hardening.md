# Argo CD: Безопасность — hardening, GPG, NetworkPolicies, mTLS и proxy

> **Актуальность (2026):** Argo CD v3.x поддерживает GPG-подпись коммитов (GPG Commit Verification), mTLS между компонентами, NetworkPolicies для сетевой изоляции, настройку proxy для доступа к внешним репозиториям, OPA/Gatekeeper интеграцию и securityContext для Pod Security Standards. Ключевые области: аутентификация (SSO/JWT), авторизация (RBAC), защита секретов, сетевая безопасность, подпись манифестов.

## Предварительные требования

1. **Argo CD установлен** (см. [Установка и настройка](./argocd_installation_and_setup.md)).
2. **kubectl** с доступом к namespace `argocd`.
3. **argocd CLI** настроен.
4. **Понимание RBAC** (см. [RBAC](./argocd_rbac_deep.md)).
5. **Понимание AppProject** (см. [AppProject](./argocd_appproject_deep.md)).

## Определения

**Hardening (Усиление безопасности)** — процесс повышения безопасности Argo CD через настройку NetworkPolicies, SecurityContext, RBAC, mTLS и других механизмов.

**GPG Commit Verification (Проверка подписи коммитов)** — механизм Argo CD, проверяющий GPG-подпись Git-коммитов перед рендерингом манифестов. Гарантирует, что манифесты не были изменены неавторизованными лицами.

**mTLS (Mutual TLS)** — двусторонняя аутентификация TLS между компонентами Argo CD. Каждый компонент подтверждает свою личность через сертификат.

**NetworkPolicy (Сетевая политика)** — Kubernetes-объект, ограничивающий сетевой трафик между подами. Используется для изоляции компонентов Argo CD друг от друга и от внешних сервисов.

**Proxy** — промежуточный сервер для доступа Argo CD к внешним репозиториям (Git, Docker Registry). Используется в corporate средах для контроля трафика.

**SecurityContext** — контейнер-специфичные настройки безопасности: runAsNonRoot, readOnlyRootFilesystem, capabilities drop.

**Pod Security Standards (PSS)** — Kubernetes-механизм контроля безопасности подов на уровне namespace (Privileged, Baseline, Restricted).

## Базовые концепции

### Архитектура безопасности Argo CD

```text
┌─────────────────────────────────────────────────┐
│  Внешний доступ (UI/CLI/API)                     │
│  ├── SSO (OIDC/LDAP)                            │
│  ├── JWT tokens                                  │
│  └── TLS termination (Ingress/Gateway)           │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│  argocd-server                                   │
│  ├── RBAC (policy.csv)                           │
│  ├── Rate Limiting                               │
│  └── Audit Logging                               │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│  argocd-application-controller                   │
│  ├── NetworkPolicy (ограничение трафика)          │
│  ├── SecurityContext (runAsNonRoot)               │
│  └── mTLS (между компонентами)                   │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│  argocd-repo-server                              │
│  ├── GPG signature verification                  │
│  ├── Git credentials isolation                   │
│  └── tmpfs (без persistent state)                │
└─────────────────────────────────────────────────┘
```

## Практические сценарии

### Сценарий 1: GPG подпись коммитов

Включение проверки GPG-подписей Git-коммитов.

**1. Добавление GPG-ключей в Argo CD:**
```bash
# Импорт публичного ключа
gpg --export --armor <KEY_ID> > /tmp/public-key.asc

# Создание секрета
kubectl create secret generic argocd-gpg-keys \
  --from-file=public.asc=/tmp/public.asc \
  -n argocd
```

**2. Настройка Argo CD:**
```yaml
# argocd-gpg-keys-cm ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-gpg-keys-cm
  namespace: argocd
data:
  # ID ключа: публичный ключ
  <KEY_ID>: |
    -----BEGIN PGP PUBLIC KEY BLOCK-----
    <GPG PUBLIC KEY>
    -----END PGP PUBLIC KEY BLOCK-----
```

**3. Включение проверки на AppProject:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production
spec:
  signatureKeys:
    - keyID: "<GPG_KEY_ID>"  # Обязательная GPG-подпись для production
```

**4. Проверка подписи:**
```bash
# Argo CD автоматически проверяет GPG-подпись при каждом коммите
# Если коммит не подписан или подпись невалидна — рендеринг блокируется

# Просмотр статуса проверки
argocd app get my-app -o json | jq '.status.conditions'
```

### Сценарий 2: NetworkPolicies для изоляции

Ограничение сетевого трафика между компонентами Argo CD.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: argocd-controller-network-policy
  namespace: argocd
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argocd-application-controller
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Разрешить входящий трафик только от repo-server
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: argocd-repo-server
      ports:
        - port: 8082
          protocol: TCP
  egress:
    # Разрешить трафик к Kubernetes API
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              component: kube-apiserver
      ports:
        - port: 6443
          protocol: TCP
    # Разрешить DNS
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
```

**NetworkPolicy для repo-server:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: argocd-repo-server-network-policy
  namespace: argocd
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argocd-repo-server
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Разрешить от controller
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: argocd-application-controller
      ports:
        - port: 8081
          protocol: TCP
    # Разрешить от server
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: argocd-server
      ports:
        - port: 8081
          protocol: TCP
  egress:
    # Разрешить Git (SSH/HTTPS)
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - port: 22
          protocol: TCP
        - port: 443
          protocol: TCP
    # Разрешить DNS
    - to:
        - namespaceSelector: {}
      ports:
        - port: 53
          protocol: UDP
```

### Сценарий 3: SecurityContext для Pod Security Standards

Настройка securityContext для подов Argo CD.

```yaml
# argocd-application-controller Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: argocd-application-controller
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 999
        runAsGroup: 999
        fsGroup: 999
      containers:
        - name: argocd-application-controller
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop:
                - ALL
            seccompProfile:
              type: RuntimeDefault
          volumeMounts:
            - name: tmp
              mountPath: /tmp
            - name: argocd-repo-server-tls
              mountPath: /app/config/ssh
              readOnly: true
      volumes:
        - name: tmp
          emptyDir: {}
        - name: argocd-repo-server-tls
          secret:
            secretName: argocd-repo-server-tls
```

### Сценарий 4: mTLS между компонентами

Включение взаимной аутентификации TLS.

**1. Генерация сертификатов:**
```bash
# Генерация CA
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /tmp/ca.key -out /tmp/ca.crt \
  -subj "/CN=argocd-ca"

# Генерация сертификата для repo-server
openssl req -nodes -newkey rsa:2048 \
  -keyout /tmp/repo-server.key -out /tmp/repo-server.csr \
  -subj "/CN=argocd-repo-server.argocd.svc"

openssl x509 -req -in /tmp/repo-server.csr \
  -CA /tmp/ca.crt -CAkey /tmp/ca.key -CAcreateserial \
  -out /tmp/repo-server.crt -days 365
```

**2. Создание Secrets:**
```bash
kubectl create secret tls argocd-repo-server-tls \
  --cert=/tmp/repo-server.crt \
  --key=/tmp/repo-server.key \
  -n argocd
```

**3. Настройка controller:**
```yaml
# argocd-cm ConfigMap
data:
  # Включение mTLS
  server.insecure: "false"
  
  # TLS для repo-server
  reposerver.strict.tls: "true"
```

### Сценарий 5: Proxy для доступа к Git

Настройка прокси для corporate сред.

```yaml
# Deployment controller
env:
  - name: HTTP_PROXY
    value: "http://proxy.example.com:8080"
  - name: HTTPS_PROXY
    value: "http://proxy.example.com:8080"
  - name: NO_PROXY
    value: "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.cluster.local,argocd-repo-server"
```

**Важно:** `NO_PROXY` должен включать:
- Внутренние сети (pod CIDR, service CIDR)
- `.cluster.local` (Kubernetes DNS)
- `argocd-repo-server` (для mTLS)

### Сценарий 6: Audit Logging

Включение аудита действий пользователей.

```yaml
# argocd-cm ConfigMap
data:
  # Уровень аудита
  server.audit.enabled: "true"
  
  # Формат логов
  server.log.format: "json"
  
  # Уровень логирования
  server.log.level: "info"
```

**Просмотр аудит-логов:**
```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server | jq '.msg'
# → {"msg":"login","user":"admin","ip":"10.0.0.1"}
# → {"msg":"sync","app":"my-app","user":"sre-team"}
```

### Сценарий 7: Ограничение доступа к exec/terminal

Запрет выполнения команд в подах через Argo CD.

```yaml
# argocd-rbac-cm ConfigMap
data:
  policy.csv: |
    # Запрет exec для всех кроме admin
    p, role:readonly, exec, create, */*, deny
    p, role:admin, exec, create, */*, allow
    
    # Запрет terminal для CI/CD ботов
    p, role:ci-bot, exec, create, */*, deny
```

## Диагностика

### Базовые команды

```bash
# Проверка GPG ключей
kubectl get configmap argocd-gpg-keys-cm -n argocd -o yaml

# Просмотр NetworkPolicy
kubectl get networkpolicy -n argocd

# Проверка SecurityContext
kubectl get deployment argocd-application-controller -n argocd -o jsonpath='{.spec.template.spec.securityContext}'

# Просмотр TLS секретов
kubectl get secret argocd-repo-server-tls -n argocd -o yaml

# Проверка proxy настроек
kubectl get deployment argocd-application-controller -n argocd -o jsonpath='{.spec.template.spec.containers[0].env}'
```

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `GPG signature verification failed` | Коммит не подписан или ключ невалиден | Импортируйте публичный ключ |
| `connection refused` (mTLS) | Сертификат не настроен или невалиден | Проверьте сертификаты и CA |
| `network policy blocks traffic` | NetworkPolicy блокирует компоненты | Добавьте разрешающие правила |
| `proxy connection timeout` | Прокси недоступен или неправильный `NO_PROXY` | Проверьте прокси и исключения |

## Лучшие практики

- **GPG для production:** Всегда включайте проверку GPG-подписей для production-проектов.
- **NetworkPolicy:** Настройте изоляцию между компонентами Argo CD в production.
- **SecurityContext:** Используйте `runAsNonRoot`, `readOnlyRootFilesystem`, `capabilities.drop: ALL`.
- **mTLS:** Включите взаимную аутентификацию TLS для всех компонентов.
- **Audit Logging:** Включите аудит-логирование для отслеживания действий пользователей.
- **Proxy:** Настройте `NO_PROXY` для внутренних сервисов.

## Ограничения и edge cases

### Ограничения

- **GPG требует публичный ключ:** Argo CD не может проверить подпись без публичного ключа.
- **NetworkPolicy не блокирует DNS:** Стандартные NetworkPolicy не ограничивают DNS-запросы.
- **mTLS требует сертификатов:** Необходимо управлять жизненным циклом сертификатов.
- **Proxy может замедлить работу:** Прокси добавляет задержку к Git-операциям.

### Edge Cases

- **GPG ключ истёк:** Argo CD блокирует рендеринг до обновления ключа.
- **NetworkPolicy + Calico/Cilium:** Расширенные NetworkPolicy (GlobalNetworkPolicy) могут потребовать дополнительных CRD.
- **mTLS + Istio:** При работе с service mesh конфликтуют сертификаты.
- **Proxy + WebSockets:** Некоторые прокси не поддерживают WebSockets (UI теряет связь).

## Дополнительная информация

### См. также

- [RBAC](./argocd_rbac_deep.md)
- [AppProject](./argocd_appproject_deep.md)
- [Установка и настройка](./argocd_installation_and_setup.md)
- [Уведомления](./argocd_notifications.md)
- [Мультитенантность](./argocd_multi_tenancy.md) — Паттерны мультитенантности, tenant isolation, project-per-team.
- [Disaster Recovery](./argocd_disaster_recovery.md) — Бэкап, восстановление, etcd snapshot, HA, geo-recovery.
- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — Multiple Sources, sourceHydrator, Helm+Git, CI-рендеринг vs Multi-Source.
- [Отслеживание ресурсов](./argocd_resource_tracking.md) — Методы отслеживания ресурсов: Label, Annotation, Annotation+Label.
- [Удаление и очистка](./argocd_deletion_and_cleanup.md) — Prune, Cascading Deletion, Propagation Policy, Orphan, Finalizers.

### Ссылки

- [GPG Signature Verification](https://argo-cd.readthedocs.io/en/stable/user-guide/gpg-verification/)
- [Security Best Practices](https://argo-cd.readthedocs.io/en/stable/operator-manual/security/)
- [Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
