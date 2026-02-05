# Crossplane: Управление облачной инфраструктурой через Kubernetes

## Определения

**Crossplane** — это решение класса "инфраструктура как код" (IaC) с открытым исходным кодом, которое расширяет Kubernetes API для управления облачной инфраструктурой от различных провайдеров. Он устанавливается в кластер Kubernetes и позволяет определять и настраивать облачные ресурсы (такие как базы данных, сети, виртуальные машины) с помощью декларативных YAML-манифестов, так же, как и нативные ресурсы Kubernetes.

## Базовые концепции

### Ключевые возможности

*   **Унифицированное управление:** Позволяет командам использовать знакомый синтаксис и инструменты Kubernetes (`kubectl`, GitOps) для управления как приложениями, так и инфраструктурой.
*   **Представление облачных сервисов как CRD:** После установки провайдера Crossplane автоматически создает Custom Resource Definitions (CRD) для соответствующих облачных сервисов, делая их нативными для Kubernetes.
*   **Интеграция с GitOps:** Полностью совместим с инструментами GitOps, такими как Argo CD и Flux, что позволяет реализовать полный цикл управления инфраструктурой через Git.
*   **Политики управления:** Поддерживает нативные механизмы безопасности Kubernetes, включая RBAC и политики Open Policy Agent (OPA), для гранулярного контроля доступа к облачным ресурсам.
*   **Расширяемость:** Поддерживает множество облачных провайдеров (AWS, Azure, GCP, Yandex Cloud и др.) и позволяет создавать собственные провайдеры.

### Архитектура

Процесс работы Crossplane выглядит следующим образом:
1.  Пользователь или CI/CD-система применяет YAML-манифест с описанием облачного ресурса в кластере (`kubectl apply -f ...`).
2.  Манифест сохраняется в базе данных etcd как кастомный ресурс Kubernetes.
3.  **Crossplane Core** (набор контроллеров) обнаруживает создание или изменение этого ресурса.
4.  На основе `ProviderConfig`, который содержит учетные данные для доступа к облаку, Crossplane Core взаимодействует с API соответствующего облачного провайдера.
5.  Облачный сервис создается, обновляется или удаляется на стороне провайдера.
6.  Crossplane Core получает от API провайдера статус операции и обновляет поле `status` кастомного ресурса в Kubernetes, обеспечивая обратную связь.

### Интеграция с GitOps и Argo CD

Crossplane идеально вписывается в методологию GitOps. В этой парадигме Git-репозиторий становится единым источником правды как для приложений, так и для инфраструктуры. **Argo CD** выступает в роли оператора, который отслеживает изменения в Git, обнаруживает новые или измененные манифесты ресурсов Crossplane и применяет их в кластере. Затем Crossplane берет на себя задачу по приведению реальной облачной инфраструктуры в соответствие с этими манифестами.

## Практические сценарии

### Установка и настройка Crossplane с провайдером Yandex Cloud

В этом примере рассматривается развертывание Crossplane в кластере Minikube и его настройка для работы с Yandex Cloud.

#### Предварительные требования

*   **Кластер Kubernetes:** Локальный (Minikube, Kind) или облачный.
*   **Helm:** Установлен и настроен.
*   **kubectl:** Установлен и настроен для работы с вашим кластером.
*   **Argo CD:** (Опционально) Развернут в кластере для реализации GitOps-подхода.

#### Установка Crossplane и его CLI

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
    Убедитесь, что все поды в `crossplane-system` перешли в состояние `Running`:
    ```bash
    kubectl get pods -n crossplane-system
    ```

4.  **Установка Crossplane CLI (`crossplane`):**
    Скачайте бинарный файл для вашей ОС с [официальной страницы релизов](https://github.com/crossplane/crossplane/releases) и поместите его в директорию, доступную в `PATH` (например, `/usr/local/bin`).

#### Установка и конфигурация провайдера

1.  **Установка провайдера Yandex Cloud:**
    Используйте Crossplane CLI для установки пакета провайдера. Рекомендуется использовать последнюю доступную версию.
    ```bash
    crossplane xpkg install provider crossplane/provider-yandex-cloud:v0.1.0 # Пример версии
    ```

2.  **Проверка установленных CRD:**
    После установки провайдера в кластере появятся новые типы ресурсов.
    ```bash
    kubectl get crd | grep yandex-cloud.crossplane.io
    ```

3.  **Создание сервисного аккаунта в Yandex Cloud:**
    *   В консоли Yandex Cloud перейдите в **Identity and Access Management** -> **Сервисные аккаунты**.
    *   Создайте аккаунт (например, `crossplane-s-account`) с ролью `editor` на ваш каталог.
    *   Создайте **авторизованный ключ** для этого аккаунта и скачайте JSON-файл с ключами.

4.  **Создание секрета с учетными данными:**
    Создайте секрет Kubernetes, который будет содержать скачанный JSON-ключ. Crossplane будет использовать его для аутентификации в Yandex Cloud.
    ```bash
    kubectl create secret generic yandex-cloud-credentials \
      --from-file=credentials=./sa-key.json \
      --namespace crossplane-system
    ```
    *Замените `./sa-key.json` на путь к вашему файлу.*

5.  **Настройка `ProviderConfig`:**
    Этот ресурс связывает провайдер с учетными данными. Создайте файл `provider-config.yaml`:
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
    *Замените `<...>` на ваши реальные `folderId` и `cloudId`.*
    Примените манифест:
    ```bash
    kubectl apply -f provider-config.yaml
    ```

### Развертывание VM с Nginx через GitOps

Этот сценарий демонстрирует, как с помощью Argo CD и Crossplane развернуть виртуальную машину в Yandex Cloud.

1.  **Подготовка Git-репозитория с Helm-чартом:**
    В вашем Git-репозитории создайте Helm-чарт, который описывает ресурс `ComputeInstance` из CRD провайдера Yandex Cloud.
    *   **`templates/vm.yaml` (фрагмент):**
        ```yaml
        apiVersion: compute.yandex-cloud.crossplane.io/v1alpha1
        kind: ComputeInstance
        metadata:
          name: {{ .Values.vmName }}
        spec:
          forProvider:
            folderId: <YOUR_YANDEX_CLOUD_FOLDER_ID>
            zone: {{ .Values.zone }}
            # ... другие параметры ...
        ```
    *   **`values.yaml`:**
        ```yaml
        vmName: my-nginx-vm
        zone: ru-central1-a
        resources:
          memory: 2G
          cores: 2
        imageId: fd80m5rnb5lsvj0s2k91 # ID образа Ubuntu 24.04 LTS
        diskSize: 15G
        subnetId: e9b56f8f-1c4b-4b2a-8b1a-2d4e7f8g0h1i # ID подсети
        ```

2.  **Создание `Application` в Argo CD:**
    Создайте манифест `Application` для Argo CD, который будет отслеживать ваш репозиторий.
    ```yaml
    apiVersion: argoproj.io/v1alpha1
    kind: Application
    metadata:
      name: nginx-vm-from-crossplane
      namespace: argocd
    spec:
      project: default
      source:
        repoURL: https://github.com/your-repo/your-crossplane-gitops.git # URL вашего репозитория
        targetRevision: HEAD
        path: charts/nginx-vm # Путь к Helm-чарту
      destination:
        server: https://kubernetes.default.svc
        namespace: default # Неймспейс для развертывания ресурсов
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
    ```

3.  **Синхронизация:**
    После применения манифеста `Application` Argo CD начнет синхронизацию, применит Helm-чарт в кластере, что приведет к созданию кастомного ресурса `ComputeInstance`. Контроллер Crossplane обнаружит этот ресурс и создаст виртуальную машину в Yandex Cloud в соответствии с заданными параметрами.

## Дополнительная информация

### Сравнение с Terraform

| Характеристика            | Crossplane                                 | Terraform                                        |
| :------------------------ | :----------------------------------------- | :----------------------------------------------- |
| **Среда выполнения**      | Выполняется как контроллер внутри Kubernetes | Выполняется как CLI-инструмент с любого хоста      |
| **Управление состоянием** | Состояние инфраструктуры хранится в etcd Kubernetes | Требует настройки внешнего хранилища (S3, Consul) для хранения state-файла |
| **Модель выполнения**     | Непрерывная сверка (reconciliation loop)   | Выполнение по запросу (`plan`, `apply`)          |
| **Безопасность**          | Интегрирован с RBAC и политиками Kubernetes (OPA) | Требует отдельных решений для управления доступом (например, Vault) |
| **Интеграция с GitOps**   | Нативная (Argo CD, Flux)                   | Требует дополнительных инструментов и скриптов-оберток |
