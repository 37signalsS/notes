# Kargo: promotion-пайплайны продвижения артефактов

> **Актуальность (2026):** Kargo (линейка v1.11) — CNCF-проект, формализующий продвижение артефактов между окружениями в GitOps. Нативно интегрирован с Argo CD; используется как недостающее звено «CD для CD», когда промоушен dev → staging → prod перестает умещаться в скрипты CI.

В GitOps-стеке всегда есть слабое место: само продвижение версии из среды в среду. Его делают `yq`-скриптами в CI, ручными PR или кластерными автоматизаторами — и везде теряется либо аудит, либо гарантия того, что в прод уехал **тот же самый** артефакт, что проверялся в staging. Kargo закрывает именно это.

## Предварительные требования

| Компонент | Требование |
| :--- | :--- |
| Kargo | v1.11.x: контроллер + API-сервер + UI (установка через Helm-чарт) |
| GitOps-агент | Argo CD v3.x — нативный шаг `argocd-update`; для Flux — шаги записи в Git |
| OCI-реестр | Harbor/GHCR с digest-доступом; образы и чарты с фиксированными версиями |
| Argo Rollouts (опционально) | AnalysisTemplate переиспользуются как verification в стадиях |

## Определения

- **Warehouse**: Ресурс-«склад»: следит за источниками артефактов (реестры образов, репозитории чартов, Git) и фиксирует каждую новую совместимую комбинацию.
- **Freight**: Зафиксированный набор артефактов: digest образа + версия чарта + коммит Git + подписи. Неизменяем; идентифицируется алиасом (`app-abc1234`). Именно Freight, а не «тег», продвигается между средами.
- **Stage**: Окружение (dev/staging/prod) как ресурс Kargo: ссылается на Warehouse/вышестоящий Stage и на Argo CD Application(s). Статус Stage = текущий продвинутый Freight + результат верификации.
- **Promotion**: Запись о перемещении конкретного Freight на Stage; выполняет control flow из шагов (запись в Git, обновление Argo CD и т.д.) и проходит verification перед завершением.
- **Verification**: Автоматические проверки после применения Freight на стадии: Jobs, повторное использование AnalysisTemplate (Rollouts), произвольные механизмы.
- **Auto-promotion vs approval**: Stage может автоматически забирать новый Freight из upstream либо требовать явного аппрува человека (`requestedFreight`).

## Базовые концепции

### Какую проблему решает

Типовой самодельный промоушен — CI-job, который после успеха staging правит тег в overlay прода. Проблемы такого подхода:

| Самодельный скрипт | Kargo |
| :--- | :--- |
| Продвигается «тег» — содержимое могло измениться после staging | Продвигается digest: побайтово тот же артефакт |
| Гейты размазаны по скриптам, аудит — в логах CI | Каждое перемещение — ресурс Promotion с историей и верификацией |
| Нет понятия «комбинация версий» (образ+чарт+конфиг) | Freight связывает все компоненты одной неизменяемой записью |
| Отклонение от регламента не видно | UI/API показывают, какой Freight где находится и почему застрял |

### Модель ресурсов

```text
Warehouse (реестр образов + репозиторий чартов)
    │  новая совместимая комбинация
    ▼
Freight app-abc1234 ─────────────────────────────────┐
    │ autoPromotion                                  │ approval (человек)
    ▼                                                ▼
Stage dev ──(verification)──► Stage staging ────────► Stage prod
   argocd-update              argocd-update            argocd-update
```

Каждый Stage ссылается на Argo CD Applications своей среды. Перемещение Freight = обновление источника этих приложений (через коммит в Git-оверлей или нативный API-апдейт) + ожидание верификации.

### Верификация и гейты

1. **Автоматическая**: Stage описывает verification (Jobs или AnalysisRun): smoke-test, проверка метрик после раскатки. Провал верификации помечает Promotion failed — Freight не двинется дальше.
2. **Человеческая**: `approvalPolicy` стадии требует явного подтверждения Freight (CLI/UI/K8s API). Типовая схема: dev и staging — auto, prod — approval + авто-верификация после.
3. **RBAC**: роли Kargo на уровне Project ограничивают, кто может аппрувить prod-stage и запускать promotion — интеграция с SSO-группами платформы.

### Связь с Rendered Manifests и другими инструментами

Kargo — оркестратор паттерна [Rendered Manifests](../GitOps_overview.md): гидратация манифестов может быть одним из шагов промоушена. В отличие от Image Updater/Flux Image Automation (обновить версию), Kargo управляет **путем** версии через цепочку сред — с гейтами, идемпотентностью и аудитом каждого шага.

## Практические сценарии

### Сценарий 1: Минимальная цепочка dev → staging → prod с аппрувом прода

```yaml
apiVersion: kargo.io/v1alpha1
kind: Warehouse
metadata:
  name: billing-api
  namespace: kargo-demo
spec:
  interval: 5m
  freightCreationPolicy: Automatic
  substrates:                # источники артефактов
    - container:
        repoURL: harbor.internal/billing/api
        imageSelection:
          strategy: SemVer
          constraint: ^1.0   # только стабильные мажор-минор линейки
---
apiVersion: kargo.io/v1alpha1
kind: Stage
metadata:
  name: dev
  namespace: kargo-demo
spec:
  requestedFreight:
    - origin: {name: billing-api}
      sources: {direct: true}          # брать прямо из Warehouse
  promotionMechanisms:
    argoCDAppUpdates:
      - appName: billing-dev           # Argo CD Application этой среды
  automation:
    autoPromotion: {enabled: true}     # новый Freight применяется сразу
---
apiVersion: kargo.io/v1alpha1
kind: Stage
metadata:
  name: prod
  namespace: kargo-demo
spec:
  requestedFreight:
    - origin: {name: billing-api}
      sources:
        stages: [staging]              # только то, что прошло staging
      approvalPolicy: {requiredManually: true}   # нужен явный аппрув
  promotionMechanisms:
    argoCDAppUpdates:
      - appName: billing-prod
  automation:
    autoPromotion: {enabled: false}
```

Операции:

```bash
kargo get warehouses -n kargo-demo
# → NAME         FREIGHTS
# → billing-api  app-abc1234, app-def5678

kargo get stages -n kargo-demo
# → NAME   CURRENT FREIGHT   HEALTHY   PHASE
# → dev    app-def5678       True      Ready
# → prod   app-abc1234       True      Ready

# Аппрув конкретного Freight для прода (после разбора метрик staging)
kargo approve freight --project kargo-demo \
  --stage prod --freight app-def5678
# → freight app-def5678 approved for stage prod

# Запуск промоушена вручную (или он стартует сам после approval)
kargo promote --project kargo-demo --stage prod --freight app-def5678
# → Promotion/prod-app-def5678 created
```

### Сценарий 2: Verification между стадиями

После применения Freight на staging стадия прогоняет проверки; прод станет доступен только если они прошли:

```yaml
apiVersion: kargo.io/v1alpha1
kind: Stage
metadata:
  name: staging
  namespace: kargo-demo
spec:
  requestedFreight:
    - origin: {name: billing-api}
      sources: {stages: [dev]}
  promotionMechanisms:
    argoCDAppUpdates:
      - appName: billing-staging
  verification:
    analysisTemplates:
      - name: success-rate-check        # тот же шаблон, что для canary (Argo Rollouts)
        args:
          - {name: service-name, value: billing-staging}
    # либо произвольные Jobs:
    # jobs:
    #   - name: smoke-tests
    #     spec: <Job manifest с curl/e2e>
```

Провал анализа (например, success rate < 99%) оставляет Promotion в статусе Failed — Freight числится «застрявшим» на staging, до прода он не дойдет физически, а не «по договоренности».

### Сценарий 3: Продвижение коммитом в Git (write-back в оверлеи)

Если GitOps-репозиторий — единственный разрешенный канал изменений (аудит через PR-историю), промоушен выполняется шагами записи в Git вместо прямого API-апдейта Argo CD:

```yaml
spec:
  promotionMechanisms:
    gitRepoUpdates:
      - repoURL: https://gitlab.internal/platform/fleet-infra.git
        writeBranch: main
        kustomize:
          images:
            - image: harbor.internal/billing/api
              # digest подставляется из самого Freight
    argoCDAppUpdates:
      - appName: billing-prod   # после пуша Argo CD синкает сам
```

Результат виден в истории инфраструктурного репозитория: коммиты вида `kargo: promote app-def5678 to prod` дают трассируемость PR → digest → Promotion → синхронизация ([трехуровневая модель прослеживаемости](./audit_logs.md)).

### Сценарий 4: Границы ответственности с остальным стеком

| Задача | Инструмент |
| :--- | :--- |
| Обновить версию в dev быстро и без церемоний | Image Updater / Flux Image Automation |
| Довести проверенный Freight до прода с гейтами | **Kargo** |
| Раскатать один Freight на флот кластеров внутри среды | ApplicationSet RollingSync / fleet-паттерны |
| Постепенный перевод трафика внутри одного кластера | Argo Rollouts / Flagger |

Эти уровни ортогональны и в зрелом стеке работают одновременно: Kargo двигает Freight по средам, RollingSync — по кластерам, canary — по трафику.

## Типовые проблемы и их решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Warehouse не создает Freight | Подписи источников не совпадают (образ есть, чарт нет); constraint отсекает теги | Проверить статус Warehouse и условия селекции; логи контроллера |
| Stage висит в Verifying бесконечно | Verification Job падает и перезапускается / AnalysisTemplate ссылается на пустые метрики | Логи Job'ов стадии; проверить PromQL руками; задать таймауты |
| `argocd-update` не может изменить приложение | Приложение вне namespace проекта Kargo / RBAC Argo CD запрещает | Настроить права плагина/агента Kargo на проект Argo CD; проверить project приложения |
| Аппрув сделали, промоушен не стартует | Approval выдан другому Freight (алиасы похожи) | `kargo get freight` — сверить алиас и digest перед approve |
| Удалили Stage — приложения Argo CD остались/исчезли неожиданно | Понимание каскада ресурсов | Stage ≠ Application: удаление Stage не удаляет приложение, но ломает цепочку промоушена; восстанавливать Stage декларативно из Git |
| Все Freight требуют ручного аппрува даже на dev | Скопирован `approvalPolicy` из prod-примера | Явно разделить профили стадий: dev — direct+auto, prod — upstream+approval |

## Дополнительная информация

- **Безопасность Freight**: подпись и provenance артефактов проверяются на границах — политики Kyverno/Gatekeeper блокируют неподписанные образы при синхронизации, а Freight гарантирует, что проверенная комбинация не пересоберется. Полная схема — в [жизненном цикле образов](./containerization_and_image_storage.md).
- **Метрики процесса**: история Promotion'ов (сколько застряло, среднее время stage→stage) — готовые данные для lead time в [DORA-метриках](./dora_metrics_gitops.md).

### См. также

- [Жизненный цикл образов и хранение](./containerization_and_image_storage.md) — краткая версия Kargo-сценария, digest pinning, зеркала.
- [Обзор методологии: стратегии продвижения](../GitOps_overview.md) — место Kargo среди branch/repo/overlay-стратегий.
- [Прогрессивная доставка](./progressive_delivery_gitops.md) — уровень трафика, дополняющий промоушен сред.
- [Мульти-кластерные паттерны](./multi_cluster_patterns.md) — fleet-раскатка поверх промоушена.
