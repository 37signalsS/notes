# Kustomize — Локальная разработка

## 1. Определения

**Локальная разработка с Kustomize** — процесс проверки, сборки и валидации Kustomize-манифестов на локальной машине разработчика перед коммитом в Git. Включает: сборку манифестов, валидацию схем, проверку diff, локальный dry-run против кластера.

**PR workflow** — последовательность действий разработчика: изменение overlay → локальная проверка → коммит → push → CI-валидация → merge → GitOps применяет.

**Makefile-подход** — стандартизация локальных команд через Makefile, обеспечивающий единообразную среду для всех членов команды.

## 2. Основные концепции

### Быстрая ссылка: основные команды

```bash
# Сборка манифестов
kustomize build overlays/production/

# Сохранение в файл
kustomize build overlays/production/ > /tmp/rendered.yaml

# Просмотр diff с кластером
kubectl diff -k overlays/production/

# Dry-run без реального применения
kubectl apply -k overlays/production/ --dry-run=client

# Dry-run на стороне сервера (проверка RBAC, quotas)
kubectl apply -k overlays/production/ --dry-run=server

# Просмотр что именно изменится
kustomize build overlays/production/ | kubectl diff -f -
```

### Makefile для Kustomize-проекта

```makefile
# Makefile
.PHONY: help build lint validate diff apply dry-run snapshot update-snapshot fmt

KUSTOMIZE ?= kustomize
KUBECTL ?= kubectl
ENV ?= production
OVERLAY = overlays/$(ENV)

help: ## Показать эту справку
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

build: ## Собрать манифесты
	$(KUSTOMIZE) build $(OVERLAY) > /tmp/manifests-$(ENV).yaml
	@echo "Build saved to /tmp/manifests-$(ENV).yaml"

lint: ## Линт kustomization.yaml
	$(KUSTOMIZE) cfg lint .

fmt: ## Форматировать kustomization.yaml
	$(KUSTOMIZE) cfg fmt .

validate: build ## Валидация схем (kubeconform)
	kubeconform -strict -summary /tmp/manifests-$(ENV).yaml

policy: build ## OPA-политики (conftest)
	conftest test /tmp/manifests-$(ENV).yaml --policy policies/

diff: build ## Diff с текущим состоянием кластера
	$(KUBECTL) diff -f /tmp/manifests-$(ENV).yaml

dry-run: build ## Dry-run (client)
	$(KUBECTL) apply -f /tmp/manifests-$(ENV).yaml --dry-run=client

dry-run-server: build ## Dry-run (server, проверка RBAC)
	$(KUBECTL) apply -f /tmp/manifests-$(ENV).yaml --dry-run=server

apply: build ## Применить к кластеру
	$(KUBECTL) apply -k $(OVERLAY)/

delete: ## Удалить ресурсы
	$(KUBECTL) delete -k $(OVERLAY)/

snapshot: build ## Проверить снапшот
	diff -u tests/snapshots/$(ENV)/rendered.yaml /tmp/manifests-$(ENV).yaml

update-snapshot: build ## Обновить снапшот
	cp /tmp/manifests-$(ENV).yaml tests/snapshots/$(ENV)/rendered.yaml
	@echo "Snapshot updated for $(ENV)"

view: build ## Просмотреть собранный манифест
	$(KUSTOMIZE) build $(OVERLAY)
```

**Использование:**
```bash
# Справка
make help

# Сборка и проверка
make build ENV=production
make validate ENV=production
make diff ENV=production

# Применение
make apply ENV=staging

# Снапшоты
make snapshot ENV=production
make update-snapshot ENV=production
```

## 3. Практические сценарии

### 3.1. Полный PR workflow

```bash
# 1. Создать ветку
git checkout -b feature/add-monitoring

# 2. Внести изменения в overlay
vim overlays/production/kustomization.yaml

# 3. Локальная проверка
make lint
make build ENV=production
make validate ENV=production
make diff ENV=production

# 4. Проверить, что снапшот актуален
make snapshot ENV=production
# Если diff — обновить:
make update-snapshot ENV=production

# 5. Коммит
git add .
git commit -m "feat: add monitoring component to production"

# 6. Push и создание PR
git push origin feature/add-monitoring

# 7. CI автоматически проверит:
#    - kubeconform (schema)
#    - conftest (OPA)
#    - polaris (best practices)
#    - snapshot diff
#    - dry-run server
```

### 3.2. Проверка конкретного overlay перед деплоем

```bash
# Быстрая проверка
kustomize build overlays/staging/ | kubeconform -strict -summary -

# Просмотр что изменится
kustomize build overlays/staging/ | kubectl diff -f -
# → Покажет: "deployment.apps/web-server configured"
# → Если пусто — изменений нет

# Dry-run
kubectl apply -k overlays/staging/ --dry-run=client --server-side
```

### 3.3. Работа с несколькими окружениями одновременно

```bash
# Сравнение staging и production
diff <(kustomize build overlays/staging/) <(kustomize build overlays/production/)

# Или через файлы
kustomize build overlays/staging/ > /tmp/staging.yaml
kustomize build overlays/production/ > /tmp/prod.yaml
diff -u /tmp/staging.yaml /tmp/prod.yaml
```

### 3.4. Локальная валидация с OPA-политиками

```bash
# Если conftest установлен локально
kustomize build overlays/production/ | conftest test --policy policies/ -

# Или через make
make policy ENV=production
```

### 3.5. Pre-commit hook для автоматизации

```bash
# Установка pre-commit
brew install pre-commit

# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: kustomize-lint
        name: Kustomize Lint
        entry: kustomize cfg lint .
        language: system
        files: kustomization\.yaml$
        pass_filenames: false

      - id: kustomize-build
        name: Kustomize Build Check
        entry: sh -c 'kustomize build . | kubeconform -strict -summary -'
        language: system
        files: \.(yaml|yml)$

pre-commit install
# Теперь при git commit автоматически запускаются проверки
```

### 3.6. Docker-окружение для CI-локальной проверки

```dockerfile
# Dockerfile.validate
FROM alpine:3.19

RUN apk add --no-cache bash curl git jq

# kustomize
ARG KUSTOMIZE_VERSION=5.8.1
RUN curl -sL "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize/v${KUSTOMIZE_VERSION}/kustomize_v${KUSTOMIZE_VERSION}_linux_amd64.tar.gz" | tar xz \
    && mv kustomize /usr/local/bin/

# kubeconform
RUN curl -sL https://github.com/yannh/kubeconform/releases/latest/download/kubeconform_linux_amd64.tar.gz | tar xz \
    && mv kubeconform /usr/local/bin/

# conftest
RUN curl -sL https://github.com/open-policy-agent/conftest/releases/latest/download/conftest_Linux_x86_64.tar.gz | tar xz \
    && mv conftest /usr/local/bin/

WORKDIR /workspace
ENTRYPOINT ["bash"]
```

```bash
# Запуск валидации через Docker
docker build -t validate -f Dockerfile.validate .
docker run -v $(pwd):/workspace validate -c "
  kustomize build overlays/production/ | kubeconform -strict -summary - &&
  kustomize build overlays/production/ | conftest test --policy policies/ -
"
```

## 4. Дополнительная информация

### Зависимости для локальной разработки

| Инструмент | Установка | Назначение |
| :--- | :--- | :--- |
| `kustomize` | `brew install kustomize` | Сборка манифестов |
| `kubeconform` | `curl ... \| tar xz` | Schema validation |
| `conftest` | `brew install conftest` | OPA-политики |
| `kubectl` | Часто уже установлен | Dry-run, diff |
| `pre-commit` | `brew install pre-commit` | Git hooks |
| `make` | Обычно уже установлен | Makefile |

### Советы

1. **Всегда делайте `make diff` перед apply** — это покажет точный diff
2. **Используйте `--dry-run=server` в CI** — проверяет RBAC и quotas
3. **Храните policies/ в Git** — OPA-политики кодируются и ревьюятся
4. **Snapshot-тесты** — фиксируйте вывод `kustomize build` для отслеживания изменений

### См. также

- [Тестирование и валидация](./kustomize_testing_validation.md) — инструменты валидации
- [Debugging Kustomize](./kustomize_debugging.md) — troubleshooting
- [Git-автоматизация](./kustomize_git_automation.md) — pre-commit, Renovate
