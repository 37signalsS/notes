# Интеграция Kustomize в конвейеры CD

Интеграция Kustomize в конвейеры непрерывного развертывания (CD) обеспечивает автоматизированное, декларативное и воспроизводимое управление конфигурациями Kubernetes для различных окружений.

## 1. Определения

**Kustomize CD Integration** — процесс автоматического рендеринга и применения манифестов Kubernetes, настроенных через Kustomize, в целевые кластеры в рамках конвейера доставки.

**Push-модель (CI-driven)** — стратегия, при которой внешний конвейер (Jenkins, GitLab CI, GitHub Actions) активно подключается к кластеру и выполняет `kubectl apply -k`.

**Pull-модель (GitOps-driven)** — стратегия, при которой специальный агент внутри кластера (ArgoCD, Flux) отслеживает изменения в Git и самостоятельно синхронизирует состояние кластера с описанным в репозитории.

**Dry-run (Валидация)** — этап проверки сгенерированных манифестов на соответствие схемам Kubernetes API и политикам безопасности без их фактического применения.

## 2. Основные концепции

### Модели доставки

| Характеристика | Push-модель (CI-driven) | Pull-модель (GitOps) |
| :--- | :--- | :--- |
| **Инструменты** | Jenkins, GitHub Actions, GitLab CI | ArgoCD, Flux |
| **Доступ** | Требуются учетные данные кластера в CI | Агент уже внутри кластера |
| **State Drift** | Сложно отследить ручные изменения | Автоматическое исправление (Self-healing) |
| **Безопасность** | Широкий доступ для CI-раннеров | Минимальный доступ (только к Git) |

### Разделение ответственности
В зрелых процессах рекомендуется разделять репозиторий с исходным кодом приложения и репозиторий с конфигурациями Kubernetes. CI-пайплайн обновляет тег образа в `kustomization.yaml` (через `kustomize edit set image`), а CD-инструмент применяет изменения.

### Хеширование имен в CD
Использование `configMapGenerator` и `secretGenerator` является критическим для CD. Kustomize автоматически добавляет хеш к имени ресурса, что гарантирует запуск **Rolling Update** при изменении конфигурации, исключая ситуации, когда поды используют устаревшие данные.

## 3. Практические сценарии

### 3.1. Сценарий 1: Push-модель через GitHub Actions

Пример рабочего процесса, который валидирует и применяет манифесты.

```yaml
name: Deploy to Staging
on:
  push:
    branches: [ main ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Kustomize
        run: |
          curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
          sudo mv kustomize /usr/local/bin/

      - name: Validate Manifests (Dry-run)
        run: kustomize build overlays/staging | kubectl apply --dry-run=client -f -

      - name: Deploy
        run: kustomize build overlays/staging | kubectl apply -f -
```

### 3.2. Сценарий 2: Push-модель через Jenkins Pipeline

Расширенный пример с ручным подтверждением для Production.

```groovy
pipeline {
    agent any
    stages {
        stage('Checkout') {
            steps {
                git 'https://your-repo-url.git'
            }
        }
        stage('Build & Validate') {
            steps {
                sh 'kustomize build overlays/staging > staging-manifest.yaml'
                sh 'kustomize build overlays/production > production-manifest.yaml'
                // Валидация через kubeconform
                sh 'kustomize build overlays/staging | kubeconform -strict'
            }
        }
        stage('Deploy to Staging') {
            steps {
                sh 'kubectl apply -k overlays/staging/'
            }
        }
        stage('Promote to Production') {
            steps {
                input message: 'Promote to Production?'
                sh 'kubectl apply -k overlays/production/'
            }
        }
    }
}
```

### 3.3. Сценарий 3: Pull-модель через ArgoCD

ArgoCD нативно поддерживает Kustomize. Достаточно указать путь к директории.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app-staging
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://github.com/my-org/my-infra.git'
    targetRevision: HEAD
    path: overlays/staging
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: staging
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### 3.4. Управление секретами

Для CD критически важно не хранить секреты в открытом виде:
- **SOPS + Kustomize:** использование плагина `ksops` для расшифровки секретов на лету.
- **Sealed Secrets:** хранение зашифрованных манифестов в Git, которые расшифровываются контроллером в кластере.
- **External Secrets Operator:** использование `secretGenerator` в Kustomize для создания заполнителей, которые наполняются данными из внешнего хранилища (Vault).

### 3.5. Стратегия откатов и версионирование

Для обеспечения надежности рекомендуется:
1.  **Git-тегирование:** пометка коммитов в репозитории конфигураций тегами версий (например, `v1.0.1`).
2.  **Откат в Git:** выполнение `git revert` в репозитории конфигураций. GitOps-инструмент мгновенно применит предыдущее стабильное состояние.
3.  **Снапшоты релизов:** хранение сгенерированных манифестов в архиве артефактов CI для возможности быстрого `kubectl apply` в случае недоступности Git.

## 4. Дополнительная информация

### См. также
- **[Обзор и основные концепции](./kustomize_overview.md)** — базовые определения и установка.
- **[Структура и синтаксис](./kustomize_structure_and_syntax.md)** — детальный разбор `kustomization.yaml`.
- **[Валидация манифестов (kubeconform)](../kubeconform_overview.md)** — автоматическая проверка схем.

### Внешние ресурсы
- [Official Kustomize Documentation](https://kustomize.io/)
- [ArgoCD: Kustomize Integration](https://argo-cd.readthedocs.io/en/stable/user-guide/kustomize/)
- [Flux v2: Kustomization API](https://fluxcd.io/flux/components/kustomize/kustomization/)
