# Kustomize — Git-автоматизация и управление образами

## 1. Определения

**Image Tag Automation** — автоматическое обновление тегов образов Docker в Kustomize-манифестах через инструменты сканирования зависимостей (Renovate, Dependabot), обеспечивающее актуальность версий без ручного вмешательства.

**Image Promotion Pipeline** — процесс автоматического продвижения образа из staging в production через обновление тега в Git-репозитории конфигураций с последующей синхронизацией через GitOps.

**Pre-commit hooks** — локальные Git-хуки, выполняющие валидацию Kustomize-манифестов (lint, build, snapshot diff) до фиксации коммита, предотвращающие попадание сломанных конфигураций в ветку.

## 2. Основные концепции

### Цикл жизни образа в Kustomize

```text
Разработчик пушит код → CI собирает образ → CI обновляет тег в kustomization.yaml
→ GitOps-контроллер применяет → Kubernetes делает Rolling Update
```

```bash
# Ключевая команда в CI:
cd overlays/production
kustomize edit set image myapp=registry.internal/team/myapp:v1.7.3
# → Автоматически обновляет поле images в kustomization.yaml
```

### Renovate: автоматическое обновление тегов

**Renovate** — инструмент автоматического обновления зависимостей. Поддерживает Kustomize natивно через менеджер `docker`.

**renovate.json:**
```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:base"],
  "packageRules": [
    {
      "matchManagers": ["kustomize"],
      "matchUpdateTypes": ["minor", "patch"],
      "automerge": true
    },
    {
      "matchManagers": ["kustomize"],
      "matchUpdateTypes": ["major"],
      "automerge": false,
      "labels": ["breaking-change"]
    }
  ]
}
```

**Что сканирует Renovate в Kustomize:**
```yaml
# kustomization.yaml — Renovate находит:
images:
  - name: registry.internal/team/myapp
    newTag: v1.7.2  # ← Renovate предложит обновить до v1.7.3

resources:
  - https://github.com/org/repo//base?ref=v2.1.0  # ← Renovate предложит v2.2.0
```

**Пример PR от Renovate:**
```markdown
## What does this PR do?
Updates Docker image registry.internal/team/myapp from v1.7.2 to v1.7.3

## docker-tags
| Package | Update | Old | New |
|---------|--------|-----|-----|
| registry.internal/team/myapp | minor | v1.7.2 | v1.7.3 |
```

### Dependabot: альтернатива Renovate

**.github/dependabot.yml:**
```yaml
version: 2
updates:
  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "daily"
    labels:
      - "dependencies"
    open-pull-requests-limit: 10
  - package-ecosystem: "docker"
    directory: "/overlays/production/"
    schedule:
      interval: "daily"
```

### Image Promotion Pipeline

**CI-скрипт для promotion:**
```bash
#!/bin/bash
# scripts/promote.sh
# Использование: ./promote.sh v1.7.3
set -euo pipefail

IMAGE_TAG="$1"
GITOPS_REPO="git@github.com:my-org/infra-gitops.git"
WORKDIR=$(mktemp -d)

git clone "$GITOPS_REPO" "$WORKDIR"
cd "$WORKDIR"

# Обновление тега во всех overlays
for env in staging production; do
  cd "overlays/$env"
  kustomize edit set image myapp=registry.internal/team/myapp:"$IMAGE_TAG"
  kustomize edit set tag myapp:"$IMAGE_TAG"
  cd -
done

# Коммит и пуш
git add overlays/
git commit -m "chore: promote myapp to $IMAGE_TAG"
git push origin main
```

**GitHub Actions с image injection:**
```yaml
name: Deploy Production
on:
  workflow_dispatch:
    inputs:
      image_tag:
        description: 'Image tag (например, v1.7.3)'
        required: true

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4

      - name: Setup Kustomize
        run: |
          curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
          sudo mv kustomize /usr/local/bin/

      - name: Update image tag
        working-directory: overlays/production
        run: |
          kustomize edit set image myapp=registry.internal/team/myapp:${{ github.event.inputs.image_tag }}
          cat kustomization.yaml

      - name: Commit and push
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add overlays/production/
          git commit -m "chore: deploy myapp ${{ github.event.inputs.image_tag }} to production"
          git push
```

### Digest-based деплой (immutable images)

```bash
# Обновление по digest (самый безопасный способ)
kustomize edit set image myapp=registry.internal/team/myapp@sha256:abc123...
# → Фиксирует точный образ, тег может меняться

# Рекомендация: комбинировать digest + tag для совместимости с kubectl rollout history
kustomize edit set image myapp=registry.internal/team/myapp:v1.7.3@sha256:abc123...
```

## 3. Практические сценарии

### 3.1. Pre-commit hook для Kustomize

**.pre-commit-config.yaml:**
```yaml
repos:
  - repo: local
    hooks:
      - id: kustomize-lint
        name: Kustomize Lint
        entry: kustomize cfg lint .
        language: system
        files: kustomization\.yaml$
        pass_filenames: false

      - id: kustomize-build-validate
        name: Kustomize Build + kubeconform
        entry: sh -c 'kustomize build . | kubeconform -strict -summary -'
        language: system
        files: \.(yaml|yml)$

      - id: kustomize-build-opa
        name: Kustomize Build + OPA
        entry: sh -c 'kustomize build . | conftest test --policy policies/ -'
        language: system
        files: \.(yaml|yml)$
```

**Установка:**
```bash
brew install pre-commit
pre-commit install
# Теперь при каждом git commit будут запускаться проверки
```

### 3.2. Makefile для локальной работы

```makefile
# Makefile
KUSTOMIZE := kustomize
ENV ?= production
OVERLAY := overlays/$(ENV)

.PHONY: build lint validate snapshot apply diff update-snapshot

build:
	$(KUSTOMIZE) build $(OVERLAY) > /tmp/manifests-$(ENV).yaml

lint:
	$(KUSTOMIZE) cfg lint .

validate: build
	kubeconform -strict -summary /tmp/manifests-$(ENV).yaml

policy: build
	conftest test /tmp/manifests-$(ENV).yaml --policy policies/

snapshot: build
	diff -u tests/snapshots/$(ENV)/rendered.yaml /tmp/manifests-$(ENV).yaml

update-snapshot: build
	cp /tmp/manifests-$(ENV).yaml tests/snapshots/$(ENV)/rendered.yaml

apply: validate
	kubectl apply -k $(OVERLAY)/

diff: build
	kubectl diff -f /tmp/manifests-$(ENV).yaml
```

### 3.3. Renovate: полная конфигурация

**renovate.json:**
```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:base"],
  "kustomize": {
    "enabled": true
  },
  "packageRules": [
    {
      "description": "Auto-merge patch updates",
      "matchManagers": ["kustomize"],
      "matchUpdateTypes": ["patch"],
      "automerge": true,
      "automergeType": "pr"
    },
    {
      "description": "Group minor updates",
      "matchManagers": ["kustomize"],
      "matchUpdateTypes": ["minor"],
      "groupName": "kustomize-minor",
      "automerge": false
    },
    {
      "description": "Major updates require manual review",
      "matchManagers": ["kustomize"],
      "matchUpdateTypes": ["major"],
      "labels": ["breaking-change", "needs-review"]
    }
  ],
  "vulnerabilityAlerts": {
    "enabled": true,
    "labels": ["security"]
  }
}
```

### 3.4. Git-вклад в аудит-трейл

```bash
# История изменений конфигураций
git log --oneline --all -- overlays/production/kustomization.yaml
# → a1b2c3d chore: deploy myapp v1.7.3 to production
# → e4f5g6h chore: deploy myapp v1.7.2 to production
# → i7j8k9l feat: add resource limits for production

# Кто изменил и когда
git log --format="%h %an %s" -- overlays/production/

# Diff между версиями
git diff v1.0.0..v1.1.0 -- overlays/production/
```

## 4. Дополнительная информация

### Лучшие практики

1. **Никогда не коммитьте `kustomize build` output** в GitOps-репозиторий — храните только source overlay'и
2. **Digest + tag** вместо tag-only для supply chain security
3. **Automerge** для patch-обновлений, manual review для minor/major
4. **Snapshot-тесты** в CI для отслеживания изменений в итоговых манифестах

### См. также

- [Debugging Kustomize](./kustomize_debugging.md) — troubleshooting
- [Тестирование и валидация](./kustomize_testing_validation.md) — snapshot, conftest, lint
- [Renovate](../../../GitOps/Concepts/renovate_dependency_updates.md) — автоматизация зависимостей
