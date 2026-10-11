# GitOps: пример пайплайна

## Определения

**GitOps-пайплайн** — это конвейер доставки программного обеспечения, реализующий декларативный подход к управлению состоянием системы. В этой модели система **CI (Continuous Integration — непрерывная интеграция)** отвечает за сборку и проверку артефактов, а система **CD (Continuous Delivery — непрерывная доставка)** обеспечивает соответствие фактического состояния кластера описанию в Git-репозитории.

- **Неизменяемый артефакт (Immutable Artifact)**: Образ или Helm-чарт, которые после публикации никогда не изменяются — новая версия кода всегда означает новый тег/digest. Основа прослеживаемости: один и тот же артефакт проходит все окружения без пересборки.
- **Продвижение (Promotion)**: Перенос проверенной версии артафакта из одного окружения в другое (Staging → Production) через изменение ссылки на его версию в GitOps-репозитории, а не через повторный деплой из CI.
- **GitOps-репозиторий (Config Repo)**: Репозиторий с декларативным описанием желаемого состояния кластера, который является единственной точкой входа для изменений состояния. Отличается от репозитория с исходным кодом (Source Repo).

## Предварительные требования

Для воспроизведения сценария необходимы:

| Компонент | Требование | Проверка |
| :--- | :--- | :--- |
| VCS + CI | GitHub-организация с правами на создание Actions workflows | Тестовый запуск `hello-world` workflow |
| Реестр | ghcr.io (входит в GitHub Packages) либо внутренний OCI-реестр (Harbor) | `docker login ghcr.io` |
| Кластер | Kubernetes 1.28+ с установленным Argo CD v3.x | `argocd version --short` |
| CLI | `helm` 3.14+/4.x, `cosign`, `trivy`, `gitleaks`, `argocd` CLI | `cosign version && trivy --version` |
| Доступы | Personal Access Token с правами `write:packages` для публикации образов и чартов | `echo $CR_PAT \| docker login ghcr.io -u USER --password-stdin` |

Исходное состояние: репозиторий приложения содержит `Dockerfile` и директорию `charts/app` с Helm-чартом; отдельный GitOps-репозиторий (или директория `deploy/`) описывает окружения; ArgoCD подключен к GitOps-репозиторию.

## Основные концепции

### Разделение зон ответственности

Пайплайн 2026 года строится на строгом разделении функций:

1.  **CI (Continuous Integration):** Проверка кода, запуск тестов, сканирование безопасности, сборка и подписание артефактов (Docker-образ и Helm-чарт). Результат — неизменяемый артефакт в реестре.
2.  **CD (Continuous Delivery):** Контроллер внутри кластера (агент) опрашивает источники и применяет изменения. CD-система не «знает» о процессе сборки, она оперирует только готовыми версиями.

Ключевое следствие разделения: CI не имеет прямого доступа к кластеру, а CD не имеет доступа к исходному коду. Контракт между ними — реестр артефактов (какая версия собрана) и GitOps-репозиторий (какая версия должна работать). Связующим звеном выступает коммит в GitOps-репозиторий, обновляющий ссылку на версию.

### Используемые инструменты и технологии

- **CI-платформа:** GitHub Actions (интеграция с VCS).
- **CD-агент:** ArgoCD v3.x (модель Pull).
- **Безопасность:** Trivy (сканирование), Cosign (подписание образов), Gitleaks (поиск секретов).
- **Доставка:** OCI-реестр (единое хранилище для образов и Helm-чартов).
- **Синхронизация:** Server-Side Apply (SSA) для минимизации конфликтов манифестов.
- **Автоматизация продвижения:** Argo CD Image Updater (v1.x, декларативный CRD `ImageUpdater`), Kargo (цепочки сред с гейтами).

Версии инструментов в примерах: actions/checkout@v4, Trivy 0.5x+, Cosign 2.x (keyless-подпись через OIDC), Argo CD v3.x (SSA — опция `ServerSideApply=true`, поддержка OCI-чартов — с v3.1+, Helm 4 — в актуальных релизах).

### Архитектура потока данных

```text
┌─────────────┐   PR/push    ┌──────────────────┐    образ+чарт     ┌───────────┐
│  Source Repo │ ──────────► │  GitHub Actions  │ ────────────────► │   GHCR    │
│  (код+чарт)  │             │  (CI: test/scan/ │                   │  (OCI)    │
└─────────────┘              │  build/sign)     │                   └─────┬─────┘
                             └────────┬─────────┘                         │ новый tag
                                      │ bump appVersion/tag               ▼
                                      ▼                            ┌─────────────┐
                             ┌──────────────────┐    poll/webhook   │ Image       │
                             │  GitOps Repo     │ ◄──────────────── │ Updater /   │
                             │  (desired state) │                   │ Kargo / PR  │
                             └────────┬─────────┘                   └─────────────┘
                                      │ reconcile (pull)
                                      ▼
                             ┌──────────────────┐
                             │  ArgoCD → K8s    │
                             │  prod namespace  │
                             └──────────────────┘
```

Направление стрелок принципиально: данные текут из Git в кластер (Pull), а не из CI в кластер (Push). Единственный путь изменить состояние кластера — изменить GitOps-репозиторий.

### Преимущества подхода

- **Безопасность:** CI-система не имеет доступа к API Kubernetes (не требует `kubeconfig`). Компрометация CI-раннера не дает прямого доступа к продакшену — злоумышленнику потребуется еще и доступ на коммит в защищенную ветку GitOps-репозитория.
- **Прослеживаемость:** Четкая связь между SHA коммита, тегом образа и состоянием ресурсов. История `git log` GitOps-репозитория = история деплоев.
- **Декларативность:** Описание всей инфраструктуры и приложений хранится в коде.
- **Воспроизводимость отката**: Откат = `git revert` коммита, после чего контроллер сам приводит кластер к прежнему состоянию.

#### Ограничения и компромиссы

- **Задержка доставки**: Pull-модель добавляет интервал опроса (типично 3 минуты по умолчанию). Сокращается webhook'ами от Git и уведомлениями от реестра, но остается фундаментальным свойством подхода.
- **Окно дрейфа**: Между изменением в Git и применением состояние кластера расходится с описанным. Для критичных исправлений (hotfix) это осознанный компромисс в обмен на стабильность.
- **Секреты не решаются «из коробки»**: Значения секретов нельзя хранить в открытом виде в Git — требуется шифрование (Sealed Secrets, SOPS) или внешний менеджер (см. [Шифрование секретов](./secrets_encryption.md)).
- **Начальная сложность**: Три репозитория (код, чарты, конфигурация окружений) вместо одного требуют дисциплины автоматизации связки между ними.

## Практические сценарии

### Поток выполнения (Workflow)

#### 1. Проверка в Feature-ветке

При каждом пуше в ветку разработки запускаются базовые проверки:
- Линтинг кода и YAML-манифестов.
- Unit-тестирование.
- Сканирование на секреты.

Конкретная реализация job'а проверок:

```yaml
# .github/workflows/pr-checks.yml — триггер: pull_request и push в feature-ветки
jobs:
  static-checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0 # полная история нужна gitleaks для сканирования всех коммитов PR
      - name: Lint manifests
        run: |
          yamllint charts/ deploy/
          helm lint charts/app
      - name: Detect secrets
        run: gitleaks detect --source . --redact --exit-code 1
        # → при обнаружении секрета: exit 1, пайплайн падает со списком находок
      - name: Unit tests
        run: make test # запуск тестов приложения (пример для Makefile-проекта)
```

Флаг `--redact` у Gitleaks обязателен: без него найденный секрет попадает в лог пайплайна и становится доступен всем, кто видит логи CI.

#### 2. Процесс сборки и публикации (CI-часть)

При слиянии в ветку `main` пайплайн выполняет следующие шаги:

```yaml
# Пример GitHub Actions для CI-части
permissions:
  contents: read
  packages: write # публикация образов и чартов в ghcr.io

env:
  IMAGE: ghcr.io/${{ github.repository }}

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build image
        run: docker build -t $IMAGE:${{ github.sha }} .

      - name: Scan with Trivy
        run: trivy image --severity CRITICAL --exit-code 1 $IMAGE:${{ github.sha }}
        # → при наличии Critical: exit 1, пайплайн падает ДО публикации

      - name: Push to OCI
        run: docker push $IMAGE:${{ github.sha }}

      - name: Sign image (keyless)
        run: cosign sign --yes $IMAGE:${{ github.sha }}
        # keyless-подпись: удостоверение выдается OIDC-токеном запуска Actions,
        # ключи не хранятся вовсе; верификация --certificate-identity-regexp

      - name: Update Helm Chart appVersion
        env:
          HELM_EXPERIMENTAL_OCI: "1"
        run: |
          sed -i 's/appVersion: .*/appVersion: "${{ github.sha }}"/' charts/app/Chart.yaml
          helm package charts/app
          helm registry login ghcr.io -u ${{ github.actor }} --password-stdin <<< "${{ secrets.GITHUB_TOKEN }}"
          helm push app-0.1.0.tgz oci://ghcr.io/org/charts
```

Принципиальные детали порядка шагов:

1.  **Сканирование до публикации**: Уязвимый образ не должен попасть в реестр вообще, чтобы его нельзя было случайно развернуть.
2.  **Подпись после публикации**: Cosign прикрепляет подпись к образу в реестре (через Referrers API OCI 1.1) — подписывать можно только уже запушенный образ. Попытка подписать локальный образ упадет с ошибкой доступа к манифесту.
3.  **Аутентификация обязательна для каждого клиента реестра**: и Docker, и Helm выполняют собственный `login` — общий слой авторизации между ними отсутствует.
4.  **Keyless вместо `--key cosign.key`**: Хранение приватного ключа подписи в секретах CI — риск и операционная нагрузка (ротация, бэкапы). Keyless-подпись привязывает образ к identity пайплайна (`https://github.com/org/app/.github/workflows/ci.yml@refs/heads/main`), что жестче для верификации политиками.

Глубокое покрытие жизненного цикла артефактов (мультиархитектурные сборки, SBOM через syft, SLSA provenance, digest-pinning, ретенция реестра) вынесено в отдельный документ: **[Жизненный цикл образов](./Concepts/containerization_and_image_storage.md)**.

#### 3. Развертывание и сверка (CD-часть)

ArgoCD отслеживает изменения и применяет их.

```yaml
# Пример манифеста ArgoCD Application
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: production-app
  namespace: argocd
spec:
  project: default
  source:
    chart: app
    repoURL: ghcr.io/org/charts # OCI-реестр как источник чарта (нативно с Argo CD v3.1+)
    targetRevision: 0.1.0 # версия чарта; именно это поле обновляется при promotion
    helm:
      valueFiles:
        - values-prod.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: prod
  syncPolicy:
    automated:
      prune: true # удалять ресурсы, исчезнувшие из Git
      selfHeal: true # возвращать ручные изменения кластера к состоянию Git
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true # включает SSA для синхронизации (в Argo CD по умолчанию client-side apply)
```

Назначение ключевых полей:

| Поле | Назначение | Риск при ошибке |
| :--- | :--- | :--- |
| `targetRevision` | Закрепленная версия чарта; единственная точка promotion | Забытый bump — старая версия работает дальше |
| `automated.prune` | Удаление объектов, убранных из Git | Ошибочный коммит удалит ресурсы из кластера |
| `selfHeal` | Борьба с ручными изменениями (`kubectl edit` в обход Git) | Ломает легитимные внешние контроллеры (HPA меняет replicas) — такие поля исключают через `ignoreDifferences` |
| `ServerSideApply` | Разрешение конфликтов полей на стороне API-сервера | Без SSA крупные манифесты (>256KB аннотации last-applied) не применятся |

Механика обнаружения изменений: ArgoCD опрашивает источник каждые 3 минуты (поле `timeout.reconciliation` в `argocd-cm`) либо реагирует мгновенно на вебхук от Git-хостинга. Для OCI-источников чартов опрос реестра встроен нативно (v3.1+); ускорить реакцию на новые чарты можно вебхуком реестра (Harbor) на endpoint ArgoCD `/api/webhook`.

**Алгоритм работы CD:**
1.  **Обнаружение:** ArgoCD получает вебхук или опрашивает OCI-реестр/Git.
2.  **Сравнение:** Вычисляется разница (`diff`) между текущим состоянием кластера и новым Helm-чартом.
3.  **Применение:** Если включена автосинхронизация, изменения применяются в кластер.
4.  **Проверка:** Ожидание успешного прохождения проб (Liveness/Readiness probes).
5.  **Тестирование:** Запуск E2E-тестов в окружении Staging перед продвижением в Production.

Детали синхронизации (стратегии, хуки, wave-порядок, разрешение конфликтов) — в специализированном руководстве: [Синхронизация в ArgoCD](./ArgoCD/synchronization.md).

#### Проверка работоспособности

```bash
# 1. Статус приложения после коммита в GitOps-репозиторий
argocd app get production-app --refresh
# → Name:               production-app
# → Status:             Synced          ← состояние Git == кластер
# → Health:             Healthy         ← пробы пройдены
# → Sync Policy:        Automated (Prune)

# 2. Фактическая версия в кластере соответствует SHA коммита
kubectl get deployment production-app -n prod \
  -o jsonpath='{.spec.template.spec.containers[0].image}'; echo
# → ghcr.io/org/app@sha256:a1b2c3... (или :<git-sha>)

# 3. Подпись образа валидна (проверка с машины инженера или из политики кластера)
cosign verify ghcr.io/org/app:<sha> \
  --certificate-identity-regexp '^https://github\.com/org/app/.+$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
# → Verified OK

# 4. История событий синхронизации
argocd app history production-app
# → ID  REVISION                    ...
# → 3   0.1.0 (abc123def456...)    ← последняя успешная синхронизация
```

#### Откат развертывания (Rollback)

Откат в GitOps-парадигме — это операция над Git, а не над кластером:

```bash
# Правильный способ: revert коммита, изменившего targetRevision/образ
git revert <commit-sha>   # в GitOps-репозитории
git push
# → ArgoCD обнаружит возврат версии и сам вернет прежнее состояние

# Просмотр того, что будет откачено, до применения:
argocd app diff production-app --revision <previous-revision>
```

**Критичный нюанс**: команда `argocd app rollback` при включенной автосинхронизации бесполезна — следующий цикл реконсиляции увидит расхождение «Git != кластер» и вернет версию из Git, отменив откат. Rollback через API допустим только временно и с отключенным auto-sync (`argocd app set production-app --sync-policy none`). Штатный путь — всегда git revert.

#### Гейты качества перед слиянием в GitOps-репозиторий

PR в конфигурационный репозиторий — последняя точка контроля перед продом. Набор обязательных проверок (порядок — от быстрой к дорогой):

```yaml
# .github/workflows/config-validate.yml — триггер: pull_request на GitOps-репозиторий
jobs:
  quality-gates:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Секреты и утечки (секунды)
        run: |
          gitleaks detect --redact --no-git   # включая содержимое измененных файлов

      - name: Рендер всех целевых окружений
        run: |
          kustomize build apps/billing/overlays/prod > rendered-prod.yaml
          kustomize build apps/billing/overlays/staging > rendered-staging.yaml

      - name: Соответствие схемам Kubernetes API (десятки секунд)
        run: |
          kubeconform -strict -summary -kubernetes-version 1.35.0 rendered-prod.yaml rendered-staging.yaml

      - name: Политики платформы (Rego)
        run: conftest test --policy policies/ rendered-prod.yaml
        # policies/: запрет :latest, обязательные resources.limits,
        # запрет привилегированных контейнеров, обязательные probes

      - name: Статический анализ качества манифестов
        run: kube-score score rendered-prod.yaml --ignore-container-cpu-limit

      # Если в репозитории есть собственные чарты — тестируются до рендера:
      - name: Юнит-тесты Helm-чартов
        run: |
          helm unittest ./charts/billing          # шаблоны: значения, ветвления, outputs
          ct lint --charts ./charts/billing       # линт чарта (chart-testing)

      - name: Dry-run применения на реальном API (минуты)
        run: |
          kubectl apply --dry-run=server --server-side -f rendered-prod.yaml
        env: { KUBECONFIG: /tmp/readonly-kubeconfig }   # read-only учетка CI!
```

Ключевые правила эксплуатации:

- **Dry-run выполняется под учеткой только для чтения** (`get/list/create/update` на validate-namespace): гейт должен провалиться при нарушении RBAC/адмиссии, но не иметь права что-либо изменить.
- **Server-side dry-run** проверяет не только схемы, но и мутирующие вебхуки (admission) — именно они чаще всего ломают деплой после того, как `kubeconform` пропустил валидный YAML.
- **Собственные чарты тестируются отдельно от манифестов**: `helm unittest` проверяет логику шаблонов на фиксированных значениях (юнит-уровень), `ct lint`/install — валидность и установку чарта (интеграционный уровень). Разбор подхода: [unit testing Helm-чартов](../Kubernetes/ToolsUtilities/Helm/Advanced/unit_testing.md); рендер-гейты выше не заменяют эти тесты, а идут после них.
- **Политики conftest хранятся в том же репозитории** — изменение политики проходит такое же ревью, как изменение манифестов; runtime-контроль Kyverno/Gatekeeper в кластере дублирует их уже без права на ошибку.
- Каждый гейт публикует результат как check-run PR'а; правило branch protection: merge разрешен только при зеленых статусах.

Концептуальный разбор инструментов валидации (и сравнение с runtime-контролем) — в [обзоре методологии](./GitOps_overview.md); выбор движка политик — в [управлении политиками](./Concepts/gitops-policy-management.md).

### Продвижение между окружениями (Promotion)

Для перехода с Staging на Production используется обновление тега или версии чарта в GitOps-репозитории. Это может выполняться:
- **Вручную:** Через Pull Request в инфраструктурный репозиторий.
- **Автоматически:** Через специализированные инструменты (например, ArgoCD Image Updater), которые следят за новыми тегами в OCI-реестре.

Ручной flow через PR — эталон с точки зрения аудита и контроля:

```diff
# GitOps-репозиторий, PR "Promote app 0.1.0 -> 0.2.0 to production"
 apiVersion: argoproj.io/v1alpha1
 kind: Application
 metadata:
   name: production-app
 spec:
   source:
     chart: app
     repoURL: ghcr.io/org/charts
-    targetRevision: 0.1.0
+    targetRevision: 0.2.0
```

PR проходит ревью (второй человек видит ровно то, что изменится), затем merge — и ArgoCD доводит кластер до нового состояния. Требование обязательного аппрува настраивается branch protection правилами Git-хостинга.

Автоматизация продвижения — сравнение подходов:

| Инструмент | Механизм | Сильные стороны | Когда выбирать |
| :--- | :--- | :--- | :--- |
| Argo CD Image Updater (v1.x) | CRD `ImageUpdater`: контроллер опрашивает реестр и обновляет параметры приложений через API Argo CD (write-back в Git опционален); аннотационный подход объявлен legacy | Нулевой порог входа, быстрая обратная связь | Dev/QA среды, где коммиты в Git не обязательны |
| Flux Image Automation | Политики `ImagePolicy` генерируют объекты-маркеры; CMFA graduated | Обязательный git-коммит на каждое обновление, digest pinning | Среды, где история изменений в Git критична |
| Kargo (v1.x) | `Warehouse` следит за артефактами, `Freight` фиксирует версионную комбинацию (digest+чарт+коммит), `Stage` проводит ее через цепочку сред с гейтами | Гейты (ручное одобрение, промоушен-тесты), побайтово идентичный артефакт во всех средах | Production-конвейеры с несколькими средами и требованиями комплаенса |

Выбор между ними подробно разобран в [Жизненном цикле образов](./Concepts/containerization_and_image_storage.md); настройка первого варианта — в [Argo CD Image Updater](./ArgoCD/argocd_image_updater.md). Комбинация «Image Updater для dev + ручной PR-промоушен для prod» — распространенный практичный старт: автоматизация там, где цена ошибки мала, контроль там, где она высока.

## Типовые проблемы и их решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `denied: permission_denied` / `403` при `docker push` в GHCR | Отсутствует `permissions: packages: write` в workflow или невыполнен `docker login` | Добавить блок permissions и шаг `docker/login-action`; для PAT проверить scope `write:packages` |
| `cosign sign` падает с `GET ... MANIFEST_UNKNOWN` | Подпись выполняется до `docker push` — образа еще нет в реестре | Переставить шаг подписи после публикации (правильный порядок: build → scan → push → sign) |
| Чарт опубликован, но ArgoCD не видит новую версию | Кэш репозитория в ArgoCD / интервал опроса | `argocd repo list` и принудительный refresh; настроить вебхук реестра на `/api/webhook` |
| Приложение вечно OutOfSync по полю `spec.replicas` | HPA мутирует replicas, selfHeal возвращает обратно — цикл | Добавить `ignoreDifferences` для поля в Application (см. [Синхронизация](./ArgoCD/synchronization.md)) |
| После merge в main ничего не деплоится | CI упал на шаге Trivy/Cosign, а алерты пайплайна никто не смотрит | Настроить уведомления о падениях CI ([уведомления в GitOps](./gitops_notifications.md)); правило «деплой возможен только зеленой сборкой» |
| `prune` удалил больше, чем ожидалось | Коммит случайно удалил манифесты/директорию | Восстановить через `git revert`; на будущее: sync window и требование ревью на prod-ветку GitOps-репозитория |
| `helm push` требует логина отдельно от docker | Helm использует собственное хранилище учетных данных | Выполнить `helm registry login` в том же шаге перед push |

## Дополнительная информация

**Связанные документы:**
- [Обзор методологии GitOps](./GitOps_overview.md) — фундаментальные принципы и подходы.
- [Обзор ArgoCD](./ArgoCD/argocd_overview.md) — CD-агент для Kubernetes.
- [Жизненный цикл образов](./Concepts/containerization_and_image_storage.md) — тегирование и хранение артефактов в OCI.

**Рекомендации:**
1.  **Наименьшие привилегии в CI**: Используйте автоматически выдаваемый `GITHUB_TOKEN` с минимальным набором permissions вместо долгоживущих PAT. Для keyless-подписи Cosign права выдаются через OIDC и не требуют хранения ключей вообще.
2.  **Digest-pinning для production**: Ссылайтесь на образ по digest (`app@sha256:...`), а не по плавающему тегу — гарантирует побайтовую идентичность проверенного артафакта во всех средах и защищает от подмены тега после сканирования.
3.  **Разделение Source Repo и Config Repo**: Отдельный GitOps-репозиторий изолирует состояние инфраструктуры от разработки: у деплоя свои правила защиты веток, свой набор ревьюеров и своя история.
4.  **Валидация подписей в кластере**: Подпись бесполезна, если ее никто не проверяет — настройте Kyverno/Gatekeeper-политики, блокирующие поды без валидной подписи доверенного пайплайна ([управление политиками](./Concepts/gitops-policy-management.md)).
5.  **Наблюдаемость пайплайна**: Свяжите три плоскости — статус CI (GitHub Actions), состояние GitOps-репозитория и здоровье приложений (уведомления ArgoCD) — иначе сбой на любом этапе останется незамеченным ([уведомления в GitOps](./gitops_notifications.md)).

**Очистка окружения** (демонтаж демо-сценария):

```bash
# 1. Удалить приложение из-под управления ArgoCD (каскадно удалит ресурсы из кластера)
argocd app delete production-app --cascade --yes
# → application 'production-app' deleted

# 2. Удалить опубликованные артефакты (ghcr.io → Packages → app → Delete),
#    либо через API для внутренней Harbor-инстанции

# 3. Удалить workflow-файлы из репозитория и отозвать выданные PAT
```

## Вопросы для собеседования

### Почему деплой из CI-пайплайна (`kubectl apply` после сборки) не считается полноценным GitOps?
Push-модель дает только однократное применение: нет непрерывной детекции дрейфа и самовосстановления, креденшилы кластера лежат в CI, аудит применения размазан по логам пайплайна. Это CI-driven deployment; GitOps добавляет реконсиляцию агентом внутри кластера и Git как SSoT.

### Что кладут в репозиторий приложения, а что в инфраструктурный?
App-repo: исходники, Dockerfile, чарт/манифесты шаблонов, CI сборки. Infra-repo: оверлеи сред с зафиксированными версиями образов, платформенные компоненты, корневые Application/Kustomization. Разделение развязывает циклы релизов и права доступа: разработчики не трогают прод-оверлеи напрямую.

### Зачем в PR-гейтах именно server-side dry-run, а не только kubeconform?
kubeconform проверяет схему YAML; server-side dry-run прогоняет манифесты через реальный API-сервер вместе с мутирующими вебхуками (admission) и выявляет конфликты SSA — то, что чаще всего ломает деплой при «валидном» YAML. Выполняется под read-only учеткой.

### Как организовать продвижение staging → prod?
PR с bump'ом версии/digest только в prod-overlay по тому же артефакту, что прошел staging (digest pinning), обязательные гейты PR, ревью владельца сервиса. Автоматизация: Renovate/Kargo — см. [стратегии продвижения](./GitOps_overview.md).

### Как правильно откатить неудачный релиз?
`git revert` коммита с bump'ом — Argo CD сам вернет кластер; это сохраняет историю и SSoT. UI-Rollback — экстренная мера: приложение уйдет OutOfSync относительно Git, self-heal временно отключится, и без follow-up revert'а следующий автосинк вернет плохую версию.
