# Crossplane: Управление облачной инфраструктурой через Kubernetes

## Что такое Crossplane?

Crossplane — это решение класса "инфраструктура как код" (IaC), которое позволяет управлять облачной инфраструктурой различных провайдеров через Kubernetes. Он разворачивается в Kubernetes и из него взаимодействует с облачной инфраструктурой.

**Ключевые возможности:**

*   **Представление облачных сервисов как Kubernetes CRD:** После установки Crossplane автоматически становятся доступны Custom Resource Definitions (CRD) — YAML-манифесты, которые используются для создания ресурсов в облаке.
*   **GitOps-интеграция:** Прекрасно интегрируется с инструментами GitOps, такими как Argo CD и Flux.
*   **Политики управления:** Поддерживает RBAC и OPA.

**Архитектура Crossplane:**

1.  Пользователь выполняет `kubectl apply` для YAML-манифеста ресурса.
2.  Манифест хранится в etcd Kubernetes.
3.  Crossplane Core (набор контроллеров) отслеживает CRD-объекты и синхронизирует состояние с реальной инфраструктурой.
4.  Crossplane Core передает запрос провайдеру через его API.
5.  Облачный сервис создается на стороне провайдера.
6.  Crossplane Core получает статус о запущенном сервисе и хранит это состояние в Kubernetes.

## Сравнение: Crossplane vs. Terraform

| Характеристика            | Crossplane                                 | Terraform                                        |
| :------------------------ | :----------------------------------------- | :----------------------------------------------- |
| **Среда выполнения**      | Выполняется из Kubernetes (разворачивается в кластере) | Выполняется с любого хоста (например, ноутбука) |
| **Управление состоянием** | Состояние хранится в etcd Kubernetes       | Использует локальные файлы состояния, требует настройки внешнего хранилища (S3) |
| **Безопасность**          | Использует политики Kubernetes (RBAC, OPA) | Отсутствует встроенная политика безопасности       |
| **Модель управления**     | Декларативная (использует YAML)            | Декларативная (использует HCL)                  |
| **Расширяемость**         | Поддерживает множество провайдеров, можно дописывать | Поддерживает множество провайдеров, можно дописывать |
| **GitOps-интеграция**     | Нативная поддержка Argo CD и Flux          | Требует дополнительной настройки и доработки      |

## Методология GitOps и Argo CD

GitOps — это методология, которая на 90% строится на использовании кластера Kubernetes. Crossplane идеально вписывается в эту концепцию, предоставляя удобный инструмент для реализации GitOps-инфраструктуры. Argo CD является ключевым инструментом GitOps, который взаимодействует с Git-репозиториями, забирает Crossplane CRD и применяет их в кластере.

## Практическая установка и использование Crossplane

### 1. Предварительные требования

*   **Кластер Kubernetes:** В примере используется Minikube (установлен на ноутбуке).
*   **Argo CD:** Развернут в кластере.

### 2. Установка Crossplane

1.  **Добавление Helm-репозитория Crossplane:**

    ```bash
    helm repo add crossplane-stable https://charts.crossplane.io/stable
    helm repo update
    ```

2.  **Установка чарта Crossplane:**

    ```bash
    helm install crossplane crossplane-stable/crossplane --namespace crossplane-system --create-namespace
    ```

3.  **Проверка установки:**

    ```bash
    kubectl get pods -n crossplane-system
    ```

4.  **Установка Crossplane CLI:** (бинарник `crossplane`)
    *   Скачать бинарник Crossplane CLI (инструкции зависят от ОС).
    *   Переместить бинарник в директорию, доступную из командной строки (например, `/usr/local/bin`).

5.  **Установка провайдера Yandex Cloud:**

    ```bash
    crossplane xpkg install provider crossplane/provider-yandex-cloud:v0.1.0 # Пример версии, использовать актуальную
    ```

6.  **Проверка установленных CRD для Yandex Cloud:**

    ```bash
    kubectl get crd | grep yandex
    ```

    Это покажет доступные ресурсы для управления Yandex Cloud (диски, Redis, PostgreSQL и т.д.).

### 3. Интеграция с Yandex Cloud

1.  **Создание сервисного аккаунта в Yandex Cloud:**

    *   Перейти в **Identity and Access Management** -> **Сервисные аккаунты**.
    *   Создать новый сервисный аккаунт, например, `crossplane-core`.
    *   Назначить роль **Editor** (для тестовой инфраструктуры можно использовать Administrator).
    *   Создать **авторизованный ключ** (JSON-файл), выбрать алгоритм `RSA 4096`. Скачать файл ключей.

2.  **Создание Kubernetes Secret с ключом сервисного аккаунта:**

    *   Предположим, скачанный файл ключей называется `sa-key.json`.
    *   Создать секрет:

        ```bash
        kubectl create secret generic yandex-cloud-credentials \
          --from-file=credentials=./sa-key.json \
          --namespace crossplane-system
        ```

        (Замените `./sa-key.json` на актуальный путь к вашему файлу ключей).

3.  **Создание `ProviderConfig` для Yandex Cloud:**

    *   `ProviderConfig` связывает провайдер Crossplane с вашими учетными данными и идентификаторами Yandex Cloud.
    *   Пример манифеста `provider-config.yaml`:

        ```yaml
        apiVersion: yandex-cloud.crossplane.io/v1alpha1
        kind: ProviderConfig
        metadata:
          name: default
        spec:
          folderId: <YOUR_YANDEX_CLOUD_FOLDER_ID>
          cloudId: <YOUR_YANDEX_CLOUD_CLOUD_ID>
          credentials:
            source: Secret
            secretRef:
              name: yandex-cloud-credentials
              namespace: crossplane-system
              key: credentials
        ```

    *   Замените `<YOUR_YANDEX_CLOUD_FOLDER_ID>` и `<YOUR_YANDEX_CLOUD_CLOUD_ID>` на актуальные значения из вашей панели управления Yandex Cloud.
    *   Применить манифест:

        ```bash
        kubectl apply -f provider-config.yaml
        ```

### 4. Развертывание приложения (VM с Nginx) через Argo CD

Вебинар демонстрирует развертывание HelmChart, который создает виртуальную машину (VM) в Yandex Cloud с Nginx.

1.  **Пример HelmChart для VM:**

    *   Будет выполнять: обновление пакетов, установку Nginx и UFW, открытие портов 80 и 22, запуск Firewall, добавление Nginx в автозапуск.
    *   `values.yaml` (пример):

        ```yaml
        vmName: my-nginx-vm
        zone: ru-central1-a
        resources:
          memory: 2G
          cores: 2
        imageId: fd80m5rnb5lsvj0s2k91 # ID образа Ubuntu 24.04 LTS
        diskSize: 15G
        subnetId: e9b56f8f-1c4b-4b2a-8b1a-2d4e7f8g0h1i # ID подсети в зоне ru-central1-a
        ```

2.  **Пример Argo CD Application манифеста:**

    Этот манифест используется для развертывания HelmChart в кластере Kubernetes через Argo CD.

    ```yaml
    apiVersion: argoproj.io/v1alpha1
    kind: Application
    metadata:
      name: nginx-vm
      namespace: argocd
    spec:
      project: default
      source:
        repoURL: https://github.com/your-repo/your-crossplane-gitops.git # URL вашего репозитория
        targetRevision: HEAD
        path: charts/nginx-vm # Путь к HelmChart в репозитории
      destination:
        server: https://kubernetes.default.svc
        namespace: crossplane-system # Неймспейс, где Crossplane будет создавать ресурсы
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
    ```

    *   **Добавить репозиторий в Argo CD:**

        ```bash
        argocd repo add https://github.com/your-repo/your-crossplane-gitops.git --ssh-private-key-path <PATH_TO_SSH_KEY> # Если приватный
        # Или
        argocd repo add https://github.com/your-repo/your-crossplane-gitops.git # Если публичный
        ```

    *   **Применить Argo CD Application:**

        ```bash
        kubectl apply -f nginx-vm-application.yaml
        ```

    *   Argo CD синхронизирует репозиторий, развертывает HelmChart, который в свою очередь создает CRD для Crossplane, и Crossplane создает VM в Yandex Cloud.
