# Продвижение артефактов между средами (Artifact Promotion)

> **Актуально для:** GitLab CI 17.x, Kubernetes 1.37.x, on-prem/self-hosted инфраструктура

## Определения

**Artifact Promotion** — процесс переноса проверенного артефакта (образа, бинарника, манифеста) из одной среды в другую (dev → staging → production) без повторной сборки, обеспечивающий консистентность и трассируемость развёртывания.

**Build Once, Deploy Many** — принцип, при котором артефакт собирается один раз и продвигается между средами по мере прохождения проверок. Критичен для воспроизводимости и supply chain security.

**Digest** — криптографический хэш (SHA256) содержимого артефакта, уникальный идентификатор, который не меняется при переносе между реестрами. Используется вместо тегов для Promotion.

**Promotion Gate** — этап пайплайна, проверяющий, что артефакт прошёл все необходимые проверки в текущей среде перед продвижением в следующую.

## Основные концепции

### Стратегии продвижения

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Tag Promotion** | Перенос тега между реестрами (dev:1.0 → prod:1.0) | Простые инфраструктуры, небольшой объём |
| **Digest Promotion** | Перенос по SHA256-дайджесту без перепаковки | Production, compliance-требования |
| **Helm Chart Promotion** | Обновление values.yaml с новым digest образа | GitOps-среды, ArgoCD/Flux |
| **Manifest Promotion** | Продвижение полностью сформированных Kubernetes-манифестов | Multi-cluster, сложные окружения |
| **GitLab Environment Promotion** | Использование `environment:name` и ручных approval gates | In-built GitLab, стандартные deployment tier'ы |

### Требования к продвигаемым артефактам

1. **Иммутабельность:** Артефакт с данным digest'ом не перезаписывается. В реестре только запись на чтение.
2. **Проверяемость:** Подпись (cosign, Sigstore) и SBOM должны следовать за артефактом.
3. **Трассируемость:** Каждый promotion должен быть привязан к ID пайплайна, коммиту и approval'у.
4. **Сканирование:** Перед promotion в prod артефакт должен пройти SAST/DAST, dependency scan, vulnerability check.

## Практические сценарии

### 1. Promotion по digest через GitLab CI (Kubernetes)

```yaml
stages:
  - build
  - test_dev
  - promote_staging
  - test_staging
  - promote_prod
  - deploy_prod

build_image:
  stage: build
  image: docker:29.8
  services:
    - docker:29.8-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
    # Сохраняем digest для promotion
    - docker inspect --format='{{index .RepoDigests 0}}' $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA > image_digest.txt
  artifacts:
    paths:
      - image_digest.txt
    expire_in: 30d
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy_dev:
  stage: test_dev
  image: bitnami/kubectl:1.37
  needs:
    - build_image
  script:
    - IMAGE=$(cat image_digest.txt | cut -d@ -f2)
    - kubectl set image deployment/my-app app=$CI_REGISTRY_IMAGE@$IMAGE -n dev
    - kubectl rollout status deployment/my-app -n dev --timeout=300s
  environment:
    name: dev
    url: https://dev.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

promote_staging:
  stage: promote_staging
  image: docker:29.8
  needs:
    - deploy_dev
  script:
    - IMAGE=$(cat image_digest.txt | cut -d@ -f2)
    # Продвигаем тот же digest в staging-реестр
    - docker pull $CI_REGISTRY_IMAGE@$IMAGE
    - docker tag $CI_REGISTRY_IMAGE@$IMAGE $CI_REGISTRY_STAGING/my-app:$CI_COMMIT_SHORT_SHA
    - docker push $CI_REGISTRY_STAGING/my-app:$CI_COMMIT_SHORT_SHA
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false

deploy_staging:
  stage: test_staging
  image: bitnami/kubectl:1.37
  needs:
    - promote_staging
  script:
    - kubectl set image deployment/my-app app=$CI_REGISTRY_STAGING/my-app:$CI_COMMIT_SHORT_SHA -n staging
    - kubectl rollout status deployment/my-app -n staging --timeout=300s
  environment:
    name: staging
    url: https://staging.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

promote_prod:
  stage: promote_prod
  image: docker:29.8
  needs:
    - deploy_staging
  script:
    - IMAGE=$(cat image_digest.txt | cut -d@ -f2)
    - docker pull $CI_REGISTRY_IMAGE@$IMAGE
    - docker tag $CI_REGISTRY_IMAGE@$IMAGE $CI_REGISTRY_PROD/my-app:$CI_COMMIT_SHORT_SHA
    - docker push $CI_REGISTRY_PROD/my-app:$CI_COMMIT_SHORT_SHA
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false

deploy_prod:
  stage: deploy_prod
  image: bitnami/kubectl:1.37
  needs:
    - promote_prod
  script:
    - kubectl set image deployment/my-app app=$CI_REGISTRY_PROD/my-app:$CI_COMMIT_SHORT_SHA -n production
    - kubectl rollout status deployment/my-app -n production --timeout=300s
  environment:
    name: production
    url: https://app.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

### 2. Promotion через GitLab API (скрипт promotion)

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

### 3. Helm Chart Promotion

```yaml
stages:
  - package
  - promote_staging
  - deploy_staging
  - promote_prod
  - deploy_prod

package_chart:
  stage: package
  image: alpine/helm:3.22
  script:
    - helm package mychart/ --destination ./
    - helm lint ./mychart-*.tgz
  artifacts:
    paths:
      - mychart-*.tgz
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

promote_chart_staging:
  stage: promote_staging
  image: alpine/helm:3.22
  needs:
    - package_chart
  script:
    - helm upgrade --install myapp ./mychart-*.tgz \
        --namespace staging \
        --values values-staging.yaml \
        --set image.tag=$CI_COMMIT_SHORT_SHA \
        --wait --timeout 5m
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual

promote_chart_prod:
  stage: promote_prod
  image: alpine/helm:3.22
  needs:
    - promote_chart_staging
  script:
    - helm upgrade --install myapp ./mychart-*.tgz \
        --namespace production \
        --values values-production.yaml \
        --set image.tag=$CI_COMMIT_SHORT_SHA \
        --wait --timeout 10m
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

### 4. GitLab Environment Promotion с approval rules

```yaml
deploy_staging:
  stage: deploy_staging
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/
    - kubectl rollout status deployment/my-app -n staging
  environment:
    name: staging
    url: https://staging.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

promote_to_production:
  stage: promote_prod
  image: bitnami/kubectl:1.37
  needs:
    - deploy_staging
  script:
    - kubectl apply -f k8s/
    - kubectl rollout status deployment/my-app -n production
  environment:
    name: production
    url: https://app.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

**Настройка approval policy в GitLab:**
1. `Settings > CI/CD > Deployment approval policy`
2. Выберите окружения: `production`
3. Укажите approval rules (например, минимум 2 approve от SRE)

### 5. Promotion с проверкой сканирования уязвимостей

```yaml
stages:
  - build
  - scan
  - promote_staging
  - deploy_staging
  - promote_prod

build:
  stage: build
  image: docker:29.8
  services:
    - docker:29.8-dind
  script:
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
```

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

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Promotion завис на manual gate** | Нет ответственного за approve или уведомление не дошло | Назначьте конкретного approver, настройте reminder за 24 часа до истечения TTL |
| **Артефакт не найден в prod-реестре** | Digest не был pushed или registry permissions некорректны | Проверьте `docker push` в логах promote-задачи; убедитесь, что CI-сервисный аккаунт имеет права push в prod-реестр |
| **Helm upgrade падает с timeout** | Релиз не успевает прогреться (большой StatefulSet, медленный Init Container) | Увеличьте `--timeout`; проверьте `helm history` и `kubectl get pods` для определения причины |
| **SBOM не прикрепился к артефакту** | Syft не сработал или путь к артефакту указан неверно | Проверьте, что `syft` запускается после сборки и до push; артефакт сохраняется в `artifacts:paths` |
| **Подпись cosign не прошла проверку** | Ключ/ключ-папка (keyless) не настроен в CI runner | Проверьте переменные окружения `COSIGN_EXPERIMENTAL=1` и наличие workload identity/Vault secret |
| **Scan нашел критичную уязвимость** | Образ содержит уязвимый слой или зависимость | Исправьте уязвимость в исходном коде и пересоберите артефакт; promotion текущего digest заблокирован |
| **Staging approval истек** | Approval был запрошен неделю назад, артефакт устарел | Ограничьте TTL approval'а 24 часами; после истечения требуется повторное promotion с новым digest |
| **Откат по digest не работает** | Deployment использует tag вместо digest, или digest изменился | Используйте immutable imagePullPolicy и конкретный digest в манифесте; не смешивайте tag и digest |
| **Multi-cluster promotion частичный** | Один из кластеров недоступен или манифест несовместим | Используйте последовательное применение с проверкой статуса каждого кластера; откатывайте при первом провале |
| **Helm values drift между средами** | В staging и prod использовались разные values-файлы вручную | Централизуйте values через Git (monorepo) и используйте `--values` для каждой среды |

## Лучшие практики

1. **Build Once, Deploy Many:** Собирайте артефакт один раз, продвигайте по digest'у между средами. Никакой rebuild для staging/prod.
2. **Иммутабельность:** Запретите тег `:latest` и перезапись артефактов. Используйте digest + immutable tags.
3. **Сканирование на каждом promotion:** SAST, DAST, dependency scan, container image scan — перед каждым продвижением.
4. **Approval Gates для production:** Ручное approval от SRE/compliance перед деплоем в prod.
5. **Артефакты пайплайна:** Сохраняйте digest, SBOM, подпись в артефактах с `expire_in: 30d`.
6. **Audit Trail:** Каждый promotion должен создавать событие в логах (кто, когда, какой артефакт, в какую среду).
7. **Раздельные реестры:** Используйте разные реестры для dev/staging/prod с разными правами доступа.
8. **Rollback по digest'у:** Откат = применение предыдущего digest'а, а не нового собранного артефакта.

## Граничные случаи и ограничения

- **Promotion упал на половине окружений:** Нет встроенного механизма отката promotion. Решение — скрипт, который проверяет статус окружений и откатывает при необходимости.
- **Нет взаимной блокировки:** Если staging approval длится неделю, prod-артефакт устаревает. Ограничьте TTL approval'ов (например, 24 часа).
- **Registry permissions:** У CI-сервисного аккаунта должны быть права push в staging/prod реестры, но не в dev.
- **Multi-cluster promotion:** Продвижение в несколько кластеров требует последовательного или параллельного применения манифестов с проверкой статуса каждого.
- **Helm values различия:** Dev/staging/prod могут иметь разные values.yaml. Используйте `--values` вместо хранения отдельных chart-версий.
- **Air-gapped среды:** В изолированных сетях promotion невозможен через стандартный registry. Решение — внутренний registry (Harbor, Nexus) с репликой или физическая доставка артефакта (sneakernet).
- **Одновременный promotion двух веток:** Если два разработчика продвигают разные артефакты одновременно, возможна гонка approval'ов. Ограничьте параллельные promotions через mutex-скрипт или очередь в GitLab.
- **Ошибки в values без санитизации:** Helm `--set` с пользовательским вводом может привести к injection. Валидируйте values через JSON Schema или `helm lint` в CI.
- **Retention артефактов:** Без политики хранения реестр разрастется. Настройте автоматическое удаление артефактов старше N дней, исключая теги, связанные с активными релизами.
- **Log shipping и audit trail:** Логи promotion должны уходить в центральный SIEM (Elastic, VictoriaMetrics) с привязкой к `CI_PIPELINE_ID`, коммиту и approval-юзеру. Без этого невозможно расследовать инцидент.
- **Resource Quota в Namespace:** При promotion Helm/chart может превысить квоту CPU/RAM в staging/prod. Проверяйте квоты перед деплоем через `kubectl describe quota -n <env>`.
- **Накопление неиспользуемыхHelm-релизов:** `helm list --all-namespaces` показывает failed/pending релизы. Настройте `--history-max` или периодический `helm uninstall` для очистки.
- **Сеть между CI и кластером:** CI-runner должен иметь сетевой доступ до Kubernetes API и registry. При VPN/файрволе используйте статические IP-раннеры или proxy.
- **Immutable артефакты в S3/NFS:** Если артефакты хранятся в S3, включите Object Lock; в NFS — `chattr +i` для предотвращения перезаписи.
- **Promotion при деградации registry:** Если registry недоступен, promotion блокируется. Настройте fallback на локальный registry-кэш (Docker Registry Mirror) или отложенный promotion.

## Дополнительная информация

### Рекомендованные ссылки

- **[Управление артефактами](../artifact_management.md)** — жизненный цикл артефактов, immutability, SBOM.
- **[Окружения и деплой в GitLab CI](../GitLab_CI/Concepts/environments_and_deployments.md)** — deployment tier'ы, approval policies, review apps.
- **[DORA-метрики](../Core_Concepts/dora_metrics.md)** — измерение Deployment Frequency и Lead Time.
- **[Проверки здоровья и откат](./deployment_health_checks_and_rollback.md)** — автоматизация отката между средами.
- **[Helm charts](../../Kubernetes/ToolsUtilities/Helm/helm_overview.md)** — управление чартами и values.
