# GitOps: Образы контейнеров и их жизненный цикл

В GitOps образ контейнера является ключевым артефактом, который связывает процессы непрерывной интеграции (CI) и непрерывной доставки (CD). Правильное управление образами — основа предсказуемости, прослеживаемости и безопасности всей системы: именно digest образа становится той единственной переменной, которой достаточно для описания состояния приложения в кластере.

## Определения

- **Образ контейнера (Container Image)**: Неизменяемый (immutable) бинарный пакет, включающий приложение и его зависимости. В GitOps-конвейере образ является «грузом» (payload), который доставляется в кластер на основе изменений в Git.
- **Тег (Tag)**: Человекочитаемая метка (`v1.2.3`, `latest`), указывающая на конкретный манифест образа. В отличие от digest тег может быть перезаписан, поэтому в GitOps он рассматривается как указатель, а не идентификатор.
- **OCI (Open Container Initiative) Артефакты**: Стандарт упаковки, позволяющий хранить в реестрах не только образы, но и Helm-чарты, манифесты, SBOM и подписи.
- **OCI 1.1 Referrers API**: Механизм, позволяющий связывать дополнительные артефакты (подписи, результаты сканирования) с основным образом через граф зависимостей без изменения digest образа. Для реестров без поддержки API используется резервная схема тегов (tag-based fallback).
- **Реестр образов (Image Registry)**: Централизованное хранилище артефактов (например, Harbor, GitHub Container Registry, Amazon ECR). Современные реестры выполняют роль Unified Artifact Hub: единое хранилище образов, чартов и сопутствующих аттестаций.
- **Дайджест (Digest)**: Уникальный неизменяемый SHA256-хеш содержимого образа. Использование дайджестов (`image@sha256:...`) вместо тегов гарантирует побайтовую идентичность развернутого кода.
- **Мульти-архитектурный образ (Multi-arch Image)**: Группа образов для разных архитектур (amd64, arm64), объединенных под одним индексом манифестов (OCI Image Index / Docker Manifest List).
- **SBOM (Software Bill of Materials)**: Формализованный список всех компонентов и зависимостей внутри образа. Основные форматы — SPDX и CycloneDX.
- **Подпись (Signature)**: Криптографическое подтверждение происхождения образа, создаваемое инструментами Sigstore (Cosign) или Notation и хранимое рядом с образом в реестре.
- **Аттестация (Attestation)/Провенанс (Provenance)**: Подписанные метаданные о том, как был собран образ (окружение сборки, исходный коммит, параметры пайплайна) в формате SLSA Provenance.
- **SLSA (Supply-chain Levels for Software Artifacts)**: Фреймворк для обеспечения целостности цепочки поставок ПО: уровни зрелости от L0 до L4 описывают, насколько гарантировано происхождение артефакта.

## Базовые концепции

### Разделение ответственности CI и CD

GitOps устанавливает четкую границу между сборкой артефакта и его развертыванием:

- **CI (Build & Push)**: Пайплайн собирает код, создает мульти-архитектурный образ, генерирует SBOM, подписывает его и публикует в OCI-реестр. Результат CI — **новый неизменяемый артефакт**.
- **CD (Pull & Reconcile)**: GitOps-контроллер (Argo CD, Flux) обнаруживает новый образ или изменение тега в Git и синхронизирует состояние кластера. Результат CD — **обновленное состояние Runtime**.

Из этого разделения следует важное правило: CD никогда не пересобирает артефакт. Продвижение между средами — это всегда продвижение одного и того же digest, а не повторная сборка из того же коммита (сборка не детерминирована из-за временных меток и плавающих зависимостей базовых слоев).

### Жизненный цикл образа

```text
Code → Build (multi-arch) → Scan (Trivy/Grype) → SBOM (syft)
     → Sign (cosign) + Attest (provenance)
     → Push to Registry (digest фиксируется)
     → Promote (тот же digest: staging → production)
     → Deploy (GitOps-контроллер сверяет digest)
     → Runtime (kubelet проверяет digest при PullPolicy)
```

Каждая стрелка — отдельный этап с собственными гарантиями: сканирование блокирует уязвимые сборки до публикации, подпись доказывает, что образ собран доверенным пайплайном, а digest-pinning исключает подмену содержимого после проверки. Разрыв любого звена (например, подпись не прикреплена к образу) должен останавливать продвижение — это реализуется политиками Kyverno/Gatekeeper или проверками Kargo.

### OCI-центричный подход

Современный GitOps переходит от хранения всех манифестов в Git к гибридной модели:
1. **Реестр как единое хранилище артефактов**: Helm-чарты и Kustomize-пакеты хранятся в OCI-реестре рядом с образами.
2. **Referrers API**: Проверки безопасности (аттестации) прикрепляются к образу. GitOps-контроллер проверяет наличие валидной подписи перед деплоем, используя Referrers API реестра.
3. **Эффективность**: Пуллинг OCI-артефактов значительно быстрее клонирования тяжелых Git-репозиториев.

При этом Git остается источником декларативного желаемого состояния (какие версии где должны работать) — меняется лишь способ хранения самих пакетов: собранные чарты публикуются как OCI-артефакты, а в Git хранится код чартов и values.

### Слои и кэширование

Понимание слоистой структуры критично для скорости rollout'ов: kubelet скачивает только отсутствующие на узле слои. Практические следствия:
- **Базовый образ — общий для всех сервисов**: изменение общей базы распространяется одним слоем; частые полные пересборки «толстых» образов замедляют деплои во всем парке.
- **Порядок инструкций Dockerfile**: редко меняемое (зависимости) раньше часто меняемого (код приложения) — иначе кэш сборки бесполезен, а diff между версиями равен размеру всего приложения.
- **Минимизация**: Distroless/Alpine-базы и multi-stage сборка сокращают поверхность атаки и объем скачивания. Для sidecar-образов Argo CD это же требование актуально из-за автоскейлинга repo-server.

## Практические сценарии

### Сценарий 1: Мульти-архитектурные образы в GitOps

**Проблема**: В инфраструктуре используются узлы как на `amd64`, так и на `arm64` (например, Apple Silicon или AWS Graviton).

**Предварительные требования**: `docker buildx` (входит в Docker Desktop / плагин buildx), доступ к реестру с поддержкой OCI Image Index (Harbor v2, GHCR, ECR); для сборки под чужую архитектуру — эмулятор QEMU (`docker run --privileged --rm tonistiigi/binfx --install arm64,amd64`) или нативные раннеры.

**Действия**:
1. Соберите образ для нескольких платформ:
   ```bash
   docker buildx create --name multiarch --use   # одноразовый builder
   docker buildx build \
     --platform linux/amd64,linux/arm64 \
     -t registry.com/app:1.2.3 \
     --provenance=false \        # упрощенный манифест; включать при использовании attestation-манифестов
     --push .
   # → result: успешно собрано и запушено; в реестре создан OCI Image Index
   ```
2. Проверьте структуру индекса:
   ```bash
   docker buildx imagetools inspect registry.com/app:1.2.3
   # → result: Manifests: linux/amd64 sha256:..., linux/arm64 sha256:...
   ```
3. В Git-манифесте укажите тег `1.2.3`. Kubernetes при пуллинге автоматически выберет нужный слой на основе архитектуры узла, сохранив единое желаемое состояние в Git.

**Граничные случаи**: если какая-то архитектура не была собрана (например, сборка arm64 упала, а пайплайн продолжился), под на arm64-узле получит ошибку `exec format error` — проверяйте наличие всех платформ в индексе до продвижения.

**Инструменты сборки без демона**: классический [Kaniko](../../Docker/Dockerfile/dockerfile_kaniko.md) (сборка внутри K8s без privileged) был архивирован Google в июне 2025; актуальные варианты — поддерживаемый форк Chainguard (`chainguard-dev/kaniko`), community-образы `osscontainertools/kaniko`, либо BuildKit rootless/Buildah. Синтаксис вызова kaniko-исполнителя не изменился.

### Сценарий 2: Продвижение образов через Kargo

**Проблема**: Необходимо безопасно переносить изменения из `Staging` в `Production`, не пересобирая образ.

**Концепция**: **Kargo** (актуальная линейка v1.11) отслеживает появление новых артефактов в реестрах через ресурс `Warehouse`. Найденная комбинация артефактов фиксируется как `Freight` (версионный набор: digest образа + версия чарта + коммит Git). При успешном прохождении проверок в `Stage` `Staging` Kargo обновляет манифесты в Git для `Production` через promotion step `argocd-update`, используя тот же digest, который был проверен ранее. Это гарантирует, что в продакшене работает побайтово идентичный артефакт.

```yaml
apiVersion: kargo.akuity.io/v1alpha1
kind: Warehouse
metadata:
  name: app
spec:
  freightCreationPolicy: Automatic
  subscriptions:
    - image:
        repoURL: registry.com/app
        discoveryLimit: 5
        semverConstraint: ^1.2.0       # какие теги считать кандидатами
        # alias не задан явно → по умолчанию совпадает с именем репозитория;
        # доступ к тегу в шагах: ${{ images.registry.com/app.Tag }}
---
apiVersion: kargo.akuity.io/v1alpha1
kind: Stage
metadata:
  name: prod
spec:
  requestedFreight:
    - origin: {name: app, kind: Warehouse}
      sources: {directStages: [staging]}  # продвигаем только то, что прошло staging
  promotion:
    steps:
      - uses: argocd-update
        as: update-app
        config:
          apps:
            - name: app-prod
              sources:
                - repoURL: https://git.example.com/deploy.git
                  desiredRevision: main
                  helm:
                    images:
                      - key: image.tag    # какой параметр обновить в values
                        value: ${{ images.registry.com/app.Tag }}
                        # digest-pinning: Tag → Digest для фиксации по sha256
```

**Валидация**:
```bash
kubectl get warehouses,freights,stages -n kargo-demo
# → result: Warehouse/app FREIGHTS app-abc123... ; Stage/prod PHASE=Ready
kubectl get promotions -n kargo-demo -l kargo.akuity.io/stage=prod
# → result: история продвижений с указанием Freight и результата шагов
```

Альтернативы: собственный CI-job с `yq`/PR-ботом (проще, но без аудита и verification-гейтов) или Flux-подобная автоматизация (см. Сценарий 3). Kargo выгоден там, где сред три и больше и нужны формальные гейты (подпись, health checks, ручные approvals) — развернутая модель Warehouse/Freight/Stage и verification разобраны в [Kargo: promotion-пайплайны](./kargo_promotion_pipelines.md).

### Сценарий 3: Автоматизация обновления (Image Automation)

Автоматическая синхронизация тегов (и дайджестов) в Git при появлении новых версий в реестре.

- **Flux Image Automation** (API `image.toolkit.fluxcd.io/v1` — GA; линейки контроллеров v1.2.x):
  - `ImageRepository`: Сканирует реестр (с поддержкой облачных провайдеров аутентификации: `spec.provider: aws/azure/gcp`).
  - `ImagePolicy`: Определяет правила выбора версии (например, `semver: 1.x.x`); умеет резолвить digest выбранного тега.
  - `ImageUpdateAutomation`: Создает коммит в Git с обновленным тегом; поддерживает digest pinning — запись полного `image@sha256:` вместо тега.
  ```yaml
  apiVersion: image.toolkit.fluxcd.io/v1
  kind: ImageRepository
  metadata:
    name: app
    namespace: flux-system
  spec:
    image: registry.com/app
    interval: 5m
    exclusionList: ["^.*-rc$", "^.*-debug$"]   # игнорировать пререлизы
  ---
  apiVersion: image.toolkit.fluxcd.io/v1
  kind: ImagePolicy
  metadata:
    name: app
    namespace: flux-system
  spec:
    imageRepositoryRef: {name: app}
    policy:
      semver: {range: 1.x.x}
  ```
  ```bash
  flux reconcile image repository app -n flux-system
  # → result: annotation updated, scanned registry in 1.2s
  kubectl describe imagepolicy app -n flux-system | grep Latest
  # → result: Latest Image: registry.com/app:1.2.7
  ```

- **Argo CD Image Updater**: проект развивается в org `argoproj-labs`; с версии v1.0 конфигурация переехала с аннотаций на декларативный CRD `ImageUpdater` (аннотационный подход объявлен legacy и обслуживается ограниченно). Контроллер обновляет параметры приложений напрямую через API Argo CD (write-back в Git опционален). Рекомендуется для Dev/QA сред.
  ```yaml
  apiVersion: argocd-image-updater.argoproj.io/v1alpha1
  kind: ImageUpdater
  metadata:
    name: dev-apps            # CR ищет Applications в СВОЕМ namespace
    namespace: argocd
  spec:
    applicationRefs:
      - labelSelector: {matchLabels: {env: dev}}
        images:
          - alias: app
            imageName: registry.com/app
            delayTags: 10m              # дать время сканированию после пуша
            updateStrategy: semver
            commonUpdateSettings:
              writeBackConfig:
                method: git             # фиксировать изменение обратно в Git
                target: env/dev/values.yaml
                branch: main
  ```

**Выбор инструмента**: Flux-автоматизация — когда Git-коммиты обязательны и нужен digest pinning; Image Updater — когда достаточно быстрого обновления Dev-приложений без лишних коммитов; **Renovate** — когда нужен единый PR-бот для образов, Helm-чартов и прочих зависимостей с ревью и гейтами ([детально](./renovate_dependency_updates.md)); Kargo — когда нужна цепочка сред с гейтами (см. Сценарий 2).

### Сценарий 4: Зеркалирование в закрытых контурах (Air-gapped)

В изолированных сетях GitOps-контроллер не имеет доступа к публичным реестрам.

**Реализация**:
1. Используйте `skopeo` или встроенные функции **Harbor** для зеркалирования (Replication) образов из внешнего реестра во внутренний.
   ```bash
   # Ручное зеркало одного образа со всеми платформами и подписями
   skopeo copy --all \
     docker://docker.io/library/nginx:1.27 \
     docker://harbor.local/library/nginx:1.27
   # → result: copied blob sha256:... (по слоям; --all переносит весь индекс)
   ```
   В Harbor репликация настраивается правилом (Administration → Replication): endpoint-провайдер `docker-hub`/`acr`/`ecr`, триггер `scheduled` или `event-based`, фильтры по именам репозиториев и тегам. Для чартов используется тот же механизм (OCI-чарты реплицируются как артефакты).
2. В Git-манифестах используйте внутренние адреса, либо настройте `ImagePullSecrets` и зеркала на уровне рантайма. Для containerd 1.5+ конфигурация выполняется через `hosts.toml` без перезагрузки демона — детальное руководство: [Air-gapped ошибки Image Pull](../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md).
3. Проверяйте полноту зеркала до переключения прод-трафика:
   ```bash
   skopeo inspect --raw docker://harbor.local/library/nginx:1.27 | jq -r '.manifests[].platform.architecture'
   # → result: amd64 \n arm64   (все платформы присутствуют во внутреннем реестре)
   ```

**Граничные случаи**: rate limits Docker Hub ломают запланированные репликации — используйте аутентифицированный pull при зеркалировании; Referrers API не всегда поддерживается транзитными реестрами — проверяйте, что подписи переносятся (`skopeo copy --all` копирует связанные артефакты только в новых версиях; иначе повторная подпись после импорта).

### Сценарий 5: Полный конвейер CI: сборка, сканирование, SBOM, подпись

Минимальный production-grade пайплайн публикации образа (GitLab CI / GitHub Actions — шаги идентичны):

```bash
#!/usr/bin/env bash
set -euo pipefail
IMAGE="registry.com/app:${CI_COMMIT_SHORT_SHA}"

# 1. Сборка мульти-архитектурного образа
docker buildx build --platform linux/amd64,linux/arm64 -t "$IMAGE" --push .

# 2. Сканирование на уязвимости; блокируем Critical/High
trivy image --exit-code 1 --severity CRITICAL,HIGH "$IMAGE"
# → result: при наличии критических уязвимостей exit 1, пайплайн падает ДО подписи

# 3. Генерация SBOM и прикрепление как аттестации OCI 1.1
syft "$IMAGE" -o cyclonedx-json > sbom.cdx.json
cosign attest --predicate sbom.cdx.json --type cyclonedx "$IMAGE"

# 4. Подпись образа (keyless через OIDC пайплайна либо ключом из KMS/Vault)
cosign sign --yes "$IMAGE"

# 5. Генерация SLSA provenance (кто/где/из чего собран)
cosign attest --predicate provenance.json --type slsaprovenance "$IMAGE"
```

**Валидация связанности артефактов**:
```bash
cosign verify --certificate-identity-regexp '^https://gitlab\.com/org/.+$' \
  --certificate-oidc-issuer https://gitlab.com registry.com/app:abc1234
# → result: Verified OK   (подпись доверенного пайплайна)

cosign triangulate registry.com/app:abc1234 | xargs crane manifest | jq .
# → result: манифест referrers с типами application/vnd.cncf.cosign..., cyclonedx
```

Далее политики в кластере ([Kyverno/Gatekeeper](./gitops-policy-management.md)) блокируют деплой образов без валидной подписи, а [журналы аудита](./audit_logs.md) связывают digest с коммитом и одобрившим ревьюером.

### Сценарий 6: Ретенция и очистка реестра

Без политики очистки реестр неограниченно растет: динамические среды и PR-сборки генерируют сотни одноразовых тегов.

1. **Retention rules в Harbor** (Project → Retention): например, «хранить последние 10 semver-тегов на репозиторий, теги вида `sha-*` — 7 дней, `latest` — всегда». Правила применяются по cron-расписанию GC.
2. **Quota per project**: лимит хранилища + alerting при приближении к порогу — защита от остановки пайплайнов из-за переполнения.
3. **Иммунитет продовых digest**: правила ретенции должны исключать теги, на которые указывают production-манифесты. Digest pinning усугубляет риск: если GC удалит слой, на который ссылается закрепленный digest, деплой упадет с `manifest unknown`. Минимум за окно отката (например, 90 дней) старые digest обязаны жить.
4. **Очистка со стороны CI**: для ephemeral-окружений удаляйте образы вместе с окружением (API Harbor: `DELETE /projects/{p}/repositories/{r}/artifacts/{ref}`).

```bash
# Пример: удалить все PR-теги старше 7 дней через Harbor API v2
curl -s -u "$HARBOR_USER:$HARBOR_PASS" \
  "https://harbor.local/api/v2.0/projects/app/repositories/backend/artifacts?page_size=100" \
  | jq -r '.[] | select(.tags[]?.name | test("^pr-")) |
           select((.pull_time // .push_time) < (now - 604800 | todate)) | .digest' \
  | while read d; do
      curl -sf -X DELETE -u "$HARBOR_USER:$HARBOR_PASS" \
        "https://harbor.local/api/v2.0/projects/app/repositories/backend/artifacts/$d"
    done
# → result: HTTP 200 на каждый удаленный артефакт
```

## Типичные проблемы и их решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `ImagePullBackOff: manifest unknown` после отката | Тег был перезаписан или digest удален политикой ретенции | Переключить манифест на существующий digest; ввести правило ретенции с окном > периода отката (см. Сценарий 6) |
| `exec format error` при запуске пода | В индексе образа отсутствует платформа узла (например, собран только amd64, а узел arm64) | Собрать полный индекс (`--platform linux/amd64,linux/arm64`), проверить `buildx imagetools inspect` до продвижения |
| ArgoCD показывает OutOfSync сразу после деплоя по digest | Kustomize/Helm подменяет digest на тег либо image updater конфликтует с ручными правками | Зафиксировать digest в самом манифесте, исключить поле из ignoreDifferences-конфликтов, использовать один механизм автоматизации (Сценарий 3) |
| `toomanyrequests` от Docker Hub в пайплайнах | Анонимные rate limits реестра | Зеркалирование базовых образов во внутренний реестр + аутентифицированный pull (Сценарий 4) |
| Подпись не находится при `cosign verify`, хотя подписывали | Реестр не поддерживает Referrers API — артефакт лежит по tag-based схеме | Обновить cosign до актуальной версии (fallback включен), либо включить поддержку referrers в Harbor; проверить `cosign triangulate` |
| Деплой заблокирован политикой «нет подписи» после зеркалирования | Репликация перенесла образ без связанных аттестаций | Повторно подписать после импорта или настроить перенос referrers (`skopeo copy --all`, свежие версии) |
| Медленные rollout'ы больших образов | Слои не кэшируются на узлах: пересборка ломает слои зависимостей | Исправить порядок Dockerfile (зависимости раньше кода), общий slim/distroless base, pre-pull через DaemonSet для критичных узлов |

## Дополнительная информация

Для настройки безопасности и версионирования изучите следующие разделы:
- **[Версионирование и тегирование образов](../../Docker/Docker_registries/image_versioning_and_tagging.md)** — подробные стратегии SemVer и CalVer.
- **[Подписание и верификация образов](../../Docker/Docker_security/image_signature_and_verification.md)** — практическое руководство по Cosign.
- **[Управление артефактами в CI/CD](../../CI-CD/artifact_management.md)** — общие принципы жизненного цикла.

См. также:
- **[GitOps: Журналы аудита и трассируемость](./audit_logs.md)** — прослеживаемость образов.
- **[Обзор Argo CD](../ArgoCD/argocd_overview.md)** · **[Image Updater: детальное руководство](../ArgoCD/argocd_image_updater.md)** · **[Обзор Flux](../flux.md)**
- **[Обзор Harbor](../../Docker/Docker_registries/Harbor/overview.md)** — развертывание собственного реестра.

Внешние ресурсы:
- [Kargo: документация](https://docs.kargo.io/) — Warehouse/Freight/Stages и promotion steps.
- [Flux: Image Update guide](https://fluxcd.io/flux/guides/image-update/) — включая digest pinning.
- [Sigstore Cosign](https://docs.sigstore.dev/cosign/signing/overview/) — подписание и аттестации.
- [OCI Distribution Spec 1.1: Referrers](https://github.com/opencontainers/distribution-spec/blob/main/spec.md#listing-referrers) — API связанных артефактов.

## Вопросы для собеседования

### Почему в production пинуют digest, а не тег?
Тег — изменяемый указатель: его можно перезаписать (`docker push` тем же тегом), и «откат на v1.2.3» даст непредсказуемое содержимое. Digest — хеш манифеста образа: неизменяем, гарантирует побайтовую идентичность того, что сканировалось и подписывалось. Тег остается человекочитаемой меткой рядом с digest.

### Чем опасен плавающий тег `latest` в GitOps-манифесте?
Нарушает принцип версионируемости: ревизия не фиксируется — откат невозможен, аудит бессмыслен, узлы кластера могут работать с разными содержимыми одного «тега» после перезаписи в реестре.

### Как организовать доставку образов в air-gapped контур?
Зеркалирование во внутренний реестр (Harbor Replication или `skopeo copy --all` с переносом платформ и referrers/подписей), все ссылки в манифестах — только на внутренний реестр, digest сверяется при переносе. Проверять, что политики верификации подписей работают против зеркала.

### Где именно проверяется подпись Cosign и что она гарантирует?
На границах потребления: admission-политика Kyverno verifyImages/Gatekeeper блокирует поды без подписи доверенного identity, плюс проверка в CI перед промоушеном. Подпись привязана к digest и гарантирует автора сборки; целостность после подписания обеспечивает сам digest, а не подпись.

### Какой главный урок из заморозки каталога Bitnami?
Зависимость от чужого публичного реестра — архитектурный риск: политика вендора может сломать ваши пайплайны за один день. Ответственная практика — зеркалировать используемые образы и чарты в собственный реестр и обновлять их контролируемо, а не тянуть напрямую из внешних источников.
