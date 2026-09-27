# Kustomize — Тестирование и валидация конфигураций

## 1. Определения

**Snapshot-тестирование Kustomize** — подход к регрессионному тестированию, при котором вывод `kustomize build` коммитится в Git как эталонный снапшот. Любое изменение в base/overlay'ах приводит к изменению снапшота, которое требует явного review в PR.

**Policy-валидация** — проверка сгенерированных манифестов на соответствие организационным политикам безопасности через OPA/Rego (conftest) или Kyverno CLI перед применением в кластере.

**kustomize cfg lint** — встроенная утилита Kustomize для статического анализа kustomization.yaml на соответствие рекомендациям и поиска потенциальных проблем (циклические зависимости, устаревшие поля).

## 2. Основные концепции

### Уровни тестирования

| Уровень | Инструмент | Что проверяет | Скорость |
| :--- | :--- | :--- | :--- |
| **Lint** | `kustomize cfg lint` | Синтаксис, устаревшие поля, структура | Мгновенно |
| **Schema** | `kubeconform` | Соответствие схемам Kubernetes API | Мгновенно |
| **Snapshot** | `kustomize build` + diff | Регрессия: что изменилось в итоговом манифесте | ~1 сек |
| **Policy** | `conftest` (OPA/Rego) | Организационные политики безопасности | ~1 сек |
| **Best practices** | `polaris` | Рекомендации по ресурсам и безопасности | ~2 сек |
| **Dry-run** | `kubectl apply --dry-run=server` | RBAC, quotas, существование CRD | ~1 сек |

### Snapshot-тестирование

**Принцип:** каждый PR, изменяющий Kustomize-конфигурацию, должен содержать обновленный снапшот. Reviewer видит точный diff итоговых манифестов.

**Структура:**
```text
tests/
├── snapshots/
│   ├── production/
│   │   └── rendered.yaml       # Эталонный вывод kustomize build
│   ├── staging/
│   │   └── rendered.yaml
│   └── dev/
│       └── rendered.yaml
├── update-snapshots.sh         # Скрипт обновления снапшотов
└── verify-snapshots.sh         # Скрипт проверки актуальности
```

**Скрипт обновления:**
```bash
#!/bin/bash
# tests/update-snapshots.sh
set -euo pipefail

for env in dev staging production; do
  echo "Updating snapshot for $env..."
  kustomize build "overlays/$env/" > "tests/snapshots/$env/rendered.yaml"
done

echo "Snapshots updated. Review changes and commit."
```

**Скрипт проверки:**
```bash
#!/bin/bash
# tests/verify-snapshots.sh
set -euo pipefail

EXIT_CODE=0

for env in dev staging production; do
  echo "Verifying snapshot for $env..."
  kustomize build "overlays/$env/" > "/tmp/current-$env.yaml"

  if ! diff -u "tests/snapshots/$env/rendered.yaml" "/tmp/current-$env.yaml"; then
    echo "ERROR: Snapshot for $env is outdated!"
    EXIT_CODE=1
  else
    echo "OK: Snapshot for $env is up to date."
  fi
done

exit $EXIT_CODE
```

**Интеграция в CI (GitHub Actions):**
```yaml
name: Snapshot Tests
on: [pull_request]

jobs:
  snapshot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Kustomize
        run: |
          curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
          sudo mv kustomize /usr/local/bin/

      - name: Verify snapshots
        run: bash tests/verify-snapshots.sh
```

### kustomize cfg lint

```bash
# Базовая проверка
kustomize cfg lint .
# → Предупреждения об устаревших полях (bases, patchesStrategicMerge)

# Проверка конкретной директории
kustomize cfg lint overlays/production/

# Что проверяет:
# - Устаревшие поля (bases → resources, patchesStrategicMerge → patches)
# - Циклические зависимости
# - Невалидные ссылки на ресурсы
# - Форматирование YAML (kustomize cfg fmt)
```

**Автоматическое форматирование:**
```bash
# Форматирование всех kustomization.yaml
kustomize cfg fmt .

# Проверка без изменений (dry-run)
kustomize cfg fmt . --sort-order order
```

## 3. Практические сценарии

### 3.1. conftest: Rego-политики для Kustomize output

**Установка:**
```bash
# macOS
brew install conftest

# Linux
curl -sL https://github.com/open-policy-agent/conftest/releases/latest/download/conftest_Linux_x86_64.tar.gz | tar xz
sudo mv conftest /usr/local/bin/
```

**Пример Rego-политики:**
```rego
# policies/deployment.rego
package main

# Обязательные resource limits
deny[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  not container.resources.limits.cpu
  msg := sprintf("Container %s must have CPU limits", [container.name])
}

deny[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  not container.resources.limits.memory
  msg := sprintf("Container %s must have memory limits", [container.name])
}

# Запрет :latest тега
deny[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  endswith(container.image, ":latest")
  msg := sprintf("Container %s uses :latest tag", [container.name])
}

# Требование runAsNonRoot
deny[msg] {
  input.kind == "Deployment"
  not input.spec.template.spec.securityContext.runAsNonRoot
  msg := "Deployment must set runAsNonRoot: true"
}

# Запрет privileged
deny[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  container.securityContext.privileged == true
  msg := sprintf("Container %s must not be privileged", [container.name])
}
```

**Запуск:**
```bash
# Валидация Kustomize output через conftest
kustomize build overlays/production/ | conftest test --policy policies/ -

# С выводом в JSON (для CI)
kustomize build overlays/production/ | conftest test --policy policies/ --output json -
```

### 3.2. kubeconform: валидация схем

```bash
# Установка
curl -sL https://github.com/yannh/kubeconform/releases/latest/download/kubeconform_linux_amd64.tar.gz | tar xz
sudo mv kubeconform /usr/local/bin/

# Базовая валидация
kustomize build overlays/production/ | kubeconform -strict -summary -
# → Summary: 15 resources found, 0 errors

# Валидация с kubernetes-version
kustomize build overlays/production/ | kubeconform -kubernetes-version 1.29.0 -strict -summary -

# Валидация с дополнительными схемами (для CRD)
kustomize build overlays/production/ | kubeconform \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
  -strict -summary -
```

### 3.3. polaris: best practices

```bash
# Установка
brew install FairwindsOps/tap/polaris

# Audit манифестов
polaris audit --file manifests.yaml --set-exit-code-on-error

# Audit Kustomize директории
polaris audit --kustomize-dir overlays/production/ --set-exit-code-on-error

# Что проверяет:
# - Container has CPU limits
# - Container has memory limits
# - Container has readiness probe
# - Container has liveness probe
# - Running as non-root
# - Not privileged
# - Root filesystem is read-only
```

### 3.4. Полный pipeline валидации (Makefile)

```makefile
# Makefile
.PHONY: validate

validate: build lint schema policy snapshot

build:
	kustomize build overlays/production/ > /tmp/manifests.yaml

lint:
	kustomize cfg lint .

schema: build
	kubeconform -strict -summary /tmp/manifests.yaml

policy: build
	conftest test /tmp/manifests.yaml --policy policies/

snapshot: build
	diff -u tests/snapshots/production/rendered.yaml /tmp/manifests.yaml

dry-run: build
	kubectl apply --dry-run=server -f /tmp/manifests.yaml

update-snapshot: build
	cp /tmp/manifests.yaml tests/snapshots/production/rendered.yaml
```

### 3.5. pre-commit hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: kustomize-lint
        name: Kustomize Lint
        entry: kustomize cfg lint .
        language: system
        files: kustomization\.yaml$
      - id: kustomize-build
        name: Kustomize Build
        entry: sh -c 'kustomize build overlays/production/ | kubeconform -strict -summary -'
        language: system
        files: \.(yaml|yml)$
      - id: kustomize-snapshot
        name: Kustomize Snapshot Check
        entry: bash tests/verify-snapshots.sh
        language: system
        files: \.(yaml|yml)$
```

## 4. Дополнительная информация

### Матрица инструментов

| Инструмент | Назначение | Язык политик | Интеграция с Kustomize |
| :--- | :--- | :--- | :--- |
| `kubeconform` | Schema validation | N/A | `kustomize build \| kubeconform -` |
| `conftest` | Policy validation | OPA/Rego | `kustomize build \| conftest test -` |
| `polaris` | Best practices | Go | `polaris audit --kustomize-dir` |
| `kustomize cfg lint` | Lint Kustomize | N/A | Нативная |
| `kustomize cfg fmt` | Format YAML | N/A | Нативная |

### См. также

- [Debugging Kustomize](./kustomize_debugging.md) — troubleshooting ошибок
- [Отладка и диагностика](./kustomize_debugging.md) — пошаговый чеклист
- [Conftest/OPA](../../../CI-CD/Testing/tdd_bdd_overview.md) — policy-тестирование
