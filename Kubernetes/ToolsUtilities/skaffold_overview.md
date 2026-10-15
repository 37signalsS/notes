# Skaffold: Локальная разработка и CI/CD для Kubernetes

**Актуально для:** Skaffold v2.x

---

## Определения

**Skaffold** — инструмент для непрерывной разработки (Continuous Development) приложений на Kubernetes. Автоматизирует цикл: сборка образа → пуш в реестр → деплой манифестов → порт-форвардинг → слежение за изменениями. Работает с любыми билдерами (Docker, Buildpacks, Kaniko, Bazel) и деплоерами (kubectl, kustomize, helm).

**skaffold.yaml** — декларативный конфигурационный файл, описывающий пайплайн: `build` (артефакты), `deploy` (манифесты/helm/kustomize), `profiles` (окружения), `portForward`, `sync` (hot-reload без пересборки).

**Профиль (profile)** — именованный набор переопределений конфигурации для конкретного окружения (dev, staging, prod). Активируется флагом `-p <name>`.

**Artifacts.json** — файл метаданных собранных артефактов (image digest, tag), передаваемый между стадиями CI (`skaffold build --file-output`) и CD (`skaffold deploy --build-artifacts`).

---

## Базовые концепции

### Жизненный цикл команды `skaffold dev`

```text
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  Watch FS   │──▶│   Build     │──▶│   Deploy    │──▶│ Port-forward│
│  (changes)  │   │  (images)   │   │ (manifests) │   │  + logs     │
└─────────────┘   └─────────────┘   └─────────────┘   └──────┬──────┘
                                                             │
                              ┌──────────────────────────────┘
                              ▼
                        ┌─────────────┐
                        │   Sync      │  (hot-reload: copy files / restart pod)
                        └─────────────┘
```

- **Build**: собирает образы по Dockerfile / buildpacks / custom builder, тегает уникальным digest.
- **Deploy**: применяет манифесты через kubectl / kustomize / helm; поддерживает `kubeContext` и `namespace`.
- **Port-forward**: автоматически пробрасывает порты сервисов на localhost.
- **Sync**: при изменении исходников копирует файлы в запущенный контейнер (Go, Java, Node, Python) или пересобирает/передеплоит.

### Режимы работы

| Режим | Команда | Назначение |
|:---|:---|:---|
| **Dev (loop)** | `skaffold dev` | Непрерывный цикл: watch → build → deploy → port-forward → sync |
| **Run (once)** | `skaffold run` | Одноразовая сборка + деплой + логи (для CI) |
| **Build only** | `skaffold build` | Только сборка образов, экспорт `artifacts.json` |
| **Deploy only** | `skaffold deploy` | Деплой по готовому `artifacts.json` (CD стадия) |
| **Render only** | `skaffold render` | Генерация итогового YAML без применения (debug) |
| **Delete** | `skaffold delete` | Удаление всех ресурсов, созданных последним `run`/`dev` |
| **Diagnose** | `skaffold diagnose` | Проверка конфигурации, вывод разрешённого `skaffold.yaml` |

---

## Практические сценарии

### Установка (Linux/macOS)

```bash
# Через curl (последняя стабильная)
curl -Lo skaffold https://storage.googleapis.com/skaffold/releases/latest/skaffold-linux-amd64
sudo install skaffold /usr/local/bin/

# Или через пакетный менеджер
# brew install skaffold        # macOS
# sudo dnf install skaffold    # Fedora
# choco install skaffold       # Windows

skaffold version
# → v2.15.0
```

### Минимальный `skaffold.yaml` (Docker + kubectl)

```yaml
apiVersion: skaffold/v4beta11
kind: Config
metadata:
  name: my-app
build:
  artifacts:
    - image: my-app
      docker:
        dockerfile: Dockerfile
deploy:
  kubectl:
    manifests:
      - k8s/*.yaml
portForward:
  - resourceType: service
    resourceName: my-app
    port: 8080
    localPort: 8080
```

### Профили для окружений

```yaml
# skaffold.yaml (фрагмент)
profiles:
  - name: dev
    activation:
      - command: dev
    build:
      artifacts:
        - image: my-app
          sync:
            manual:
              - src: "src/**/*.go"
                dest: /app
    portForward:
      - resourceType: service
        resourceName: my-app
        port: 8080
        localPort: 8080

  - name: staging
    build:
      artifacts:
        - image: registry.corp/staging/my-app
    deploy:
      kubectl:
        manifests:
          - k8s/overlays/staging/*.yaml
    kubeContext: staging-cluster

  - name: prod
    build:
      artifacts:
        - image: registry.corp/prod/my-app
    deploy:
      helm:
        releases:
          - name: my-app
            chartPath: helm/my-app
            valuesFiles:
              - helm/my-app/values-prod.yaml
    kubeContext: prod-cluster
```

---

## Операции и команды

### 1. Dev режим (горячая перезагрузка)

```bash
skaffold dev --port-forward
# → Starting dev loop...
# → Building [my-app]...
# → Deploying [my-app]...
# → Port forwarding service/my-app in namespace default...
# → Forwarding from 127.0.0.1:8080 -> 8080
# → [my-app] 2026-10-14 10:00:00 Server started on :8080
```

- `--port-forward`: пробрасывает порты сервисов на localhost (автоматически для всех сервисов в манифестах).
- `--tail`: стримит логи подов в терминал (вкл. по умолчанию в `dev`).
- `--status-check`: отключить проверку готовности подов перед порт-форвардом.
- Изменения в исходниках → авто-sync (если настроен `sync`) или полная пересборка/передеплой.

### 2. Разовая сборка и деплой (CI)

```bash
skaffold run --tail
# → Building [my-app]...
# → Tag: my-app:abc123def456
# → Deploying [my-app]...
# → [my-app] 2026-10-14 10:00:00 Server started on :8080
```

- `--tail`: выводит логи подов после деплоя (удобно в CI).
- `--default-repo`: задать базовый реестр для тегов (например, `registry.corp/project`).
- `--digest-source=local`: использовать локальный digest вместо пуша в реестр (для kind/k3d).

### 3. Только сборка (без деплоя)

```bash
skaffold build --file-output=artifacts.json
# → Building [my-app]...
# → Tag: my-app:abc123def456
# → Artifacts written to artifacts.json
```

**artifacts.json**:
```json
{
  "builds": [
    {
      "imageName": "my-app",
      "tag": "my-app:abc123def456",
      "digest": "sha256:abc123...",
      "local": false
    }
  ]
}
```
- Используется в CI для передачи артефактов в стадию деплоя.
- `--file-output`: путь к файлу метаданных (по умолчанию stdout).

### 4. Деплой готовых артефактов (CD)

```bash
skaffold deploy --build-artifacts=artifacts.json
# → Deploying [my-app]...
# → Applying k8s/deployment.yaml...
# → Applying k8s/service.yaml...
```

- `--build-artifacts`: путь к `artifacts.json` от стадии `build`.
- `--render-only`: только сгенерировать YAML в stdout без применения.
- Работает с любым деплоером (kubectl, helm, kustomize) из `skaffold.yaml`.

### 5. Только рендеринг манифестов

```bash
skaffold render --output=manifests.yaml
# → Rendered manifests written to manifests.yaml
```

- `--output`: файл для вывода (по умолчанию stdout).
- `--profile`: использовать профиль для рендеринга (например, `-p staging`).
- Полезно для: code review, `kubectl diff -f manifests.yaml`, `kubeconform` валидация, GitOps превью.

### 6. Использовать конкретный профиль

```bash
skaffold dev -p staging
# → Activating profile: staging
# → Using kubeContext: staging-cluster
# → Building [registry.corp/staging/my-app]...
```

- `-p, --profile`: активирует профиль по имени (может повторяться: `-p dev -p debug`).
- Профили комбинируются: последний переопределяет предыдущие.
- `skaffold run -p prod` — деплой в продакшн профиль.

### 7. Диагностика проблем конфигурации

```bash
skaffold diagnose
# → Checking skaffold.yaml...
# → ✓ Configuration is valid
# → Resolved configuration:
# →   build:
# →     artifacts:
# →       - image: my-app
# →         docker:
# →           dockerfile: Dockerfile
# →   deploy:
# →     kubectl:
# →       manifests:
# →         - k8s/*.yaml
```

- Проверяет синтаксис, разрешает переменные/профили, выводит итоговый конфиг.
- Выходной код: 0 = OK, 1 = ошибки конфигурации.
- Полезно в CI перед `run`/`dev`.

### 8. Удалить задеплоенные ресурсы

```bash
skaffold delete
# → Deleting deployed resources...
# → Deleted deployment/my-app
# → Deleted service/my-app
```

- Удаляет ресурсы, созданные последним `skaffold run` или `skaffold dev` (по лейблам `skaffold.dev/run-id`).
- `--filename`: удалить по конкретному манифесту (как `kubectl delete -f`).
- `--profile`: использовать профиль для определения манифестов.

---

## Дополнительные полезные флаги

| Флаг | Описание |
|:---|:---|
| `--kubeconfig <path>` | Явный kubeconfig (вместо `KUBECONFIG` env) |
| `--kube-context <name>` | Контекст кластера (переопределяет профиль) |
| `--namespace <ns>` | Целевой неймспейс (переопределяет манифесты) |
| `--default-repo <repo>` | Базовый реестр для тегов образов |
| `--insecure-registry` | Разрешить небезопасные реестры (HTTP) |
| `--verbosity=info\|debug\|trace` | Уровень логирования |
| `--output=json\|yaml` | Формат вывода для `render`, `diagnose` |
| `--cleanup=true\|false` | Авто-очистка при Ctrl+C в `dev` (по умолчанию true) |

---

## Интеграция с CI/CD

### GitLab CI (стадии build → deploy)

```yaml
# .gitlab-ci.yml
stages:
  - build
  - deploy-staging
  - deploy-prod

variables:
  SKAFFOLD_DEFAULT_REPO: $CI_REGISTRY_IMAGE

build:
  stage: build
  image: gcr.io/kaniko-project/executor:debug
  script:
    - skaffold build --file-output=artifacts.json --default-repo=$CI_REGISTRY_IMAGE
  artifacts:
    reports:
      dotenv: artifacts.json
    paths:
      - artifacts.json
    expire_in: 1 week

deploy-staging:
  stage: deploy-staging
  image: gcr.io/k8s-skaffold/skaffold:latest
  needs:
    - build
  script:
    - skaffold deploy --build-artifacts=artifacts.json -p staging
  environment:
    name: staging
    url: https://staging.app.corp

deploy-prod:
  stage: deploy-prod
  image: gcr.io/k8s-skaffold/skaffold:latest
  needs:
    - build
  when: manual
  script:
    - skaffold deploy --build-artifacts=artifacts.json -p prod
  environment:
    name: production
    url: https://app.corp
```

### GitHub Actions

```yaml
# .github/workflows/ci.yml
jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      artifacts: ${{ steps.build.outputs.artifacts }}
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/setup-gcloud@v2
      - name: Build with Skaffold
        id: build
        run: |
          skaffold build --file-output=artifacts.json --default-repo=gcr.io/${{ secrets.GCP_PROJECT }}
          echo "artifacts=$(cat artifacts.json)" >> $GITHUB_OUTPUT

  deploy-staging:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with: credentials_json: ${{ secrets.GCP_SA_KEY }}
      - name: Deploy to Staging
        run: |
          echo '${{ needs.build.outputs.artifacts }}' > artifacts.json
          skaffold deploy --build-artifacts=artifacts.json -p staging
```

---

## Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `no space left on device` при сборке | Docker cache забит | `docker system prune -a --volumes`; `--cache-from` в билдере |
| `skaffold dev` не видит изменения | `sync` не настроен или путь не совпадает | Проверить `sync.manual` пути в `skaffold.yaml`; `skaffold diagnose` |
| Порт-форвардинг не работает | Сервис не готов / неверный selector | `--status-check=false`; проверить `kubectl get svc`; `portForward.resourceName` |
| `image not found` при деплое | Образ не запушен в реестр | `--default-repo` + `docker login`; для kind: `skaffold build --digest-source=local` |
| Профиль не активируется | Неверное имя или `activation` условие | `skaffold config list-profiles`; проверить `activation.command: dev` |
| `skaffold delete` не удаляет ресурсы | Лейбл `skaffold.dev/run-id` не совпадает | `kubectl get all -l skaffold.dev/run-id` → ручное удаление |

---

## Лучшие практики

1. **Отделяйте сборку и деплой в CI**: `skaffold build --file-output` → артефакт → `skaffold deploy --build-artifacts`. Гарантирует воспроизводимость и позволяет передеплоить без пересборки.
2. **Используйте профили для окружений**: dev (sync + port-forward), staging (registry + kustomize overlay), prod (helm + values). Не хардкодьте реестры/контексты в базовом конфиге.
3. **Настройте `sync` для горячей перезагрузки**: для Go — `manual` копия бинарника; для Node/Python — `auto` (rsync); для Java — JRebel / Spring Boot DevTools.
4. **Валидируйте манифесты перед деплоем**: `skaffold render | kubeconform -strict` в CI pipeline.
5. **Закрепляйте версии базовых образов и билдеров**: в `skaffold.yaml` или через `skaffold.yaml` схему (`apiVersion: skaffold/v4beta11`).
6. **Логируйте digest образов**: `skaffold build --file-output` даёт детерминированный digest для traceability и rollback.
7. **Для локальных кластеров (kind/k3d) используйте `--digest-source=local`**: избегает пуша в удалённый реестр, работает через локальный containerd.

---

## Дополнительная информация

### Официальная документация
- [Skaffold Documentation](https://skaffold.dev/docs/) — полное руководство, конфигурация, примеры.
- [Skaffold Configuration Reference](https://skaffold.dev/docs/references/yaml/) — схема `skaffold.yaml` (v4beta11).
- [Skaffold Profiles](https://skaffold.dev/docs/concepts/profiles/) — детали профилей и активации.

### Связанные документы базы знаний
- [Helm Overview](../ToolsUtilities/Helm/helm_overview.md) — деплой через Helm в Skaffold.
- [Kustomize Overview](../ToolsUtilities/kustomize/kustomize_overview.md) — деплой через Kustomize в Skaffold.
- [Kubectl Commands](../ToolsUtilities/kubectl_commands.md) — базовые kubectl операции для отладки.
- [ArgoCD Overview](../GitOps/ArgoCD/overview.md) — GitOps деплой артефактов, собранных Skaffold.
- [Docker Build Optimization](../Docker/Dockerfile/dockerfile_optimization_tools.md) — оптимизация Dockerfile для быстрой сборки в Skaffold.