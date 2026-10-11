# Стратегии промоушена артефактов в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

## Предварительные требования

### Версии компонентов

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| GitLab | 17.0+ | Deployment Approval Policies — с 19.0+, External Deployment Approvals — с 19.2+ |
| GitLab Runner | 17.0+ | Docker executor для dind, Kubernetes executor |
| Docker | 24.x+ | Для build/push/pull образов в CI |
| Helm | 3.22+ | Для promotion Helm chart |
| Kubernetes | 1.29+ | Целевой кластер для deploy |
| Container registry | Любой OCI-совместимый | GitLab Container Registry, Harbor, Nexus, Quay |

### Инфраструктура

- **Сети:** CI Runner имеет сетевой доступ до registry и Kubernetes API. Задержка между Runner и registry < 100 ms.
- **Registry:** Раздельные репозитории или namespace для dev/staging/prod с разными правами доступа.
- **Хранилище:** Registry поддерживает immutable tags (`Content-Tag: immutable`) или lifecycle policies для production.
- **Secrets:** Protected/Masked переменные для registry credentials, Cosign keys, Kubernetes kubeconfig.
- **Права:** Maintainer или выше для deployment в production; Developer для staging.

### Знания

- Структура `.gitlab-ci.yml`, стадии, `rules`, `needs`, `environment`
- Основы registry и OCI digest
- Kubernetes Deployment, imagePullPolicy, rollout
- Helm release management, values overlay per environment

## Определения

**Image promotion (промоушен артефактов)** — процесс переноса протестированного артефакта (образа, пакета) из одной среды в другую (dev → staging → production) без пересборки. Гарантирует, что в продакшене работает побайтово идентичный артефакт, который прошёл все тесты.

**Immutable artifact (неизменяемый артефакт)** — артефакт, который не может быть изменён после создания. В контексте контейнеров — образ, привязанный к digest (SHA256), а не к тегу, который может быть перезаписан.

**Digest** — SHA256-хеш манифеста образа. Уникальный идентификатор образа, который не меняется при перезаписи тега.

**Tag** — человекочитаемое имя образа (например, `v1.0.0`, `latest`). Может быть перезаписан, поэтому не является неизменяемым.

**Promotion pipeline** — отдельный пайплайн или job, который отвечает за перенос артефакта между окружениями. Не зависит от build-пайплайна.

**Promotion gate** — ручное или автоматическое подтверждение перед промоушеном. Обычно включает: approval от SRE, проверка результатов тестов, проверка подписи образа.

**Build Once, Deploy Many** — принцип одной сборки и многократного деплоя того же артефакта между окружениями.

**Promotion strategy** — подход к переносу артефактов между окружениями:
- **Push-based:** Build pipeline push'ит артефакт в следующий environment
- **Pull-based:** Deployment pipeline pull'ит артефакт из registry по digest
- **GitOps-based:** Обновление тега/digest в GitOps-репозитории

**RTO / RPO при промоушене** — целевые показатели времени восстановления и потерь данных при сбое deployment. Для promotion: RTO = время отката к предыдущему digest, RPO = 0 при immutable артефактах.

## Основные концепции

### Архитектура промоушена артефактов

```
Build (dev) → Test → Registry (dev)
                               ↓
                          Promotion Gate
                               ↓
                          Registry (staging)
                               ↓
                          Test (staging)
                               ↓
                          Promotion Gate
                               ↓
                          Registry (production)
                               ↓
                          Deploy (production)
```

### Жизненный цикл промоушена

1. **Build:** Сборка образа, тегирование `$CI_COMMIT_SHA`, push в registry.
2. **Test:** Запуск тестов в dev/staging. Результаты сохраняются как artifacts.
3. **Gate:** Ручной approval или автоматическая проверка (scan, signature, tests).
4. **Promote:** Перенос digest между registry или репозиториями без rebuild.
5. **Deploy:** Применение manifest/deployment с новым digest.
6. **Verify:** Smoke-тесты, health-check, метрики.
7. **Audit:** Запись события в GitLab audit log с ID пайплайна, коммитом, approver'ом.

### Сравнение стратегий промоушена

| Стратегия | Механизм | Плюсы | Минусы | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **Push-based** | Build pipeline push'ит в staging/prod | Простота реализации | Build pipeline имеет доступ к prod registry | Для небольших команд |
| **Pull-based** | Deploy pipeline pull'ит из registry по digest | Изоляция окружений | Сложнее управление версиями | Для production |
| **GitOps-based** | ArgoCD/Flux синхронизирует manifests | Полная аудитория, declarative | Требует GitOps infrastructure | Для enterprise |
| **Manual promotion** | Ручной approval gate | Максимальный контроль | Замедляет доставку | Для production |

### Registry-стратегии

| Стратегия | Описание | Безопасность | Сложность |
| :--- | :--- | :--- | :--- |
| **Один registry, разные namespace** | `registry.example.com/dev/*`, `staging/*`, `prod/*` | Средняя (общий контроль доступа) | Низкая |
| **Раздельные registry** | Отдельный registry для prod с WORM/storage policy | Высокая (изоляция, отдельные ACL) | Средняя |
| **GitLab Container Registry** | Встроенный registry, project/group-level permissions | Средняя (зависит от GitLab RBAC) | Низкая |
| **Harbor / Nexus / Quay** | Enterprise registry с replication, scanning, retention | Высокая ( enterprise controls, robot accounts) | Средняя |

### Типы артефактов

| Тип | Пример | Промоушен |
| :--- | :--- | :--- |
| **Container image** | Docker, OCI | Tag + digest |
| **Helm chart** | .tgz | Chart version + app version |
| **Package** | npm, PyPI, Maven | Version + metadata |
| **Binary** | executable, jar | Version + checksum |
| **SBOM** | CycloneDX, SPDX | Attached to image |

### Сравнение environment scope и deployment tier

| Environment | deployment_tier | Approval | Scan requirement | Retention |
| :--- | :--- | :--- | :--- | :--- |
| development | development | Нет | Базовый | 7 дней |
| staging | testing | Опционально | SAST + container scan | 30 дней |
| production | production | Обязательно (Manual / Policy) | SAST + DAST + container scan + dependency scan | 90 дней |

## Практические сценарии

### Сценарий 1: Push-based промоушен через GitLab CI

```yaml
stages:
  - build
  - test
  - promote
  - deploy

build_dev:
  stage: build
  image: docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
    - echo "IMAGE_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA)" >> build.env
  artifacts:
    reports:
      dotenv: build.env
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

test_dev:
  stage: test
  script:
    - docker run --rm $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA npm test
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

promote_staging:
  stage: promote
  image: docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker pull $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
    - docker tag $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA \
        $CI_REGISTRY/$CI_PROJECT_PATH:staging
    - docker push $CI_REGISTRY/$CI_PROJECT_PATH:staging
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false

deploy_staging:
  stage: deploy
  image: bitnami/kubectl:1.30
  script:
    - kubectl set image deployment/myapp \
        myapp=$CI_REGISTRY/$CI_PROJECT_PATH:staging \
        -n staging
    - kubectl rollout status deployment/myapp -n staging --timeout=300s
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

promote_production:
  stage: promote
  image: docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker pull $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
    - docker tag $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA \
        $CI_REGISTRY/$CI_PROJECT_PATH:production
    - docker push $CI_REGISTRY/$CI_PROJECT_PATH:production
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false

deploy_production:
  stage: deploy
  image: bitnami/kubectl:1.30
  script:
    - kubectl set image deployment/myapp \
        myapp=$CI_REGISTRY/$CI_PROJECT_PATH:production \
        -n production
    - kubectl rollout status deployment/myapp -n production --timeout=300s
  environment:
    name: production
    deployment_tier: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

**Валидация:**
- `docker inspect` в staging/prod показывает тот же digest, что и в dev.
- `kubectl rollout status` завершается успешно в течение timeout.
- Deployment Approval Policy для production требует минимум 1 approve.
- Audit log содержит событие promotion с `CI_PIPELINE_ID`, approver, commit SHA.

### Сценарий 2: Immutable промоушен через digest

```yaml
stages:
  - build
  - test
  - promote
  - deploy

build:
  stage: build
  image: docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
    # Получение digest
    - DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA | cut -d@ -f2)
    - echo "IMAGE_DIGEST=$DIGEST" >> image.env
  artifacts:
    reports:
      dotenv: image.env
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

promote:
  stage: promote
  image: docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - |
      # Промоушен по digest (immutable)
      SOURCE_IMAGE="$CI_REGISTRY/$CI_PROJECT_PATH@$IMAGE_DIGEST"
      TARGET_IMAGE="$CI_REGISTRY/$CI_PROJECT_PATH:staging"

      docker pull $SOURCE_IMAGE
      docker tag $SOURCE_IMAGE $TARGET_IMAGE
      docker push $TARGET_IMAGE

      # Верификация
      TARGET_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' $TARGET_IMAGE | cut -d@ -f2)
      if [ "$TARGET_DIGEST" != "$IMAGE_DIGEST" ]; then
        echo "ERROR: Digest mismatch!"
        exit 1
      fi
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false

deploy:
  stage: deploy
  image: bitnami/kubectl:1.30
  script:
    - |
      # Деплой по digest (immutable)
      kubectl set image deployment/myapp \
        myapp="$CI_REGISTRY/$CI_PROJECT_PATH@$IMAGE_DIGEST" \
        -n production
    - kubectl rollout status deployment/myapp -n production --timeout=300s
  environment:
    name: production
    deployment_tier: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

**Валидация:**
- `kubectl describe deployment/myapp -n production` показывает `Image: registry/...@sha256:...`.
- `docker inspect` staging и production образов возвращает одинаковый digest.
- `imagePullPolicy: Always` отключен для production; используется конкретный digest.

### Сценарий 3: GitLab Environment Promotion с approval policies

```yaml
stages:
  - build
  - test
  - promote

build:
  stage: build
  image: docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

test:
  stage: test
  script:
    - docker run --rm $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA npm test
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

promote_to_staging:
  stage: promote
  image: docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker tag $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA \
        $CI_REGISTRY/$CI_PROJECT_PATH:staging
    - docker push $CI_REGISTRY/$CI_PROJECT_PATH:staging
  environment:
    name: staging
    url: https://staging.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false

promote_to_production:
  stage: promote
  image: docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker tag $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA \
        $CI_REGISTRY/$CI_PROJECT_PATH:production
    - docker push $CI_REGISTRY/$CI_PROJECT_PATH:production
  environment:
    name: production
    url: https://example.com
    deployment_tier: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
  # Deployment Approval Policy (GitLab 19.0+)
  # Settings → CI/CD → Deployment approval policy
  # Требует approve от Maintainer для production
```

**Валидация:**
- GitLab UI: `Operate > Environments` показывает окружения staging и production с deployment history.
- Promoted job заблокирован до approve, если настроена Deployment Approval Policy.
- Audit log содержит событие promotion с approver.

### Сценарий 4: Автоматический промоушен через API

```yaml
stages:
  - build
  - test
  - promote

build:
  stage: build
  image: docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

test:
  stage: test
  script:
    - docker run --rm $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA npm test
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

promote:
  stage: promote
  image: curlimages/curl:8.7
  script:
    - |
      # Автоматический промоушен через trigger API
      curl --request POST \
        --header "JOB-TOKEN: $CI_JOB_TOKEN" \
        --header "Content-Type: application/json" \
        --data "{
          \"ref\": \"main\",
          \"variables\": {
            \"PROMOTE_SOURCE\": \"$CI_COMMIT_SHA\",
            \"PROMOTE_TARGET\": \"staging\"
          }
        }" \
        "$CI_API_V4_URL/projects/$CI_PROJECT_ID/trigger/pipeline"
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Валидация:**
- Trigger API возвращает `201 Created` с ID нового pipeline.
- Downstream pipeline содержит `PROMOTE_SOURCE` и `PROMOTE_TARGET` переменные.
- Cross-project trigger имеет отдельный audit trail.

### Сценарий 5: Promotion gate с проверкой подписи

Для полного цикла подписи и SBOM используйте [SBOM и подпись артефактов](../Advanced/sbom_and_artifact_signing.md). Ниже — проверка подписи как gate перед promotion в production.

```yaml
stages:
  - build
  - promote

build:
  stage: build
  image: docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

promote_to_production:
  stage: promote
  image: gcr.io/projectsigstore/cosign:v2.4.0
  script:
    - |
      # Проверка подписи перед промоушеном (gate)
      cosign verify \
        --certificate-identity-regexp '^https://gitlab\.com/org/.*$' \
        --certificate-oidc-issuer https://gitlab.com \
        $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA

      # Промоушен только если подпись валидна
      docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
      docker pull $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA
      docker tag $CI_REGISTRY/$CI_PROJECT_PATH:$CI_COMMIT_SHA \
          $CI_REGISTRY/$CI_PROJECT_PATH:production
      docker push $CI_REGISTRY/$CI_PROJECT_PATH:production
  environment:
    name: production
    deployment_tier: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

**Валидация:**
- `cosign verify` возвращает `Verified` и Chain of Trust.
- При невалидной подписи job завершается с ошибкой, promotion блокируется.
- `COSIGN_EXPERIMENTAL=1` не требуется для keyless verification с OIDC.

### Сценарий 6: Промоушен Helm chart

```yaml
stages:
  - build
  - package
  - promote
  - deploy

build:
  stage: build
  script:
    - helm dependency build charts/myapp
    - helm lint charts/myapp
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

package:
  stage: package
  image: alpine/helm:3.22
  script:
    - helm package charts/myapp --destination ./dist/
    - curl --header "JOB-TOKEN: $CI_JOB_TOKEN" \
        --upload-file ./dist/myapp-*.tgz \
        "$CI_API_V4_URL/projects/$CI_PROJECT_ID/packages/helm/api/stable/charts"
  artifacts:
    paths:
      - ./dist/*.tgz
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

promote:
  stage: promote
  image: alpine/helm:3.22
  script:
    - |
      # Промоушен chart в staging
      helm upgrade --install myapp ./charts/myapp \
        --namespace staging \
        --values values-staging.yaml \
        --set image.tag=$CI_COMMIT_SHA \
        --wait --timeout 5m
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false

deploy:
  stage: deploy
  image: alpine/helm:3.22
  script:
    - |
      # Промоушен в production
      helm upgrade --install myapp ./charts/myapp \
        --namespace production \
        --values values-production.yaml \
        --set image.tag=$CI_COMMIT_SHA \
        --wait --timeout 10m
  environment:
    name: production
    deployment_tier: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

**Валидация:**
- `helm history myapp -n staging` показывает новую ревизию.
- `helm get values myapp -n production` подтверждает правильный `image.tag`.
- `helm list --all-namespaces` не содержит failed/pending релизов после deploy.

### Сценарий 7: Promotion с проверкой сканирования уязвимостей

```yaml
stages:
  - build
  - scan
  - promote_staging
  - deploy_staging
  - promote_prod

build:
  stage: build
  image: docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

security_scan:
  stage: scan
  image: aquasec/trivy:0.74.0
  needs:
    - build
  script:
    - trivy image --exit-code 1 --severity HIGH,CRITICAL $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  allow_failure: true

promote_staging:
  stage: promote_staging
  needs:
    - security_scan
  script:
    - echo "Promoting to staging..."
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false

deploy_staging:
  stage: deploy_staging
  image: bitnami/kubectl:1.30
  needs:
    - promote_staging
  script:
    - kubectl set image deployment/my-app app=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA -n staging
    - kubectl rollout status deployment/my-app -n staging --timeout=300s
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

promote_prod:
  stage: promote_prod
  needs:
    - deploy_staging
  script:
    - echo "Promoting to production..."
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

**Валидация:**
- Trivy возвращает `exit code 0` или `1` с отчетом. При `HIGH/CRITICAL` promotion в staging блокируется.
- Deployment Approval Policy требует approve перед production.
- Staging smoke-тесты проходят успешно.

### Сценарий 8: Promotion через GitLab API (скрипт promotion)

```bash
#!/bin/bash
# promote_to_prod.sh
# Продвижение артефакта из staging в production через GitLab API

set -euo pipefail

SOURCE_PROJECT="group/myapp-staging"
TARGET_PROJECT="group/myapp-production"
PIPELINE_ID=$CI_PIPELINE_ID
PROMOTION_TOKEN=$PROMOTION_API_TOKEN

# Получаем артефакт из staging-пайплайна
ARTIFACT_URL=$(curl -s --header "PRIVATE-TOKEN: $PROMOTION_TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$SOURCE_PROJECT/pipelines/$PIPELINE_ID/jobs" \
  | jq -r '.[] | select(.name=="build_image") | .artifacts[0].url')

# Скачиваем manifest с digest'ом
curl -s --header "PRIVATE-TOKEN: $PROMOTION_TOKEN" "$ARTIFACT_URL" > manifest.yaml

# Запускаем prod-пайплайн с продвигаемым digest'ом
curl -s --request POST \
  --header "PRIVATE-TOKEN: $PROMOTION_TOKEN" \
  --header "Content-Type: application/json" \
  "https://gitlab.example.com/api/v4/projects/$TARGET_PROJECT/trigger/pipeline" \
  --data "{
    \"ref\": \"$CI_DEFAULT_BRANCH\",
    \"variables\": {
      \"PROMOTED_DIGEST\": \"$(grep DIGEST manifest.yaml | cut -d: -f2-)\",
      \"PROMOTED_COMMIT\": \"$CI_COMMIT_SHA\",
      \"PROMOTED_BY\": \"$GITLAB_USER_NAME\"
    }
  }"
```

**Валидация:**
- Trigger API возвращает `201 Created` с pipeline ID.
- Prod-пайплайн получает `PROMOTED_DIGEST` и использует его для deploy.
- Audit log содержит событие cross-project promotion.

## Операции и команды

### GitLab CI — управление окружениями и approval gates

| Действие | Команда / Конфигурация | Результат |
| :--- | :--- | :--- |
| **Ручной promotion gate** | `when: manual` в правиле stage | Пайплайн останавливается и ждет нажатия кнопки |
| **Approval policy** | `Settings > CI/CD > Deployment approval policy` | Требует approve от указанных пользователей/ролей перед деплоем |
| **TTL approval'а** | Время жизни approval по умолчанию — 30 дней | Ограничьте через политику или reminder, чтобы артефакт не устарел |
| **Environment URL** | `environment:url: https://staging.example.com` | В интерфейсе GitLab появляется кнопка просмотра окружения |
| **Rollback environment** | Перезапуск предыдущего пайплайна с тем же digest'ом | Быстрый возврат к стабильной версии без новой сборки |

### Docker — работа с registry и digest

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Получить digest образа** | `docker inspect --format='{{index .RepoDigests 0}}' $IMAGE` | `registry.example.com/my-app@sha256:abc123...` |
| **Переместить образ между реестрами** | `docker pull $SRC@$DIGEST && docker tag $SRC@$DIGEST $DST:$TAG && docker push $DST:$TAG` | Тот же дайджест в целевом реестре |
| **Проверить immutability** | `docker manifest inspect $IMAGE@$DIGEST` | Дайджест не меняется при повторном push |
| **Сканировать образ** | `trivy image --exit-code 1 --severity HIGH,CRITICAL $IMAGE` | Ненулевой exit code при наличии критичных уязвимостей |

### Kubernetes — применение манифестов с pinned digest

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Применить манифест** | `kubectl apply -f k8s/` | Манифест применен, статус rollout отслеживается |
| **Откатить к предыдущему digest** | `kubectl rollout undo deployment/my-app` | Возврат к предыдущей ревизии Deployment |
| **Проверить историю ревизий** | `kubectl rollout history deployment/my-app` | Список ревизий с изменениями |
| **Откатить к конкретной ревизии** | `kubectl rollout undo deployment/my-app --to-revision=3` | Возврат к указанной ревизии |

### Helm — продвижение chart с values

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Упаковать chart** | `helm package mychart/ --destination ./` | Файл `mychart-0.1.0.tgz` готов к promotion |
| **Lint chart** | `helm lint ./mychart-*.tgz` | Проверка на корректность шаблонов и схемы |
| **Установить/обновить в staging** | `helm upgrade --install myapp ./mychart-*.tgz --namespace staging --values values-staging.yaml --set image.tag=$DIGEST --wait --timeout 5m` | Релиз установлен/обновлен в staging |
| **Просмотр ревизий** | `helm history myapp -n staging` | Список ревизий релиза |
| **Откат Helm-релиза** | `helm rollback myapp 1 -n staging` | Возврат к ревизии 1 |

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `Image not found` при промоушене | Тег не pushed или registry недоступен | Проверьте push в предыдущем stage |
| `Digest mismatch` | Образ был перезаписан между build и promote | Используйте immutable tags и digest-based promotion |
| `Approval gate expired` | Approval был запрошен неделю назад | Ограничьте TTL approval'а 24 часами |
| `Rollback по digest не работает` | Deployment использует tag вместо digest | Используйте immutable imagePullPolicy и конкретный digest |
| `SBOM attestation not found` | Аттестация не была создана | Проверьте stage sbom и sign; детали см. в [SBOM и подпись артефактов](../Advanced/sbom_and_artifact_signing.md) |

## Восстановление (Cleanup)

### Откат deployment к предыдущему digest

```bash
# Kubernetes: откат к предыдущей ревизии
kubectl rollout undo deployment/my-app -n production
kubectl rollout status deployment/my-app -n production --timeout=300s

# Helm: откат к предыдущей ревизии
helm rollback myapp 1 -n production
helm history myapp -n production
```

### Очистка orphaned образов в registry

```bash
# GitLab Container Registry: удалить устаревший тег
curl --request DELETE \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/registry/repositories/$REGISTRY_ID/tags/staging"

# Harbor: удаление по digest
curl -X DELETE \
  "https://harbor.example.com/api/v2.0/projects/myproject/repositories/myapp/tags/staging" \
  -u admin:Harbor12345
```

### Отмена stuck approval gate

```bash
# Перезапуск pipeline для сброса approval gate
curl --request POST \
  --header "JOB-TOKEN: $CI_JOB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/pipelines/$CI_PIPELINE_ID/retry"
```

## Best Practices

### Разработка (Dev)

1. **Используйте immutable артефакты:** Digest + immutable tags, запретите перезапись `:latest`.
2. **Промоушен по digest:** Никогда не используйте теги для промоушена между окружениями.
3. **Автоматизируйте тесты после промоушена:** Staging — это не production, тестируйте.
4. **Версионируйте артефакты:** Семантическое версионирование (SemVer) для Helm charts, пакетов.
5. **Храните SBOM с артефактом:** Attach SBOM к образу в registry.

### Эксплуатация (DevOps/SRE)

1. **Ограничьте TTL approval'ов:** 24 часа максимум. После истечения — повторный промоушен.
2. **Автоматизируйте откат:** При проблемах в production — автоматический откат на предыдущий digest.
3. **Мониторьте промоушен:** Время от build до deploy — ключевая DORA-метрика.
4. **Используйте separate registry для production:** Разные registry или репозитории для staging/prod.
5. **Аудит промоушенов:** Все промоушены логируются в GitLab audit log.
6. **Resource group для production:** Используйте `resource_group: production` для предотвращения параллельных деплоев.
7. **DORA-метрики:** Используйте `deployment_tier: production` для корректного расчета Deployment Frequency и Change Failure Rate.

### Sysadmin

1. **Запретите перезапись тегов в production:** Настройте registry policy.
2. **Включите Content Trust:** Только подписанные артефакты могут быть промоушенены в production.
3. **Настройте lifecycle policies:** Автоматически удаляйте устаревшие теги.
4. **Ограничьте доступ к production registry:** Только CI/CD service account имеет права push.
5. **Registry мониторинг:** Следите за quota, throughput, error rate registry.
6. **Immutable storage для production registry:** WORM/append-only на уровне storage защищает от ransomware.
7. **Secrets isolation:** Секреты production scope не доступны в staging/development.

## Граничные случаи

### Air-gapped среды

В изолированных сетях promotion невозможен через стандартный registry. Решение — внутренний registry (Harbor, Nexus) с репликой или физическая доставка артефакта (sneakernet). Настройте pull-through cache на каждом Runner.

### Registry недоступен во время promotion

Если registry недоступен, promotion блокируется. Настройте fallback на локальный registry-кэш (Docker Registry Mirror) или отложенный promotion через cron job.

### Одновременный promotion двух веток

Если два разработчика продвигают разные артефакты одновременно, возможна гонка approval'ов. Ограничьте параллельные promotions через mutex-скрипт или очередь в GitLab (`resource_group: production`).

### Approval истек при долгом тестировании

Если staging approval длится неделю, prod-артефакт устаревает. Ограничьте TTL approval'ов 24 часами; после истечения требуется повторное promotion с новым digest.

### Память и CPU на Runner

Большие образы (>2 GB) при `docker:24-dind` требуют >4 GB RAM на Runner. Настройте `privileged: true` для dind и убедитесь, что Runner имеет достаточные ресурсы.

### Multi-project cross-promotion

При promotion между проектами используйте Project Access Tokens с минимальными правами (`read_registry`, `write_registry`). Избегайте Personal Access Tokens в CI.

### Helm values drift

Dev/staging/prod могут иметь разные values.yaml. Централизуйте values через Git (monorepo) и используйте `--values` для каждой среды. Валидируйте через `helm lint` и JSON Schema.

### Откат при сломанных миграциях БД

Если promotion включает миграции БД, храните separate database backup перед каждым promotion. Откат = restore backup + previous digest, а не просто `helm rollback`.

## Дополнительная информация

### Связанные файлы

- **[Окружения и развертывания в GitLab CI](../Concepts/environments_and_deployments.md)** — deployment tier'ы, approval policies
- **[SBOM и подпись артефактов](../Advanced/sbom_and_artifact_signing.md)** — Cosign, Sigstore, SLSA
- **[Strategies: parent-child пайплайны](../Advanced/Downstream_Pipelines/strategies.md)** — стратегии downstream пайплайнов
- **[Artifact Promotion](../../../CI-CD/Deployment_Strategies/artifact_promotion.md)** — общее руководство по промоушену

### Внешние ресурсы

- [GitLab: Environment Promotion](https://docs.gitlab.com/ee/ci/environments/environment_scope.html)
- [GitLab: Deployment Approval Policy](https://docs.gitlab.com/ee/ci/environments/deployment_approval_policies.html)
- [OCI Image Specification](https://github.com/opencontainers/image-spec)
