# Ошибки загрузки образов (Image Pull Errors): Интеграция с CI/CD

## Определения

**Конвейер CI/CD (Pipeline)** — автоматизированная последовательность шагов сборки, тестирования и развертывания приложения. В контексте Image Pull конвейер отвечает за своевременную публикацию образа и обеспечение кластера правами доступа.

**Image Promotion (Продвижение образа)** — процесс перемещения или перетегирования проверенного образа между различными реестрами или пространствами имен (например, из `staging-reg` в `prod-reg`) без пересборки. Это гарантирует, что в продакшн попадет именно тот артефакт, который прошел тестирование.

**Wait-for-image (Ожидание образа)** — паттерн проектирования, предотвращающий запуск развертывания до момента физического завершения процесса Push образа в реестр и обновления манифестов.

**Workload Identity / OIDC** — механизмы аутентификации в реестрах без использования статических паролей, основанные на доверии между провайдером идентичности (Dex, Keycloak, HashiCorp Vault) и кластером Kubernetes. Kubernetes подписывает ServiceAccount-bound JWT, провайдер обменивает его на короткоживущий токен доступа к реестру.

**Эфемерные реестры (Ephemeral Registries)** — временные хранилища образов с коротким временем жизни (TTL), используемые для промежуточных сборок в динамических окружениях (например, `ttl.sh`).

---

## Основные концепции

### Взаимосвязь CI/CD и стабильности загрузки образов

Большинство ошибок загрузки в динамических средах являются следствием рассинхронизации между процессами сборки и развертывания.

| Проблема | Роль CI/CD | Решение |
| :--- | :--- | :--- |
| **Race Condition** | Deployment стартует до завершения Push образа. | Паттерн `Wait-for-image` на уровне пайплайна или K8s Init-контейнера. |
| **Expired Tokens** | Использование токенов с TTL (например, AWS ECR). | Использование **Workload Identity (IRSA/WIF)** или External Secrets Operator. |
| **Promotion Failure** | Ошибки при копировании образа между реестрами. | Использование специализированных утилит (Skopeo/Crane) вместо связки `docker pull/tag/push`. |
| **Tag Overwriting** | Использование `:latest` приводит к запуску неверной версии. | Принудительное использование уникальных тегов (SHA коммита) и неизменяемых репозиториев. |

### Стратегия Build Once, Deploy Anywhere

Для минимизации ошибок `ErrImagePull` рекомендуется использовать стратегию "одной сборки":
1.  Образ собирается один раз на этапе `build`.
2.  Образ помечается уникальным тегом (Commit SHA).
3.  Тот же самый дайджест образа продвигается (promote) через контуры (Dev -> Staging -> Prod) путем копирования манифестов, а не пересборки из исходников.

> Глубокое погружение в стратегии продвижения (включая Kustomize/Helm-инжекцию по SHA, ArgoCD Image Updater, подпись образов через Cosign) — см. [Image Promotion (CI/CD)](../../../../Docker/Docker_fs/images/promotion_cicd.md).

### Способы доставки секретов реестра в кластер

На on-prem-инсталляциях существует 4 основных способа, выбор между ними определяется требованиями к безопасности, временем жизни токена и сложностью эксплуатации.

| Способ | Плюсы | Минусы | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Статический `kubernetes.io/dockerconfigjson` Secret** | Прост в настройке, работает везде | Ручная ротация, риск утечки в Git | Dev/staging, low-trust реестры |
| **External Secrets Operator (Vault)** | Автоматическая ротация, единый источник | Требует Vault + ESO operator | Production с on-prem Vault |
| **OIDC Workload Identity (Dex/Keycloak)** | Нет секретов в кластере, короткоживущие токены | Требует Dex + OIDC-aware registry | Production с Harbor 2.4+ |
| **`imagePullSecrets` через ServiceAccount** | Централизованное управление в namespace | SA есть на каждый namespace | Mid-size кластеры с одним реестром |

**Жизненный цикл `docker-registry` Secret (создание → подвязка → ротация):**

1. **Создание** из `docker login` payload:
   ```bash
   kubectl create secret docker-registry regcred \
     --docker-server=registry.corp.local \
     --docker-username=ci-deployer \
     --docker-password=$(vault kv get -field=password secret/registry/ci) \
     --docker-email=ci@corp.local \
     -n production
   # Автоматически создаст type: kubernetes.io/dockerconfigjson
   kubectl get secret regcred -n production -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d
   ```
2. **Подвязка на уровне Pod** (вручную — в каждом манифесте):
   ```yaml
   spec:
     imagePullSecrets:
     - name: regcred
   ```
3. **Подвязка на уровне ServiceAccount** (рекомендуется — DRY):
   ```yaml
   apiVersion: v1
   kind: ServiceAccount
   metadata:
     name: my-app-sa
     namespace: production
   imagePullSecrets:
   - name: regcred
   # Все поды с этим SA наследуют секрет автоматически
   ```
4. **Ротация**:
   ```bash
   # Подготовить новый secret с новым паролем
   kubectl create secret docker-registry regcred-v2 \
     --docker-server=registry.corp.local \
     --docker-username=ci-deployer \
     --docker-password=$NEW_PASSWORD \
     -n production --dry-run=client -o yaml > regcred-v2.yaml
   kubectl apply -f regcred-v2.yaml
   # Обновить SA
   kubectl patch sa my-app-sa -n production \
     -p '{"imagePullSecrets":[{"name":"regcred-v2"}]}'
   # Удалить старый
   kubectl delete secret regcred -n production
   ```
5. **Альтернативная ротация без перезапуска подов** (через мягкий рестарт kubelet):
   ```bash
   # kubelet кеширует Secret в памяти; обновление Secret требует
   # перезапуска kubelet, но НЕ pods. На 100 узлах: Ansible/playbook
   ansible nodes -m service -a "name=kubelet state=restarted" -b
   ```

### Registry mirror и layered pull-through cache

Mirror-конфигурация в containerd/CRI-O позволяет перенаправить pull любого внешнего образа на локальный pull-through кэш **на уровне CRI**, до Kubernetes. Это решает сразу три проблемы: rate-limit на Docker Hub, долгий pull при холодном кэше, сетевую недоступность upstream.

**containerd (`/etc/containerd/config.toml`):**

```toml
[plugins."io.containerd.grpc.v1.cri"]
  # Per-host mirror: registry-1.docker.io → локальный кэш
  [plugins."io.containerd.grpc.v1.cri".registry]
    config_path = "/etc/containerd/certs.d"

  [plugins."io.containerd.grpc.v1.cri".registry.mirrors]
    [plugins."io.containerd.grpc.v1.cri".registry.mirrors."docker.io"]
      endpoint = ["https://harbor-cache.corp.local"]
    [plugins."io.containerd.grpc.v1.cri".registry.mirrors."registry.k8s.io"]
      endpoint = ["https://harbor-cache.corp.local"]
    [plugins."io.containerd.grpc.v1.cri".registry.mirrors."ghcr.io"]
      endpoint = ["https://harbor-cache.corp.local"]

  [[plugins."io.containerd.grpc.v1.cri".registry.mirrors."docker.io".hosts]]
    # fallback, если mirror недоступен
    endpoint = ["https://registry-1.docker.io"]
```

**CRI-O (`/etc/containers/registries.conf`):**

```ini
unqualified-search-registries = ["harbor-cache.corp.local"]

[[registry]]
location = "harbor-cache.corp.local"
insecure = false
blocked = false
mirror-on-pull = true   # при pull любого образа — сперва mirror

[[registry.mirror]]
location = "harbor-cache.corp.local"
```

> Подробно: [Pull-through кэш (Harbor/Nexus)](./common_errors.md#сценарий-11-локальный-pull-through-кэш-harborn-nexus-для-on-prem), [Air-gapped кластеры](./airgapped.md).

### Image Sign Verification на этапе CI

Подпись образа (Cosign/Notary v2) на этапе CI и проверка подписи на этапе CD через Kyverno/Connaisseur/Conftest — превращает pull в **доверенную операцию**: неподписанный или подделанный образ не запустится, даже если registry доступен.

**CI (Go-пример, Cosign keyless):**

```yaml
# .gitlab-ci.yml (фрагмент)
sign-image:
  stage: publish
  image: golang:1.22
  script:
  - go install github.com/sigstore/cosign/cmd/cosign@latest
  # keyless: используется OIDC-токен CI-раннера
  - cosign sign --yes registry.corp.local/my-app:$CI_COMMIT_SHA
  # Прозрачность лога сохраняется в Rekor
  - cosign verify --certificate-identity-regexp ".*" \
      --certificate-oidc-issuer-regexp ".*gitlab.*" \
      registry.corp.local/my-app:$CI_COMMIT_SHA
  artifacts:
    reports:
      container_scanning: gl-container-scanning-report.json
```

**CD (Kyverno ClusterPolicy):**

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signature
spec:
  validationFailureAction: Enforce
  rules:
  - name: verify-cosign
    match:
      any:
      - resources:
          kinds: ["Pod"]
    verifyImages:
    - imageReferences:
      - "registry.corp.local/*"
      attestors:
      - entries:
        - keys:
            publicKeys: |-
              -----BEGIN PUBLIC KEY-----
              MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
              -----END PUBLIC KEY-----
```

**Эффект:** при попытке запуска неподписанного образа Kyverno блокирует Pod, в `kubectl describe pod` видно `ImagePullBackOff` с `denied by policy verify-cosign`. Это **отдельный класс ошибок** от сетевых и auth-ошибок и должен распознаваться SRE как «проблема CI/CD pipeline», а не инфраструктуры.

### Проблема «поздней» секретной ротации в CI

Типичный CI-инцидент: пароль от Harbor в `.gitlab-ci.yml` или Vault KV-секрете истёк → все pull-job'ы падают с `401 Unauthorized`. Корень проблемы — отсутствие превентивной ротации и мониторинга «здоровья» секрета.

**Чек-лист:**
1. **TTL на уровне реестра** — Harbor поддерживает per-robot-account expiration (по умолчанию бесконечный). Установить 90 дней через API/UI.
2. **TTL на уровне Vault** — KV v2: `vault kv metadata put -custom-ttl=2160h secret/registry/ci`.
3. **Мониторинг** — алерт Prometheus за 7 дней до истечения:
   ```promql
   # Псев-запрос: получить secret из Vault и сравнить creation_time
   (time() - vault_secret_creation_time{path="secret/data/registry/ci"}) > 7776000
   ```
4. **Превентивный CI-step** перед `docker push`:
   ```yaml
   pre-push:
     script:
     - if ! curl -sSf -u $CI_USER:$CI_PASS https://harbor.corp.local/api/v2.0/ping; then
         echo "Registry credentials expired or invalid"
         exit 1
       fi
   ```

---

## Практические сценарии

### Сценарий 1: Продвижение образов через Skopeo (Promotion)

Использование `skopeo` позволяет копировать образы напрямую между реестрами, экономя время и дисковое пространство раннера.

**Копирование между реестрами:**
```bash
# Копирование из стейджинга в продакшн без скачивания слоев на хост
skopeo copy \
  --src-creds $STAGING_USER:$STAGING_PASS \
  --dest-creds $PROD_USER:$PROD_PASS \
  docker://staging-registry.io/my-app:v1.2.3 \
  docker://prod-registry.io/my-app:v1.2.3
```

### Сценарий 2: Паттерн Wait-for-image (K8s-native)

Если вы не можете гарантировать порядок завершения CI-джобов, используйте Init-контейнер для ожидания образа.

**Пример манифеста:**
```yaml
spec:
  initContainers:
  - name: wait-for-image
    image: curlimages/curl  # Или легковесный образ с skopeo/crane
    command:
    - "/bin/sh"
    - "-c"
    - |
      # Цикл ожидания доступности манифеста в реестре
      until curl -s -f -o /dev/null "https://registry.example.com/v2/my-app/manifests/v1.2.3"; do
        echo "Waiting for image..."
        sleep 5
      done
```

### Сценарий 3: Workload Identity через on-prem OIDC (Dex/Keycloak + Harbor)

Полное исключение `imagePullSecrets` из манифестов за счёт федерации идентичности между провайдером (Dex, Keycloak) и Harbor через OIDC-токен, подписанный Kubernetes.

**Архитектура потока:**

```
kubelet → pod SA token (projected ServiceAccountToken, JWT)
        → Dex (OIDC issuer, проверяет подпись kube-apiserver)
        → выдаёт ID-token (TTL 1h, audience=harbor-registry)
        → Harbor принимает токен, сопоставляет группу с robot-account
        → pull проходит без imagePullSecrets
```

**Шаг 1. Настройка Dex → Kubernetes connector:**

```yaml
# dex-config.yaml (staticPasswords отключены, только connectors)
connectors:
- type: kubernetes
  id: k8s
  name: Kubernetes
  config:
    issuer: https://kubernetes.default.svc.cluster.local
    # kube-apiserver проверяет ServiceAccountToken через TokenReview API
    audience: harbor
    # Bound claims: SA может быть ограничен группой
```

**Шаг 2. Аннотация ServiceAccount:**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app-sa
  namespace: production
  annotations:
    dex.coreos.com/group: "harbor-robot-deployers"   # группа в Dex
    dex.coreos.com/audience: "harbor"
automountServiceAccountToken: true   # иначе токен не проецируется в под
```

**Шаг 3. Token Projection API в pod:**

```yaml
spec:
  serviceAccountName: my-app-sa
  containers:
  - name: app
    volumeMounts:
    - name: oidc-token
      mountPath: /var/run/secrets/tokens
  volumes:
  - name: oidc-token
    projected:
      sources:
      - serviceAccountToken:
          path: harbor-token
          audience: harbor
          expirationSeconds: 3600
```

**Шаг 4. Harbor OIDC integration:**

- Harbor → Configuration → OIDC → Issuer = `https://dex.corp.local`, ClientID = `harbor`.
- Создать robot-account `ci-deployer` с правами `pull` на проект `my-app`.
- Dex-claim `groups` маппится на `harbor-robot-deployers` → robot-account активируется.

**Верификация:**

```bash
# 1. kubelet на узле подтягивает образ без dockerconfigjson
kubectl get pod -n production -l app=my-app -o yaml | grep -A2 imagePullSecrets
# → (пусто)  # imagePullSecrets отсутствуют, токен приходит из SA

# 2. В логах Harbor виден OIDC-flow
grep "oidc.*harbor" /var/log/harbor/core.log
# → oidc: token exchange succeeded, group=harbor-robot-deployers, robot=ci-deployer$my-app

# 3. Pull из пода (проверка токена)
kubectl exec -n production deploy/my-app -- cat /var/run/secrets/tokens/harbor-token | \
  cut -d. -f2 | base64 -d 2>/dev/null | jq '.aud, .exp - .iat'
# → "harbor"            # audience совпадает
# → 3600                # TTL = 1 час
```

**Преимущества перед статическим `docker-registry` secret:**
- Ротация автоматическая (TTL токена 1 ч), нет «забытых» паролей в Git.
- Audit-trail в Dex: кто, когда получил токен.
- Один и тот же SA работает на всех узлах — не нужно разворачивать `imagePullSecrets` через External Secrets.

> **Примечание:** для cloud-native реестров (ECR, GCR, ACR) шаги аналогичны — меняется только OIDC-issuer на `https://token.actions.githubusercontent.com` (для GH Actions) или нативный STS-эндпоинт облака. На on-prem этот сценарий покрывает любой реестр с поддержкой OIDC (Harbor 2.4+, Distribution 2.7+ с `token` extension).

### Сценарий 4: Эфемерные реестры для Review-окружений

Для временных веток (Pull Requests) использование основного реестра может привести к его замусориванию. Используйте `ttl.sh` — анонимный эфемерный реестр.

**CI-конвейер:**
```bash
# Образ будет автоматически удален через 24 часа
IMAGE_TAG="ttl.sh/my-app-pr-${PR_NUMBER}:24h"
docker build -t $IMAGE_TAG .
docker push $IMAGE_TAG
```

### Сценарий 5: Автоматизация секретов через External Secrets Operator (ESO)

Синхронизация учетных данных реестра из HashiCorp Vault напрямую в `imagePullSecrets`.

**Манифест ExternalSecret:**
```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: registry-auth
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: regcred
    template:
      type: kubernetes.io/dockerconfigjson
  data:
  - secretKey: .dockerconfigjson
    remoteRef:
      key: registry/production
```

**Расширенный шаблон (template) — формирование `dockerconfigjson` из отдельных полей:**

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: registry-auth-detailed
spec:
  refreshInterval: 15m
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: regcred
    template:
      type: kubernetes.io/dockerconfigjson
      templateFrom:
      - target: Data
        define:
          # Jinja2-шаблон: собираем base64-блок auths из отдельных полей
          auths: |
            {
              "{{ .server }}": {
                "username": "{{ .user }}",
                "password": "{{ .pass }}",
                "email": "{{ .email }}",
                "auth": "{{ .user }}:{{ .pass }} | b64enc"
              }
            }
  data:
  - secretKey: server
    remoteRef:
      key: registry/production
      property: host
  - secretKey: user
    remoteRef:
      key: registry/production
      property: username
  - secretKey: pass
    remoteRef:
      key: registry/production
      property: password
  - secretKey: email
    remoteRef:
      key: registry/production
      property: email
```

**Подвязка к ServiceAccount и мониторинг:**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: app-deployer
  namespace: production
imagePullSecrets:
- name: regcred
# ESO автоматически подхватит; SA применит секрет ко всем новым подам
```

```bash
# Проверить, что ESO обновил Secret
kubectl get externalsecret registry-auth -n production
# → STATUS: SecretSynced   # OK
# → STATUS: Error          # см. events

# Принудительно обновить (например, после ручной ротации в Vault)
kubectl annotate externalsecret registry-auth -n production \
  force-sync=$(date +%s) --overwrite
```

**Edge case — refresh race:**

Если pull-job в CI выполняется между моментом, когда Vault обновил пароль, и моментом, когда ESO синхронизировал Secret в кластер (типичный lag 5-30 секунд), возникнет `401 Unauthorized`. Решения:
1. Установить `refreshInterval: 1m` для критичных секретов (нагрузка на Vault растёт).
2. Использовать `rotationPolicy: ReadyForRotation` + ручной триггер через `kubectl annotate` в момент CI-деплоя.
3. Перейти на Workload Identity (Сценарий 3) — токены не устаревают, потому что выдаются по требованию.

### Сценарий 6: race condition при быстром CI-rollout

**Симптом:** после успешного `docker push` в рамках CI-пайплайна сразу же `kubectl apply -k overlays/prod` приводит к `ImagePullBackOff` у 1-3 из 20 реплик. В логах kubelet: `Back-off pulling image "registry.corp.local/my-app:abc123"`. Через 5-10 минут rollout завершается успешно (после back-off retry).

**Корневая причина:** между `push` (атомарная запись манифеста в registry) и моментом, когда kubelet реально может прочитать манифест, проходит **до 5-30 секунд** (распространение по CDN/кластеру реестра, инвалидация кешей, eventual consistency). Свежесозданный тег может быть виден на одних нодах реестра, но не на других.

**Пошаговая диагностика:**

```bash
# 1. С тестовой машины сразу после push — есть ли тег?
time skopeo inspect --tls-verify=true \
  docker://registry.corp.local/my-app:abc123
# → Если возвращает JSON < 1 сек: pull должен работать
# → Если connection refused / 404: тег ещё не реплицирован

# 2. С проблемной ноды (SSH) — есть ли тег?
ssh node-03 "crictl inspect registry.corp.local/my-app:abc123"
# → Сравнить с успешной нодой: crictl pull запускает GET /v2/<image>/manifests/<tag>

# 3. Посмотреть, как давно pod в ImagePullBackOff
kubectl get pod -l app=my-app -n production -o json | \
  jq '.items[] | {name: .metadata.name, age: .metadata.creationTimestamp,
    events: [.status.containerStatuses[]?.state] | .[0]}'
```

**Решения (выбрать одно или комбинировать):**

1. **Кратковременный sleep в CI (простое, но хрупкое):**
   ```yaml
   deploy-prod:
     stage: deploy
     script:
     - docker push $CI_REGISTRY/my-app:$CI_COMMIT_SHA
     - sleep 30    # ждём распространения тега
     - kubectl set image deploy/my-app my-app=$CI_REGISTRY/my-app:$CI_COMMIT_SHA
   ```

2. **Использование digest вместо tag (правильное):**
   ```bash
   # В CI: сразу после push получаем дайджест
   DIGEST=$(skopeo inspect --format '{{.Digest}}' \
     docker://$CI_REGISTRY/my-app:$CI_COMMIT_SHA)
   # Промоутим дайджест (immutable, реплицируется мгновенно)
   skopeo copy --src-creds $USER:$PASS --dest-creds $PROD_USER:$PROD_PASS \
     docker://$CI_REGISTRY/my-app@$DIGEST \
     docker://registry.corp.local/my-app:$CI_COMMIT_SHA
   # В kustomization.yaml — image зафиксирован по дайджесту:
   # images:
   #   - name: registry.corp.local/my-app
   #     newName: registry.corp.local/my-app
   #     digest: sha256:abc123...
   ```

3. **Init-контейнер `wait-for-image` (Сценарий 2 + exponential backoff):**
   ```yaml
   initContainers:
   - name: wait-for-image
     image: alpine:3.19
     command:
     - /bin/sh
     - -c
     - |
       set -eu
       # 1. Ждём, пока тег начнёт резолвиться
       for i in $(seq 1 30); do
         if skopeo inspect --tls-verify=false \
            docker://registry.corp.local/my-app:abc123 >/dev/null 2>&1; then
           echo "Image available after $i attempts"
           exit 0
         fi
         sleep $((i * 2))   # exponential: 2,4,6,8... секунды
       done
       echo "Image not available after 60s" >&2
       exit 1
   ```

4. **Pre-pull DaemonSet (для крупных образов):**
   ```yaml
   apiVersion: apps/v1
   kind: DaemonSet
   metadata:
     name: image-prepuller
     namespace: kube-system
   spec:
     updateStrategy:
       type: RollingUpdate
       rollingUpdate:
         maxUnavailable: 1
     template:
       spec:
         initContainers:
         - name: wait-and-prepull
           image: quay.io/skopeo/stable:v1.13
           command:
           - /bin/sh
           - -c
           - |
             # Получаем список тегов из ConfigMap, ждём каждый
             for img in $(cat /etc/tags-to-pull/* | tr '\n' ' '); do
               skopeo copy docker://$img docker-daemon:$img
             done
   ```

**Верификация (время rollout):**

```bash
time kubectl rollout status deploy/my-app -n production --timeout=5m
# До оптимизации: 3-7 минут (5-10 ретраев kubelet × back-off)
# После: 30-60 секунд (digest + 1 попытка)
```

Сценарий связан с [best_practices → §4 Троттлинг kubelet](./best_practices.md) и [common_errors → Сценарий 9 (лавина pull-запросов)](./common_errors.md#сценарий-9-лавина-pull-запросов-из-за-imagepullpolicy-always).

### Сценарий 7: cert-manager для TLS-сертификата on-prem реестра

**Симптом:** при pull с on-prem Harbor/Nexus возникает `x509: certificate signed by unknown authority`. Сертификат реестра — самоподписанный или выпущен корпоративным CA. При обновлении CA (истечение, ревокация) приходится вручную перезаливать `ca.crt` на всех узлах.

**Решение через cert-manager (автоматическая доставка CA на узлы):**

**Шаг 1. Issuer для корпоративного CA (step-ca или корпоративный Vault PKI):**

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: corp-ca-issuer
spec:
  url: https://pki.corp.local/acme/directory
  # или
  ca:
    secretName: corp-ca-secret
```

**Шаг 2. Сертификат для Harbor:**

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: harbor-tls
  namespace: harbor
spec:
  secretName: harbor-tls-secret
  issuerRef:
    name: corp-ca-issuer
    kind: ClusterIssuer
  dnsNames:
  - harbor.corp.local
  - registry.corp.local
  duration: 2160h   # 90 дней
  renewBefore: 720h  # за 30 дней до истечения
```

**Шаг 3. Автоматическая рассылка CA на узлы через DaemonSet:**

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: ca-bundle-sync
  namespace: kube-system
spec:
  updateStrategy:
    type: RollingUpdate
  template:
    spec:
      hostPID: true
      hostPath: {}
      tolerations:
      - operator: Exists
      containers:
      - name: sync
        image: alpine:3.19
        command:
        - /bin/sh
        - -c
        - |
          set -eu
          # Загружаем актуальный CA из Secret
          apk add --no-cache curl openssl ca-certificates
          curl -sf http://cert-manager.corp.local/ca-bundle.pem \
            -o /host/etc/ssl/certs/corp-ca-bundle.pem
          # Дёргаем kubelet/containerd reload
          systemctl reload containerd || true
          # Триггер: kubelet сам подхватит обновлённый bundle за счёт
          # периодического reload (/etc/ssl/certs обновлён)
          echo "CA bundle updated at $(date)" > /var/log/ca-sync.log
        volumeMounts:
        - name: host-certs
          mountPath: /host/etc/ssl/certs
        - name: host-pki
          mountPath: /host/etc/pki
        - name: host-pki-trust
          mountPath: /host/etc/pki/ca-trust/source/anchors
      volumes:
      - name: host-certs
        hostPath:
          path: /etc/ssl/certs
      - name: host-pki
        hostPath:
          path: /etc/pki
      - name: host-pki-trust
        hostPath:
          path: /etc/pki/ca-trust/source/anchors
```

**Верификация:**

```bash
# 1. Сертификат обновлён
openssl s_client -connect harbor.corp.local:443 -showcerts </dev/null 2>&1 | \
  openssl x509 -noout -dates
# → notBefore=Sep  4 00:00:00 2026 GMT
# → notAfter=Dec  3 00:00:00 2026 GMT   # 90 дней

# 2. CA доставлен на узел
ssh node-03 "openssl x509 -in /etc/ssl/certs/corp-ca-bundle.pem -noout -subject"
# → subject=O = Corp, OU = IT

# 3. Pull работает
kubectl run test --rm -it --image=alpine:3.19 -- \
  wget -O- https://harbor.corp.local/v2/_catalog
# → {"repositories":["my-app","ops-tools"]}
```

> Связано: [common_errors → Сценарий 7 (TLS/сертификаты)](./common_errors.md#сценарий-7-проблемы-с-tls-и-сертификатами-x509) и [network_issues → Сценарий 5 (TLS-инспекция прокси)](./network_issues.md#сценарий-5-tls-инспекция-на-корпоративном-прокси-ломает-pull-x509-signed-by-unknown-authority).

### Сценарий 8: namespace-scoped registry credential без повторения secret

**Проблема:** в кластере 50+ namespace, в каждом нужно `imagePullSecrets: regcred`. Создание secret вручную в каждом namespace при ротации — error-prone. Решение: один мастер-`Secret` + `imagePullSecrets` на уровне `ServiceAccount` через admission webhook или `cluster-admin`-template.

**Вариант A — шаблон через Kyverno (без дополнительных controller):**

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: inject-registry-credentials
spec:
  rules:
  - name: add-imagePullSecrets
    match:
      any:
      - resources:
          kinds: ["Pod"]
          namespaces: ["production", "staging"]
    mutate:
      patchStrategicMerge:
        spec:
          imagePullSecrets:
          - name: regcred
          # Kyverno добавит, если отсутствует (smart merge)
```

**Вариант B — cert-manager Vault Injector + ServiceAccount-anchor:**

```bash
# 1. Один раз создать regcred в namespace kube-system
kubectl create secret docker-registry regcred \
  --docker-server=registry.corp.local \
  --docker-username=ci-deployer \
  --docker-password=$(vault kv get -field=password secret/registry/ci) \
  -n kube-system

# 2. RBAC: разрешить SA из production читать secret из kube-system
cat > rbac-regcred-reader.yaml <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: kube-system
  name: regcred-reader
rules:
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["regcred"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  namespace: kube-system
  name: regcred-reader-binding
subjects:
- kind: ServiceAccount
  name: default
  namespace: production
roleRef:
  kind: Role
  name: regcred-reader
  apiGroup: rbac.authorization.k8s.io
EOF
kubectl apply -f rbac-regcred-reader.yaml

# 3. На каждом узле настроить kubelet на чтение из kube-system
# /var/lib/kubelet/config.yaml
# imageCredentialProviderConfig: /etc/kubernetes/cred-providers/...
# (см. kubelet Image Credential Provider для более гибкой схемы)
```

**Вариант C — Image Credential Provider (kubelet 1.26+)**:

Нативный механизм kubelet, который вызывает exec-плагин для получения credentials. Позволяет не хранить Secret в кластере вообще.

```yaml
# /etc/kubernetes/image-credentials.yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: CredentialProviderConfig
providers:
- name: harbor-cred-provider
  apiVersion: credentialprovider.kubelet.k8s.io/v1
  matchImages:
  - "registry.corp.local/*"
  - "harbor-cache.corp.local/*"
  args:
  - /usr/local/bin/harbor-cred-helper
  env:
  - name: VAULT_ADDR
    value: "https://vault.corp.local"
  - name: VAULT_ROLE
    value: "kubelet-harbor"
```

```go
// harbor-cred-helper.go (упрощённо) — вызывается kubelet перед pull
package main

import (
  "encoding/json"
  "os"
  credentialprovider "k8s.io/kubernetes/pkg/credentialprovider"
)

func main() {
  // Запрашиваем токен в Vault по AppRole
  token := vaultLogin(os.Getenv("VAULT_ROLE"))
  // Возвращаем JSON-структуру, понятную kubelet
  out := credentialprovider.DockerConfigJSON{
    Auths: map[string]credentialprovider.DockerConfig{
      "registry.corp.local": {
        Username: "kubelet",
        Password: token,
      },
    },
  }
  json.NewEncoder(os.Stdout).Encode(out)
}
```

```bash
# /var/lib/kubelet/config.yaml
imageCredentialProviderConfig: /etc/kubernetes/image-credentials.yaml
# Перезапустить kubelet на всех узлах
ansible nodes -m service -a "name=kubelet state=restarted" -b
```

**Проверка:**

```bash
# 1. Kyverno (вариант A): pod в production автоматически получает imagePullSecrets
kubectl get pod -n production -o json | jq '.items[].spec.imagePullSecrets'
# → [{"name":"regcred"}]

# 2. Image Credential Provider (вариант C): в логах kubelet
journalctl -u kubelet | grep -i "credential"
# → credentialprovider: harbor-cred-provider matched image registry.corp.local/my-app:abc123
# → credentialprovider: returned fresh token, ttl=3599s
```

### Сценарий 9: ImageGC конфликтует с активным CI-pull

**Симптом:** при `kubectl rollout` Deployment kubelet на одном узле возвращает `image not found (manifest unknown)` несмотря на то, что `skopeo inspect` с тестовой машины показывает тег как доступный. Через 30-60 секунд pull проходит.

**Корневая причина:** ImageGC (garbage collection) на узле удалил локальный layer этого образа в промежутке между предыдущим `crictl pull` (когда узел принял решение, что образ не нужен) и текущим `pull` (когда он снова понадобился). При `imagePullPolicy: IfNotPresent` kubelet **не проверяет** registry повторно, а ImageGC удаляет слои при достижении порога.

**Диагностика:**

```bash
# 1. На проблемном узле — что в локальном кеше containerd
ssh node-03 "crictl images | grep my-app"
# → registry.corp.local/my-app:abc123    110MB     <-- есть
# или
# → (пусто)    # <-- ImageGC удалил

# 2. История GC на узле
journalctl -u kubelet --since "1h ago" | grep -i "imagegc"
# → ImageGC: removed image registry.corp.local/my-app:v1.0, age=72h, total=12GB

# 3. Текущие пороги GC
ssh node-03 "cat /var/lib/kubelet/config.yaml | grep -A4 imageGCHighThresholdPercent"
# → imageGCHighThresholdPercent: 85
# → imageGCLowThresholdPercent: 80
```

**Решения:**

1. **Принудительный `imagePullPolicy: Always` для критичных приложений** (если rollout редкий):
   ```yaml
   spec:
     containers:
     - name: app
       image: registry.corp.local/my-app:abc123
       imagePullPolicy: Always   # НЕ IfNotPresent
   ```

2. **Переопределение порогов GC на уровне кластера** (если 85/80 — слишком агрессивно):
   ```bash
   # /var/lib/kubelet/config.yaml
   imageGCHighThresholdPercent: 90
   imageGCLowThresholdPercent: 85
   # ImageGC запустится, только если диск заполнен на 90%
   ```

3. **Pre-pull через DaemonSet** (Сценарий 6, вариант 4) — после успешного деплоя запустить DaemonSet с `image: registry.corp.local/my-app:abc123`, чтобы заполнить кеш.

4. **Мониторинг ImageGC** (см. Сценарий 10).

### Сценарий 10: метрики и алерты для CI/CD pull-здоровья

Чтобы SRE-команда видела деградации до того, как они приведут к `ImagePullBackOff` в проде, нужно собирать метрики со всех слоёв pipeline'а.

**Prometheus-метрики, которые нужно собирать:**

| Метрика | Источник | Назначение |
| :--- | :--- | :--- |
| `kubelet_image_pull_latency_seconds_*` | kubelet `/metrics` | Гистограмма длительности pull |
| `kubelet_image_pull_errors_total{reason}` | kubelet `/metrics` | Счётчик ошибок с reason (ErrImagePull, ImagePullBackOff) |
| `containerd_image_pull_duration_seconds` | containerd `/metrics/v1` (v1.7+) | Латентность на уровне CRI |
| `harbor_pull_through_cache_hit_ratio` | Harbor Prometheus exporter | Эффективность mirror |
| `external_secrets_sync_status{secret, status}` | ESO `/metrics` | Свежесть синхронизации Secret |
| `vault_kv_secret_age_seconds{path}` | vault-exporter | Возраст секрета (для алерта ротации) |
| `image_pull_throttle_count` | kubelet `/metrics` (если включён) | Количество throttled pull'ов |

**Сбор метрик kubelet (если не используется managed Prometheus):**

```yaml
# /etc/prometheus/prometheus.yml (фрагмент)
scrape_configs:
- job_name: kubelet
  scheme: https
  tls_config:
    ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    insecure_skip_verify: true
  bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
  kubernetes_sd_configs:
  - role: node
  relabel_configs:
  - target_label: __address__
    replacement: kubernetes.default.svc:443
  - source_labels: [__meta_kubernetes_node_name]
    target_label: instance
  metric_relabel_configs:
  - source_labels: [__name__]
    regex: kubelet_image_pull_.*
    action: keep
```

**Алерты (Alertmanager rules):**

```yaml
groups:
- name: image_pull
  rules:
  # 1. Высокая доля ошибок pull
  - alert: ImagePullErrorRateHigh
    expr: |
      rate(kubelet_image_pull_errors_total[5m])
      / rate(kubelet_image_pull_latency_seconds_count[5m]) > 0.05
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Image pull error rate > 5% на {{ $labels.instance }}"
      runbook: https://wiki.corp/runbooks/image-pull-errors

  # 2. Медленный pull (p95 > 60s)
  - alert: ImagePullLatencyHigh
    expr: |
      histogram_quantile(0.95,
        rate(kubelet_image_pull_latency_seconds_bucket[10m])
      ) > 60
    for: 15m
    labels:
      severity: warning

  # 3. Secret реестра не обновлялся > 80 дней (предупреждение за 10 до истечения)
  - alert: RegistrySecretAging
    expr: time() - vault_kv_secret_age_seconds{path=~".*registry.*"} > 6912000
    for: 1h
    labels:
      severity: warning
    annotations:
      summary: "Registry secret {{ $labels.path }} старше 80 дней"

  # 4. ImageGC удалил > 30% образов за час
  - alert: ImageGCAgressive
    expr: |
      rate(kubelet_image_gc_removed_total[1h]) > 0.3
    labels:
      severity: info
```

**Grafana-дашборд (минимальный набор панелей):**

1. **Pull success rate** — `1 - (rate(kubelet_image_pull_errors_total[5m]) / rate(kubelet_image_pull_latency_seconds_count[5m]))`. Зелёный > 99%, жёлтый 95-99%, красный < 95%.
2. **Pull p95 latency** — `histogram_quantile(0.95, ...)`. Линия тренда.
3. **Pull errors by reason** — `sum by (reason) (rate(kubelet_image_pull_errors_total[5m]))`. Видно, растут ли 401 (проблема секрета) или 429 (rate limit).
4. **ImageGC removed per hour** — стэковая диаграмма по образам.
5. **Registry secret age** — gauge.

---

## Дополнительная информация

### Чек-лист CI/CD-здоровья pull (от простого к сложному)

| Шаг | Команда / действие | Что проверяет | Ожидаемый результат |
| :--- | :--- | :--- | :--- |
| 1 | `kubectl get events -A --field-selector reason=Failed` за последний час | Свежие `Failed` события | Только известные плановые (CronJob) |
| 2 | `kubectl get pods -A -o json \| jq '.items[].status.containerStatuses[]? \| select(.state.waiting.reason=="ImagePullBackOff")'` | Текущие зависшие поды | `[]` (пусто) в healthy-кластере |
| 3 | `skopeo inspect docker://registry.corp.local/my-app:$TAG` с CI-runner | Образ доступен из CI-сети | JSON-ответ за < 2 сек |
| 4 | `kubectl get externalsecret -A -o json \| jq '.items[] \| select(.status.conditions[]?.type=="Ready" and .status=="False")'` | ESO в ошибке | `[]` (все SecretSynced) |
| 5 | `time crictl pull registry.corp.local/my-app:$TAG` на проблемном узле | Pull от kubelet | < 60 сек, без retries |
| 6 | Проверка `kubelet_image_pull_errors_total` в Prometheus | Error rate за 5 мин | < 1% (warn), < 5% (page) |
| 7 | `kubelet_image_pull_latency_seconds` p95 | Скорость pull | < 30 сек (warn), < 60 сек (page) |
| 8 | Сравнение `crictl images` на двух узлах | Консистентность кеша | Один набор образов на всех узлах |
| 9 | `journalctl -u containerd --since "15m ago" \| grep -i "back-off\|throttl"` | Троттлинг | Пусто (или rate-limit в норме) |
| 10 | `dmesg \| tail -50 \| grep -i "nf_conntrack\|tcp"` на проблемном узле | Сетевые ошибки | Пусто (или единичные) |

### Типичные антипаттерны CI/CD → pull-ошибки

| Антипаттерн | Симптом | Корректная практика |
| :--- | :--- | :--- |
| `image: my-app:latest` в production-манифесте | Случайный pull промежуточной сборки | Всегда тег по `$CI_COMMIT_SHA` или digest |
| Один `imagePullSecrets` в `default` namespace, но манифесты в `production` | `ImagePullBackOff` на новых namespace'ах | `imagePullSecrets` на уровне ServiceAccount или Kyverno-инжекция |
| `docker login` внутри CI-job'а, передача `--password` через `--password-stdin` | Пароль в логах pipeline'а (видно SRE) | OIDC Workload Identity или короткоживущий токен через Vault |
| Ручной `kubectl create secret docker-registry` в каждом namespace | 50 namespace × 30 минут на ротацию | ESO + ClusterSecretStore, один ExternalSecret на namespace |
| `sleep 30` после `docker push` для «распространения тега» | Непредсказуемый rollout, flaky в CI | Промоут по digest, init-контейнер с exponential backoff |
| Pull напрямую с docker.io без mirror | `429 Too Many Requests` при CI-burst | Настроить `registry.mirrors` в containerd + Harbor cache |
| `imagePullPolicy: Always` для всех deployment'ов | Шторм pull при каждом pod-restart | `IfNotPresent` + ImageGC тюнинг, `Always` только для mutable images |
| Хардкод пароля в CI Variables без `masked: true` / `protected: true` | Утечка в GitLab CI logs | Vault dynamic secrets + краткоживущие токены |
| Отсутствие Image Sign Verification (Cosign) | Запуск неавторизованных образов из compromised registry | Kyverno verifyImages + keyless Cosign в CI |

### Связанные темы

- [Image Promotion (CI/CD)](../../../../Docker/Docker_fs/images/promotion_cicd.md) — глубокое погружение в стратегии Build Once, продвижение по digest, ArgoCD Image Updater.
- [Внешние менеджеры секретов](../../../Base/secrets/external_managers.md) — настройка Vault, External Secrets Operator, AppRole и Kubernetes auth.
- [Распространённые ошибки Image Pull](./common_errors.md) — разбор кодов 401, 403, 429, TLS, race conditions и pull-through cache.
- [NetworkPolicy и доступ к реестру](./network_policy_impact.md) — влияние NetworkPolicy и GlobalNetworkPolicy на image pull.
- [Pod Security Standards и image pull](./pod_security_standards.md) — PSS/PSA и их влияние на загрузку образов.
- [HPA и автоскейлинг](./hpa_and_scaling.md) — влияние масштабирования на image pull и rate limiting.
- [Init-контейнеры и image pull](./init_container_image_pulls.md) — проблемы pull в init-контейнерах.

