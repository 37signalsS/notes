# ArgoCD vs. Flux: Сравнение Подходов и Манифестов

> **Актуальные версии (февраль 2026):** ArgoCD v3.3, Flux v2.x (GitOps Toolkit). Оба проекта — CNCF Graduated.

ArgoCD и Flux — два ведущих GitOps-инструмента в экосистеме CNCF, но они реализуют свои задачи с разной философией. Это сравнение фокусируется на ключевых архитектурных различиях и том, как они отражаются в структуре манифестов.

## Определения

- **ArgoCD**: Централизованный GitOps-инструмент с упором на "все-в-одном", мощный Web UI и мультикластерное управление из коробки. Его основной ресурс — `Application`, который описывает, *что*, *откуда* и *куда* разворачивать.
- **Flux**: Набор ("toolkit") декомпозированных, независимых контроллеров, которые работают вместе. Философия Flux ближе к "Unix-way" — каждый инструмент делает одну вещь хорошо. Ответственность разделена между разными CRD (например, `GitRepository` + `Kustomization`).

## Базовые концепции: Ключевые различия

### 1. Архитектура и потребление ресурсов

| Аспект | ArgoCD | Flux |
| :--- | :--- | :--- |
| **Архитектура** | Монолитное приложение (API server + repository server + application controller + Dex + Redis) | Модульная архитектура на контроллерах (GitOps Toolkit) |
| **Компоненты** | Централизованный API server, UI, Redis для кэширования | Source Controller, Kustomize Controller, Helm Controller, Notification Controller, Image Automation Controller |
| **Потребление ресурсов** | Выше (~2× CPU/памяти при синхронизации) | Ниже (статические бинарные контроллеры) |
| **Хранение состояния** | Полный граф ресурсов в памяти | Каждый контроллер отслеживает только свои объекты |

### 2. Модель конфигурации

- **ArgoCD**: Использует единый, монолитный CRD `Application`. В нем смешаны все аспекты: ссылка на Git-репозиторий (`source`), целевой кластер (`destination`) и политика синхронизации (`syncPolicy`). Это делает конфигурацию простой для старта, но менее гибкой.
- **Flux**: Разделяет обязанности. `Source`-контроллер отвечает за получение артефактов из источников (`GitRepository`, `HelmRepository`). `Kustomize`- и `Helm`-контроллеры отвечают за применение (`Kustomization`, `HelmRelease`). Это более многословно, но позволяет переиспользовать один источник для нескольких развертываний.

### 3. Пользовательский интерфейс (UI)

- **ArgoCD**: Поставляется с мощным и интуитивно понятным Web UI, который является одной из его главных особенностей. UI позволяет визуализировать состояние приложений, просматривать `diff`, откатываться и управлять синхронизацией.
- **Flux**: Не имеет официального встроенного UI. Основной способ взаимодействия — CLI (`flux`) и просмотр CRD в кластере (`kubectl`). Существуют сторонние UI, например Weave GitOps.

### 4. Управление доступом и безопасность

| Функция | ArgoCD | Flux |
| :--- | :--- | :--- |
| **RBAC** | Встроенный детализированный (Projects, whitelist ресурсов) | Kubernetes-native RBAC |
| **SSO** | Нативный через Dex (Auth0, Google, Okta, Zitadel) | Нет нативного, зависит от провайдера кластера |
| **Секреты в Git** | External Secrets Operator / Vault | Нативная SOPS интеграция |

### 5. Мультикластерное управление

- **ArgoCD**: Централизованная модель. Один инстанс ArgoCD может управлять множеством кластеров из единой консоли.
- **Flux**: Децентрализованный набор контроллеров. Обычно один набор контроллеров Flux управляет одним кластером. Координация между кластерами осуществляется через Git.

## Практические сценарии: Примеры Манифестов

Рассмотрим, как развернуть одно и то же Kustomize-приложение с помощью обоих инструментов.

### ArgoCD: Единый манифест `Application`

ArgoCD описывает все в одном ресурсе.

```yaml
# apps/argocd/my-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  # ЧТО: источник в Git
  source:
    repoURL: https://github.com/my-org/my-app-config.git
    path: overlays/production
    targetRevision: main
  # КУДА: целевой кластер и namespace
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
  # КАК: политика синхронизации
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

### Flux: Разделение на `Source` и `Kustomization`

Flux требует как минимум два ресурса: один для описания источника, другой — для описания процесса применения.

```yaml
# 1. Описываем источник (ЧТО)
# sources/git-repo.yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: my-app-config-repo
  namespace: flux-system
spec:
  interval: 1m
  url: https://github.com/my-org/my-app-config.git
  ref:
    branch: main
---
# 2. Описываем применение (КУДА и КАК)
# apps/flux/my-app.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: my-app
  namespace: flux-system
spec:
  interval: 5m
  path: ./overlays/production # Путь внутри источника
  prune: true
  # Ссылка на источник
  sourceRef:
    kind: GitRepository
    name: my-app-config-repo
  # Целевой namespace
  targetNamespace: my-app
```

## Дополнительная информация

### Расширенное функциональное сравнение

| Функция | ArgoCD | Flux |
| :--- | :--- | :--- |
| **Helm** | Нативная поддержка | Первый класс через Helm Controller |
| **Kustomize** | Через плагин | Первый класс через Kustomize Controller |
| **Image automation** | Отдельный ArgoCD Image Updater | Встроенный image-automation-controller |
| **Progressive delivery** | Argo Rollouts (Canary, Blue-Green) | Flagger (Canary, A/B, Blue-Green) |
| **Уведомления** | Встроенные с v2.6 | Dedicated Notification Controller |
| **Интервалы синхронизации** | Глобальный | На ресурс |
| **Обнаружение дрейфа** | Визуальный diff в UI | Автоматическая коррекция |
| **Air-gapped** | Поддерживается | Поддерживается (спроектирован для изоляции) |
| **Шаблонизация** | ApplicationSet | Kustomize overlays |
| **Аудит** | Встроенные event logs | Kubernetes-native events |

### Новые функции и изменения (2025-2026)

#### ArgoCD

- **AWS EKS Managed ArgoCD** (GA ноябрь 2025): полностью управляемый сервис вне кластера клиента
- Интеграции: AWS Secrets Manager, Amazon ECR, AWS CodeCommit, CodeConnections
- ApplicationSet: сокращение multi-cluster развёртывания с 30+ до ~5 минут
- PreDelete Hooks (v3.3): запуск Jobs перед удалением приложения
- OIDC Refresh: обновление сессий без таймаутов
- Granular RBAC: whitelist имён ресурсов для детального контроля доступа
- Progressive Sync: постепенное развёртывание на несколько кластеров с валидацией

#### Flux

- **Публикация roadmap 2025** после закрытия Weaveworks (февраль 2024)
- Поддержка от ControlPlane, Microsoft Azure, GitLab, Cisco
- Стабильные и beta API для production
- Регулярные релизы (активная поддержка сообществом)
- Нативная интеграция с Azure AKS (flux extension)

### Масштабирование и производительность

| Метрика | ArgoCD | Flux |
| :--- | :--- | :--- |
| **Тестировано приложений** | 50,000+ | Десятки тысяч |
| **Подключённые кластеры** | 1,000+ | Ограничено capacity API server |
| **UI производительность** | Замедление при 3,000-5,000 приложений | N/A (нет UI) |
| **Потребление памяти** | Выше (граф в памяти + Redis) | Ниже (контроллеры отслеживают свои объекты) |

### Рекомендации по выбору

#### Выбирайте ArgoCD когда

- Команда новичок в GitOps и нужен визуальный интерфейс
- Приоритет — developer experience
- Управление приложениями на множестве кластеров из единой консоли
- Требуется SSO, детализированный RBAC, audit trails
- Работа на AWS EKS (managed ArgoCD GA ноябрь 2025)
- Важны размер сообщества и зрелость экосистемы (17,800+ GitHub stars, NPS 79)
- Регулируемые отрасли (compliance, аудит)

#### Выбирайте Flux когда

- Platform engineering команда строит модульные инфраструктурные паттерны
- Ограничения по ресурсам (edge, staging, малые пулы)
- Требуется нативная SOPS для секретов в Git
- Автоматическая promotion образов — ключевой workflow
- Предпочтение Kubernetes-native CRD-first workflow
- Работа на Azure AKS (нативный Flux extension)
- Air-gapped или изолированные среды

#### Гибридный подход

- **Flux** для инфраструктуры (Terraform, cluster addons, CNI)
- **ArgoCD** для доставки приложений
- Рекомендуется только для зрелых platform engineering практик

### Риски и ограничения

| Аспект | ArgoCD | Flux |
| :--- | :--- | :--- |
| **Недостатки** | Выше потребление ресурсов; отдельный компонент для image automation; нет нативной SOPS | Нет встроенного UI; нет нативного SSO; меньшее сообщество (6,500 stars) |
| **Зависимости** | UI замедляется при 3000-5000 приложений без тюнинга | Закрылся Weaveworks (февраль 2024) — поддержка через сообщество |

---

- **[Обзор ArgoCD](../ArgoCD/argocd_overview.md)**: Подробное введение в архитектуру и возможности ArgoCD.
- **[Обзор Flux](../Flux/overview.md)**: Введение в философию и компоненты GitOps Toolkit от Flux.
- **[Установка ArgoCD](../ArgoCD/argocd_installation_and_setup.md)**: Практическое руководство по установке ArgoCD v3.x.
- **[Helm интеграция](../ArgoCD/helm_integration.md)**: Описание подходов к развёртыванию с помощью Helm.
- **Официальная документация ArgoCD**: [argoproj.github.io/cd/](https://argoproj.github.io/cd/)
- **Официальная документация Flux**: [fluxcd.io](https://fluxcd.io/)
