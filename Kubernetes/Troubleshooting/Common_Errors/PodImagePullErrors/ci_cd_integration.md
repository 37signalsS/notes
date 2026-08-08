# Ошибки загрузки образов (Image Pull Errors): Интеграция с CI/CD

## Определения

**Конвейер CI/CD (Pipeline)** — автоматизированная последовательность шагов сборки, тестирования и развертывания приложения. В контексте Image Pull конвейер отвечает за своевременную публикацию образа и обеспечение кластера правами доступа.

**Image Promotion (Продвижение образа)** — процесс перемещения или перетегирования проверенного образа между различными реестрами или пространствами имен (например, из `staging-reg` в `prod-reg`) без пересборки. Это гарантирует, что в продакшн попадет именно тот артефакт, который прошел тестирование.

**Wait-for-image (Ожидание образа)** — паттерн проектирования, предотвращающий запуск развертывания до момента физического завершения процесса Push образа в реестр и обновления манифестов.

**Workload Identity / OIDC** — механизмы аутентификации в облачных реестрах (ECR, GCR, ACR) без использования статических паролей, основанные на доверии между облачным провайдером и кластером Kubernetes.

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

### Сценарий 3: Использование Workload Identity (IRSA в AWS)

Полное исключение `imagePullSecrets` из манифестов за счет федерации идентичностей.

1.  **Создание IAM роли** с правами `AmazonEC2ContainerRegistryReadOnly`.
2.  **Аннотирование ServiceAccount** в Kubernetes:
    ```yaml
    apiVersion: v1
    kind: ServiceAccount
    metadata:
      name: my-app-sa
      annotations:
        eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/my-app-ecr-role
    ```
3.  **Kubelet** автоматически использует эту роль для получения временного токена при обращении к ECR.

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
apiVersion: external-secrets.io/v1beta1
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
      key: secret/data/registry/production
```

---

## Дополнительная информация

### Связанные темы

- [Лучшие практики](./best_practices.md) — стратегии управления тегами и GC.
- [Распространённые ошибки](./common_errors.md) — детальный разбор кодов 401, 403, 429.
- [Image Promotion (CI/CD)](../../../../Docker/Docker_fs/images/promotion_cicd.md) — глубокое погружение в стратегии продвижения артефактов.
- [External Secrets Operator](../../Base/secrets/external_managers.md) — настройка провайдеров секретов.
- [Workload Identity](../../../../Cloud/Concepts/workload_identity.md) — общие принципы облачной идентификации.

