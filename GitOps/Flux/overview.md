# Flux: Гибкий GitOps-инструмент для Kubernetes

## Определения

**Flux** — это набор инструментов для непрерывной и прогрессивной доставки (continuous and progressive delivery) для Kubernetes, который поддерживает принципы GitOps. Проект инкубируется в Cloud Native Computing Foundation (CNCF). Flux автоматизирует развертывание, синхронизируя состояние кластера с конфигурациями, хранящимися в Git-репозиториях.

Flux придерживается "pull" модели, где его компоненты, работающие в кластере, отслеживают источники конфигураций (например, Git-репозитории) и применяют изменения к кластеру.

## Базовые концепции

### Архитектура и компоненты (GitOps Toolkit)

Flux имеет модульную архитектуру и представляет собой набор специализированных контроллеров, известных как **GitOps Toolkit**.

| Контроллер | Основные CRD | Назначение |
| --- | --- | --- |
| source-controller | GitRepository, HelmRepository, OCIRepository, Bucket | Получение исходников, версионирование артефактов, кеш артефактов |
| kustomize-controller | Kustomization | Применение манифестов/оверлеев Kustomize, порядок, prune, wait |
| helm-controller | HelmRelease | Управление релизами Helm как декларативными объектами |
| notification-controller | Provider, Alert, Receiver | Уведомления и webhook-триггеры |
| image-reflector/automation | ImageRepository, ImagePolicy, ImageUpdateAutomation | Отражение тегов образов и автоматические PR/коммиты для обновлений |

Ключевая особенность — все сущности описываются в виде CRD, что делает конвейер самодокументированным и управляемым через Git.

### Ключевые ресурсы (CRD)

*   **`GitRepository`**: Ресурс, описывающий Git-репозиторий как источник конфигураций.
*   **`Kustomization`**: Ресурс, который указывает, как применить манифесты из источника. Он определяет путь к манифестам, интервал синхронизации, зависимости и другие параметры.
*   **`HelmRelease`**: Декларативное представление релиза Helm. Он ссылается на `HelmChart` (описывающий чарт в `HelmRepository`) и позволяет переопределять значения (`values`).
*   **Поддержка зависимостей (`dependsOn`)**: Flux позволяет определять явные зависимости между ресурсами. Например, можно указать, что `HelmRelease` приложения зависит от `HelmRelease` базы данных, и Flux развернет их в правильном порядке.

### Сравнение с ArgoCD

| Характеристика          | Flux                                                                                             | ArgoCD                                                                                       |
| :---------------------- | :----------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------- |
| **Философия**           | Набор модульных, "unix-way" инструментов (toolkit), которые можно комбинировать. Гибкость и расширяемость. | Монолитное, но полнофункциональное решение с сильным фокусом на UI и мультикластерное управление. |
| **Пользовательский интерфейс** | Минималистичный UI (Web UI), основной способ взаимодействия — CLI (`flux`) и YAML-манифесты.         | Мощный и детализированный веб-интерфейс является одной из ключевых особенностей.             |
| **Установка**           | Использует команду `flux bootstrap` для первоначальной настройки и фиксации своей конфигурации в Git. | Устанавливается через манифесты `kubectl apply` или Helm.                                    |
| **Мульти-арендность (Multi-tenancy)** | Легко реализуется благодаря своей модульной структуре, позволяя разным командам управлять своими приложениями с помощью отдельных `Kustomization` ресурсов и источников. | Также поддерживает мульти-арендность через проекты (Projects), которые обеспечивают изоляцию. |
| **Управление секретами** | Интегрируется с SOPS "из коробки" для прозрачного шифрования секретов в Git.                      | Требует сторонних плагинов, таких как `argo-vault-plugin`, или инструментов вроде Sealed Secrets. |

### Использование OCI репозиториев

Flux может использовать OCI-совместимые репозитории (например, Docker Hub, Harbor) не только для хранения образов, но и для хранения конфигурационных артефактов (Helm-чартов, YAML-манифестов). Это позволяет унифицировать хранение артефактов и версионировать конфигурацию вместе с кодом приложения.

### Базовая связка: GitRepository + Kustomization
Ниже минимальный пример, в котором Flux забирает манифесты из Git и применяет их с очисткой «мусора» и ожиданием готовности объектов.
```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: platform-config
  namespace: flux-system
spec:
  interval: 1m
  url: https://github.com/org/platform-config
  ref:
    branch: main

---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: platform
  namespace: flux-system
spec:
  interval: 2m
  path: ./clusters/prod
  prune: true
  wait: true
  sourceRef:
    kind: GitRepository
    name: platform-config
  timeout: 5m
```
Реконсиляция строится в два шага: source-controller формирует «артефакт» из Git, kustomize-controller применяет его к кластеру. Для зависимостей между частями конфигурации используется поле dependsOn в Kustomization, что позволяет выражать порядок развертывания без стороннего оркестратора.

### Helm через операторы
Flux управляет Helm-чартами декларативно, без ручных helm install/upgrade. Репозиторий чартов и релиз описываются как CRD:
```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: bitnami
  namespace: flux-system
spec:
  interval: 5m
  url: https://charts.bitnami.com/bitnami

---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: redis
  namespace: databases
spec:
  interval: 5m
  chart:
    spec:
      chart: redis
      version: 18.x.x
      sourceRef:
        kind: HelmRepository
        name: bitnami
  values:
    replica:
      replicaCount: 3
```
helm-controller берет на себя обновления, откаты и контроль готовности, сохраняя историю ревизий в статусе CRD.

### Политики, безопасность и многотенантность
*   Разделение доступа достигается неймспейс-скоупом и указанием serviceAccountName в Kustomization; можно изолировать команды и окружения на уровне RBAC.
*   Поддерживается верификация артефактов и подписи коммитов; с Secrets работает через стандартные механизмы Kubernetes и интеграцию с SOPS для расшифровки на стороне кластера.
*   Drift устраняется автоматически благодаря loop-модели; опция prune управляет удалением неописанных ресурсов, а health checks предотвращают «разгон» при деградации.
*   Image Automation обновляет теги образов по политике (semver, latest, количество публикаций), создавая коммиты или PR в репозитории конфигурации, что сохраняет полный аудит изменений.

## Практические сценарии

### Установка Flux (Bootstrap)

Процесс начальной установки называется "бутстрэппинг". Он заключается в установке компонентов Flux в кластер и настройке синхронизации с Git-репозиторием, где будет храниться конфигурация самого Flux.

1.  **Подготовка**:
    *   Установить Flux CLI.
    *   Иметь доступ к кластеру Kubernetes.
    *   Создать Git-репозиторий (например, в GitHub или GitLab) и сгенерировать Personal Access Token (PAT) с правами на доступ к репозиторию.

2.  **Выполнение команды `bootstrap`**:
    Эта команда установит компоненты Flux, создаст `flux-system` `Kustomization` и зафиксирует изменения в указанном Git-репозитории.

    ```bash
    export GITHUB_TOKEN=<your-personal-access-token>
    export GITHUB_USER=<your-git-username>

    flux bootstrap github 
      --owner=$GITHUB_USER 
      --repository=my-cluster-config 
      --branch=main 
      --path=./clusters/my-cluster 
      --personal
    ```

    После выполнения этой команды Flux будет управлять самим собой через конфигурацию в этом репозитории.

### Развертывание приложения с помощью `HelmRelease`

1.  **Добавление источника Helm-репозитория**:
    Создайте манифест `HelmRepository` для репозитория, содержащего нужный чарт.

    ```yaml
    # ./clusters/my-cluster/podinfo-repo.yaml
    apiVersion: source.toolkit.fluxcd.io/v1beta2
    kind: HelmRepository
    metadata:
      name: podinfo
      namespace: flux-system
    spec:
      interval: 1h
      url: https://stefanprodan.github.io/podinfo
    ```

2.  **Создание `HelmRelease`**:
    Создайте манифест `HelmRelease`, который описывает развертывание чарта.

    ```yaml
    # ./clusters/my-cluster/podinfo-release.yaml
    apiVersion: helm.toolkit.fluxcd.io/v2beta1
    kind: HelmRelease
    metadata:
      name: podinfo
      namespace: default
    spec:
      interval: 5m
      chart:
        spec:
          chart: podinfo
          version: ">=6.0.0"
          sourceRef:
            kind: HelmRepository
            name: podinfo
            namespace: flux-system
      values:
        replicaCount: 2
        ui:
          color: "#34577c"
    ```

3.  **Добавление в `Kustomization`**:
    Убедитесь, что `flux-system` `Kustomization` отслеживает эти новые файлы, добавив их в `kustomization.yaml` в Git.

4.  **Синхронизация**:
    Зафиксируйте изменения в Git. Flux автоматически обнаружит их и развернет `podinfo`.

## Дополнительная информация

*   **Flux CLI**: Мощный инструмент для взаимодействия с Flux, который позволяет выполнять синхронизацию вручную (`flux reconcile`), проверять состояние (`flux get`) и многое другое.
*   **Web UI**: Существует официальный дашборд (Weave GitOps) и другие community-проекты, которые предоставляют веб-интерфейс для визуализации состояния системы.