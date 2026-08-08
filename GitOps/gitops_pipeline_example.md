# GitOps: пример пайплайна

## Определения

**GitOps-пайплайн** — это конвейер доставки программного обеспечения, реализующий декларативный подход к управлению состоянием системы. В этой модели система **CI (Continuous Integration — непрерывная интеграция)** отвечает за сборку и проверку артефактов, а система **CD (Continuous Delivery — непрерывная доставка)** обеспечивает соответствие фактического состояния кластера описанию в Git-репозитории.

## Основные концепции

### Разделение зон ответственности

Пайплайн 2026 года строится на строгом разделении функций:

1.  **CI (Continuous Integration):** Проверка кода, запуск тестов, сканирование безопасности, сборка и подписание артефактов (Docker-образ и Helm-чарт). Результат — неизменяемый артефакт в реестре.
2.  **CD (Continuous Delivery):** Контроллер внутри кластера (агент) опрашивает источники и применяет изменения. CD-система не «знает» о процессе сборки, она оперирует только готовыми версиями.

### Используемые инструменты и технологии

- **CI-платформа:** GitHub Actions (интеграция с VCS).
- **CD-агент:** ArgoCD (модель Pull).
- **Безопасность:** Trivy (сканирование), Cosign (подписание образов), Gitleaks (поиск секретов).
- **Доставка:** OCI-реестр (единое хранилище для образов и Helm-чартов).
- **Синхронизация:** Server-Side Apply (SSA) для минимизации конфликтов манифестов.

### Преимущества подхода

- **Безопасность:** CI-система не имеет доступа к API Kubernetes (не требует `kubeconfig`).
- **Прослеживаемость:** Четкая связь между SHA коммита, тегом образа и состоянием ресурсов.
- **Декларативность:** Описание всей инфраструктуры и приложений хранится в коде.

## Практические сценарии

### Поток выполнения (Workflow)

#### 1. Проверка в Feature-ветке

При каждом пуше в ветку разработки запускаются базовые проверки:
- Линтинг кода и YAML-манифестов.
- Unit-тестирование.
- Сканирование на секреты.

#### 2. Процесс сборки и публикации (CI-часть)

При слиянии в ветку `main` пайплайн выполняет следующие шаги:

```yaml
# Пример GitHub Actions для CI-части
jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build image
        run: docker build -t ghcr.io/org/app:${{ github.sha }} .
      - name: Scan with Trivy
        run: trivy image --severity CRITICAL --exit-code 1 ghcr.io/org/app:${{ github.sha }}
      - name: Sign image
        run: cosign sign --key cosign.key ghcr.io/org/app:${{ github.sha }}
      - name: Push to OCI
        run: docker push ghcr.io/org/app:${{ github.sha }}
      - name: Update Helm Chart appVersion
        run: |
          sed -i 's/appVersion: .*/appVersion: "${{ github.sha }}"/' charts/app/Chart.yaml
          helm package charts/app
          helm push app-0.1.0.tgz oci://ghcr.io/org/charts
```

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
    repoURL: ghcr.io/org/charts
    targetRevision: 0.1.0
    helm:
      valueFiles:
        - values-prod.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: prod
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

**Алгоритм работы CD:**
1.  **Обнаружение:** ArgoCD получает вебхук или опрашивает OCI-реестр/Git.
2.  **Сравнение:** Вычисляется разница (`diff`) между текущим состоянием кластера и новым Helm-чартом.
3.  **Применение:** Если включена автосинхронизация, изменения применяются в кластер.
4.  **Проверка:** Ожидание успешного прохождения проб (Liveness/Readiness probes).
5.  **Тестирование:** Запуск E2E-тестов в окружении Staging перед продвижением в Production.

### Продвижение между окружениями (Promotion)

Для перехода с Staging на Production используется обновление тега или версии чарта в GitOps-репозитории. Это может выполняться:
- **Вручную:** Через Pull Request в инфраструктурный репозиторий.
- **Автоматически:** Через специализированные инструменты (например, ArgoCD Image Updater), которые следят за новыми тегами в OCI-реестре.

## Дополнительная информация

**Связанные документы:**
- [Обзор методологии GitOps](./GitOps_overview.md) — фундаментальные принципы и подходы.
- [Обзор ArgoCD](./ArgoCD/argocd_overview.md) — CD-агент для Kubernetes.
- [Жизненный цикл образов](./Concepts/containerization_and_image_storage.md) — тегирование и хранение артефактов в OCI.
