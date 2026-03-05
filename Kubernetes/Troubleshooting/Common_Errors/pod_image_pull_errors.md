# Проблемы с загрузкой образов (`ImagePullBackOff` / `ErrImagePull`)

## Определения

**`ErrImagePull`** — начальная ошибка, означающая, что `kubelet` не может скачать образ контейнера из репозитория.

**`ImagePullBackOff`** — состояние, в которое переходит под после нескольких неудачных попыток скачивания образа. `kubelet` увеличивает задержку между попытками (exponential backoff).

> - Docker Registry: [`docker_registries.md`](../../../Docker/Docker_registries/docker_registries.md)
> - GitLab CI/CD: [`ci_cd_pipeline_overview.md`](../../../CI-CD/GitLab_CI/Tutorials/ci_cd_pipeline_overview.md)
> - ArgoCD: [`argocd_troubleshooting_and_monitoring.md`](../../../GitOps/ArgoCD/argocd_troubleshooting_and_monitoring.md)
> - Secrets: [`external_managers.md`](../../Base/secrets/external_managers.md)

**Backoff задержки:** 10s → 20s → 40s → 80s → 160s → 300s (максимум)

## Основные концепции

### Workflow загрузки образа

```
Pod создан
    ↓
kubelet на узле получает задачу
    ↓
Проверка локального кэша
    ↓
Образ не найден → Запрос в registry
    ↓
Аутентификация (если приватный)
    ↓
Скачивание слоев
    ↓
Распаковка и запуск
```

### ImagePullPolicy

| Политика | Поведение | Когда использовать |
|----------|-----------|-------------------|
| **`IfNotPresent`** | Использовать кэш, если есть; иначе скачать | Production (по умолчанию для `:tag`) |
| **`Always`** | Всегда скачивать свежий образ | Production (по умолчанию для `:latest`) |
| **`Never`** | Использовать только локальный образ | Offline-кластеры, тестирование |

> **Best Practice:** Избегайте тега `:latest` в production. Используйте конкретные версии или SHA256 digest.

### Типы репозиториев

| Тип | Примеры | Аутентификация |
|-----|---------|----------------|
| **Публичные** | Docker Hub, GHCR | Не требуется (для публичных образов) |
| **Приватные** | Docker Hub, GCR, ECR, Harbor | `imagePullSecrets` |
| **Локальные** | Internal registry, air-gapped | Self-signed cert, offline tokens |

## Практические сценарии

### Диагностика: пошаговый чек-лист

#### Шаг 1: Проверка статуса пода

```bash
kubectl describe pod <pod-name>
```

**Ищите в разделе `Events`:**
```
Type     Reason     Age                From               Message
----     ------     ----               ----               -------
Warning  Failed     2m (x4 over 3m)    kubelet            Failed to pull image "my-app:1.1": rpc error: code = Unknown desc = Error response from daemon: manifest for my-app:1.1 not found
Warning  Failed     2m (x4 over 3m)    kubelet            Error: ErrImagePull
Normal   BackOff    1m (x6 over 2m)    kubelet            Back-off pulling image "my-app:1.1"
Warning  Failed     1m (x6 over 2m)    kubelet            Error: ImagePullBackOff
```

#### Шаг 2: Проверка имени образа

```bash
# Извлечение имени образа из пода
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].image}'

# Проверка наличия образа в registry
docker pull <image-name>
# или
crane pull <image-name> <local-file>
```

#### Шаг 3: Проверка imagePullSecrets

```bash
# Проверка secrets в поде
kubectl get pod <pod-name> -o jsonpath='{.spec.imagePullSecrets}'

# Проверка существования secret
kubectl get secret <secret-name> -o yaml

# Проверка типа secret
kubectl get secret <secret-name> -o jsonpath='{.type}'
```

#### Шаг 4: Проверка сети и DNS

```bash
# Проверка доступности registry с узла
ssh <node-name> "curl -I https://registry.example.com"

# Проверка DNS
ssh <node-name> "nslookup registry.example.com"

# Проверка firewall правил
ssh <node-name> "telnet registry.example.com 443"
```

### Распространенные случаи и решения

#### 1. Неверное имя или тег образа

**Сообщение:**
```
manifest for my-app:1.1 not found
manifest unknown: manifest unknown
```

**Причина:** Опечатка в имени, тег не существует, образ удален.

**Решение:**
```yaml
# ❌ Ошибка
spec:
  containers:
  - name: app
    image: myregistry.io/my-app:1.1  # Опечатка или несуществующий тег

# ✅ Решение
spec:
  containers:
  - name: app
    image: myregistry.io/my-app:1.2  # Исправленный тег
```

**Проверка:**
```bash
# Список тегов в registry (для Docker Hub)
curl -s https://hub.docker.com/v2/repositories/<user>/<repo>/tags?page_size=100

# Для Harbor
curl -k https://harbor.example.com/api/v2.0/projects/<project>/repositories/<repo>/artifacts
```

#### 2. Проблемы с доступом к приватному репозиторию

**Сообщение:**
```
unauthorized: authentication required
pull access denied for my-app, repository does not exist or may require 'docker login'
```

**Причина:** Отсутствует или неверно настроен `imagePullSecrets`.

**Решение:**

##### Создание imagePullSecret

```bash
# Способ 1: kubectl create secret
kubectl create secret docker-registry regcred \
  --docker-server=https://registry.example.com \
  --docker-username=<username> \
  --docker-password=<password> \
  --docker-email=<email> \
  -n <namespace>

# Способ 2: из существующего docker config
kubectl create secret generic regcred \
  --from-file=.dockerconfigjson=$HOME/.docker/config.json \
  --type=kubernetes.io/dockerconfigjson \
  -n <namespace>
```

##### Привязка secret к Pod

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  containers:
  - name: app
    image: registry.example.com/my-app:1.0
  imagePullSecrets:
  - name: regcred
```

##### Привязка secret к ServiceAccount (автоматически для всех подов)

```bash
kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "regcred"}]}' \
  -n <namespace>
```

> **См. также:** [`ci_cd_pipeline_overview.md`](../../../CI-CD/GitLab_CI/Tutorials/ci_cd_pipeline_overview.md) — интеграция с GitLab Deploy Tokens

#### 3. Образ не существует

**Сообщение:**
```
manifest unknown: manifest unknown
404 Not Found
```

**Причина:** Образ никогда не был загружен в репозиторий, удален, или неверно указан path.

**Решение:**
```bash
# Проверка наличия образа
docker pull <image-name>

# Для CI/CD: убедиться, что image build шаг выполнен успешно
# Проверить pipeline в GitLab CI / GitHub Actions
```

**Best Practice:** Используйте immutable tags (SHA256 digest) в production:
```yaml
image: myregistry.io/my-app@sha256:abc123...
```

#### 4. Сетевые проблемы

**Сообщение:**
```
dial tcp: lookup registry.example.com: no such host
connection timed out
x509: certificate signed by unknown authority
```

**Причины и решения:**

| Проблема | Диагностика | Решение |
|----------|-------------|---------|
| **DNS** | `nslookup registry.example.com` | Исправить DNS настройки узла |
| **Firewall** | `telnet registry.example.com 443` | Открыть порт, добавить whitelist |
| **Proxy** | Проверить env vars | Настроить `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` |
| **Self-signed cert** | `curl -v https://registry` | Добавить CA cert в доверенные на узлах |

**Настройка proxy для kubelet:**
```ini
# /etc/systemd/system/kubelet.service.d/http-proxy.conf
[Service]
Environment="HTTP_PROXY=http://proxy.example.com:3128"
Environment="HTTPS_PROXY=http://proxy.example.com:3128"
Environment="NO_PROXY=localhost,127.0.0.1,.cluster.local"
```

**Настройка для containerd:**
```toml
# /etc/containerd/config.toml
[plugins."io.containerd.grpc.v1.cri".registry.mirrors."registry.example.com"]
  endpoint = ["http://proxy-registry.internal:5000"]
```

#### 5. Rate Limiting (Docker Hub)

**Сообщение:**
```
toomanyrequests: You have reached your pull rate limit.
```

**Причина:** Docker Hub ограничивает количество скачиваний для анонимных и бесплатных аккаунтов.

**Решение:**
| Вариант | Описание |
|---------|----------|
| **Аутентификация** | `imagePullSecrets` увеличивает лимит |
| **Локальный mirror** | Развернуть Harbor/Nexus как proxy-cache |
| **Переход на другой registry** | GCR, ECR, GHCR имеют лучшие лимиты |
| **Pre-pull образы** | Скачать образы на узлы заранее |

#### 6. Проблемы с Network Policies

**Сообщение:**
```
connection timed out
dial tcp <ip>:443: i/o timeout
```

**Причина:** Network Policy блокирует исходящий трафик к registry.

**Диагностика:**
```bash
kubectl get networkpolicy -n <namespace>
kubectl describe networkpolicy <policy-name>
```

**Решение:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-registry-access
  namespace: <namespace>
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: <registry-ip>/32
    ports:
    - protocol: TCP
      port: 443
```

> **См. также:** [`network_policies.md`](../../Security/network_policies.md), [`calico.md`](../../Security/network_policies/calico.md)

#### 7. Air-gapped кластеры (offline)

**Проблема:** Нет доступа к внешним registry.

**Решение:**
```bash
# 1. Скачать образы на машине с доступом
docker pull my-app:1.0
docker save -o my-app.tar my-app:1.0

# 2. Передать в offline-кластер
scp my-app.tar offline-node:

# 3. Загрузить в локальный registry
docker load -i my-app.tar
docker tag my-app:1.0 local-registry:5000/my-app:1.0
docker push local-registry:5000/my-app:1.0
```

**Использование в манифесте:**
```yaml
containers:
- name: app
  image: local-registry:5000/my-app:1.0
imagePullPolicy: IfNotPresent  # Использовать локальный кэш
```

> **См. также:** [`offline_airgapped_installation.md`](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/offline_airgapped_installation.md)

### Интеграция с CI/CD

#### GitLab CI/CD

```yaml
# .gitlab-ci.yml
deploy:
  stage: deploy
  image: bitnami/kubectl
  script:
  - kubectl create secret docker-registry regcred \
    --docker-server=$CI_REGISTRY \
    --docker-username=$CI_REGISTRY_USER \
    --docker-password=$CI_REGISTRY_PASSWORD \
    --namespace=$KUBE_NAMESPACE \
    --dry-run=client -o yaml | kubectl apply -f -
  - kubectl patch serviceaccount default -p '{"imagePullSecrets": [{"name": "regcred"}]}' -n $KUBE_NAMESPACE
```

> **См. также:** [`gitlab_kubernetes_integration_guide.md`](../../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md)

#### ArgoCD

ArgoCD автоматически использует `imagePullSecrets`, указанные в манифесте. Убедитесь, что secret создан в том же namespace, где развертывается приложение.

## Дополнительная информация

### Best Practices

| Практика | Описание |
|----------|----------|
| **Используйте конкретные теги** | Избегайте `:latest`, используйте `:v1.2.3` или SHA256 |
| **Настройте imagePullSecrets глобально** | Привяжите secret к `default` ServiceAccount |
| **Используйте private registry** | Harbor, Nexus, ECR для контроля доступа |
| **Кэшируйте образы на узлах** | Уменьшает время запуска и нагрузку на registry |
| **Мониторьте rate limits** | Алерты на ошибки аутентификации |

### Мониторинг и алерты

```yaml
# Prometheus alert для ImagePullBackOff
- alert: ImagePullBackOff
  expr: kube_pod_container_status_waiting_reason{reason="ImagePullBackOff"} == 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Pod {{ $labels.pod }} ImagePullBackOff"
    description: "Container {{ $labels.container }} не может скачать образ"
```

### Таблица решений

| Симптом | Первая команда | Вероятное решение |
|---------|----------------|-------------------|
| `manifest not found` | `kubectl describe pod` | Исправить имя/тег образа |
| `unauthorized` | `kubectl get pod -o jsonpath='{.spec.imagePullSecrets}'` | Создать/исправить imagePullSecret |
| `connection timed out` | `ssh node curl -I registry` | Проверить сеть, firewall, proxy |
| `toomanyrequests` | `kubectl describe pod` | Аутентификация или mirror registry |
| `x509: unknown authority` | `kubectl describe pod` | Добавить CA cert на узлы |

### Ссылки

- [Kubernetes Images](https://kubernetes.io/docs/concepts/containers/images/)
- [Docker Hub Rate Limiting](https://docs.docker.com/docker-hub/download-rate-limit/)
- [Pull Private Container Images](https://kubernetes.io/docs/tasks/configure-pod-container/pull-image-private-registry/)
