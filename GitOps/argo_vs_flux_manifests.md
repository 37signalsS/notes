# ArgoCD vs. Flux: Сравнение Подходов и Манифестов

> **Надежность: 10** (Подтверждено SSoT и актуальными данными на февраль 2026)
> **Актуальные версии:** ArgoCD v3.3, Flux v2.x (GitOps Toolkit). Оба проекта являются CNCF (Cloud Native Computing Foundation) Graduated.

**ArgoCD** и **Flux** — два ведущих GitOps-инструмента в экосистеме CNCF, реализующие свои задачи с разной философией. Данное сравнение фокусируется на ключевых архитектурных различиях и их отражении в структуре манифестов.

## Определения

- **ArgoCD**: Централизованный GitOps-инструмент с упором на принцип "все-в-одном". Обладает мощным **UI (User Interface — пользовательский интерфейс)** и встроенными функциями мультикластерного управления. Основной ресурс — `Application`.
- **Flux**: Набор ("toolkit") декомпозированных, независимых контроллеров. Философия Flux следует принципу "Unix-way" — каждый инструмент выполняет одну задачу. Ответственность разделена между несколькими **CRD (Custom Resource Definition — кастомное определение ресурса)**, такими как `GitRepository` и `Kustomization`.

## Базовые концепции

### 1. Архитектура и потребление ресурсов

| Аспект | ArgoCD | Flux |
| :--- | :--- | :--- |
| **Архитектура** | Монолитная (API server, repository server, application controller, Dex, Redis) | Модульная (GitOps Toolkit на независимых контроллерах) |
| **Компоненты** | Централизованный сервер, UI, Redis для кэширования | Source, Kustomize, Helm, Notification, Image Automation контроллеры |
| **Потребление ресурсов** | Выше (~2× CPU/памяти при синхронизации) | Ниже (статические бинарные файлы контроллеров) |
| **Хранение состояния** | Полный граф ресурсов в памяти | Каждый контроллер отслеживает только свои объекты |

### 2. Модель конфигурации

- **ArgoCD**: Использует единый ресурс `Application`. В нем объединены источник в Git (`source`), целевой кластер (`destination`) и политики синхронизации (`syncPolicy`). Это упрощает старт, но дает меньше гибкости при переиспользовании источников.
- **Flux**: Разделяет обязанности. `Source`-контроллер отвечает за получение артефактов (`GitRepository`, `HelmRepository`), а `Kustomize`- и `Helm`-контроллеры — за их применение (`Kustomization`, `HelmRelease`). Это позволяет использовать один источник для множества независимых развертываний.

### 3. Интерфейс управления

- **ArgoCD**: Поставляется с развитым Web UI, который визуализирует состояние ресурсов кластера, позволяет просматривать различия (**diff**), логи подов и выполнять ручную синхронизацию или откат.
- **Flux**: Не имеет официального встроенного графического интерфейса. Основное взаимодействие происходит через **CLI (Command Line Interface — интерфейс командной строки)** `flux` и стандартные инструменты Kubernetes (`kubectl`). Существуют сторонние решения, такие как Weave GitOps.

### 4. Безопасность и доступ

| Функция | ArgoCD | Flux |
| :--- | :--- | :--- |
| **RBAC (Role-Based Access Control)** | Встроенный детализированный (проекты, лимиты ресурсов) | Нативный Kubernetes RBAC |
| **SSO (Single Sign-On)** | Нативный через Dex (OAuth2, LDAP, SAML) | Нет нативного, зависит от провайдера кластера |
| **Секреты в Git** | Внешние операторы или Vault | Нативная интеграция с Mozilla SOPS |

### 5. Мультикластерное управление

- **ArgoCD**: Централизованная модель. Один инстанс ArgoCD может управлять парком удаленных кластеров из единой точки.
- **Flux**: Децентрализованная модель. Обычно в каждом кластере работает свой набор контроллеров. Координация между кластерами реализуется через структуру директорий в Git.

## Практические сценарии

### Пример 1: Развертывание Kustomize-приложения

#### Вариант ArgoCD: Манифест `Application`

```yaml
# apps/argocd/my-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  # Откуда брать манифесты
  source:
    repoURL: https://github.com/my-org/my-app-config.git
    path: overlays/production
    targetRevision: main
  # Куда разворачивать
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
  # Политика синхронизации
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

#### Вариант Flux: Разделение на `Source` и `Kustomization`

```yaml
# 1. Описание источника
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
# 2. Описание применения
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: my-app
  namespace: flux-system
spec:
  interval: 5m
  path: ./overlays/production
  prune: true
  sourceRef:
    kind: GitRepository
    name: my-app-config-repo
  targetNamespace: my-app
```

## Дополнительная информация

### Функциональное сравнение возможностей

| Функция | ArgoCD | Flux |
| :--- | :--- | :--- |
| **Helm** | Нативная поддержка | Через Helm Controller |
| **Image Automation** | Отдельный ArgoCD Image Updater | Встроенный image-automation-controller |
| **Прогрессивная доставка** | Argo Rollouts (Canary, Blue-Green) | Flagger (Canary, A/B, Blue-Green) |
| **Интервалы синхронизации** | Глобальный для контроллера | Индивидуальный для каждого ресурса |
| **Обнаружение дрейфа** | Визуальный анализ в UI | Автоматическая коррекция контроллером |

### Изменения и тренды (2025-2026)

**ArgoCD:**

- **AWS EKS Managed ArgoCD** (ноябрь 2025): предоставление CD как сервиса.
- **Progressive Sync**: постепенное обновление группы кластеров с проверкой здоровья.
- **OIDC (OpenID Connect) Refresh**: улучшенная работа с сессиями пользователей.

**Flux:**

- **Нативная интеграция Azure AKS**: использование Flux как расширения кластера.
- **Стабильные API**: переход большинства CRD в статус `v1` для промышленного использования.
- **Поддержка сообщества**: активное развитие после реструктуризации Weaveworks в 2024 году.

**Рекомендация по выбору:**

- Выбирайте **ArgoCD**, если важен визуальный контроль, детальный RBAC и управление множеством кластеров из одной консоли.
- Выбирайте **Flux**, если требуется легковесное решение, модульный подход "Unix-way" или нативная поддержка шифрования SOPS для секретов.

**Связанные документы:**

- [Обзор методологии GitOps](../GitOps_overview.md)
- [Обзор ArgoCD](./ArgoCD/argocd_overview.md)
- [Обзор Flux](../flux.md)
- [Управление секретами в GitOps](../secrets_encryption.md)

**Официальные ресурсы:** [ArgoCD Documentation](https://argoproj.github.io/cd/), [Flux Documentation](https://fluxcd.io/).
