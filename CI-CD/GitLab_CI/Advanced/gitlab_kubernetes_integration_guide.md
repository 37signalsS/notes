# Интеграция GitLab CI с Kubernetes

## Определения

**Интеграция GitLab с Kubernetes** — это процесс настройки взаимодействия между CI/CD-пайплайнами GitLab и кластером Kubernetes для автоматического развертывания, тестирования и управления приложениями.

Существует три основных подхода к интеграции:

1. **"Push"-модель (управляемая CI)**: GitLab CI/CD пайплайн, используя инструменты командной строки (`kubectl`, `helm`), напрямую "проталкивает" (push) изменения в кластер. Это наиболее распространенный и гибкий подход.
2. **"Pull"-модель (GitOps)**: Агент, установленный в кластере (например, ArgoCD), отслеживает Git-репозиторий с манифестами и "притягивает" (pull) изменения. GitLab CI отвечает только за сборку образов и обновление конфигурации в Git.
3. **Встроенная интеграция (устарела)**: Нативный механизм интеграции GitLab, который **не рекомендуется** к использованию из-за высоких требований к правам доступа и низкой гибкости.

## Основные концепции

### Сравнение стратегий развертывания

| Стратегия | Принцип работы | Безопасность | Гибкость | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **Push-модель (`kubectl`)** | Пайплайн GitLab CI получает доступ к API-серверу Kubernetes и выполняет команды. | Требует безопасного хранения и передачи учетных данных в CI. | Высокая, полный контроль над процессом развертывания. | **Рекомендуется** для большинства сценариев. |
| **Pull-модель (GitOps)** | Агент в кластере синхронизирует состояние с Git-репозиторием. Пайплайн CI не имеет прямого доступа к кластеру. | Высокая, учетные данные не покидают пределы кластера. | Высокая, но требует строгого следования декларативному подходу. | **Рекомендуется** для зрелых процессов и повышения безопасности. |
| **Встроенная интеграция** | GitLab управляет ресурсами в кластере через свой UI и API. | Низкая, требует прав `cluster-admin`. | Низкая, конфликтует с существующими инструментами. | **Не рекомендуется**. |

### Способы авторизации в "Push"-модели

Ключевой задачей является безопасное предоставление CI-задаче прав для выполнения команд в Kubernetes.

1. **Переменная `KUBE_CONFIG`**
    * **Принцип**: Содержимое файла `kubeconfig` сохраняется в виде защищенной CI/CD-переменной в GitLab. Runner использует эту переменную для аутентификации.
    * **Минусы**: Менее безопасно, так как токен доступа является долгоживущим. Требует сетевой доступности от Runner'а до API-сервера кластера.
    * **Статус**: Не рекомендуется для production-окружений.

2. **GitLab Runner с Kubernetes Executor**
    * **Принцип**: Runner устанавливается непосредственно в кластер Kubernetes. Для каждой CI-задачи создается отдельный Pod. Используя `ServiceAccount` Kubernetes, задача автоматически получает токен доступа с коротким сроком жизни.
    * **Плюсы**: **Наиболее безопасный и идиоматичный способ.**
    * См. **[Обзор Runner'ов и Executor'ов](gitlab_ci_runners_executors.md)** для подробного сравнения.

3. **OIDC/JWT-аутентификация (рекомендуется)**
    * **Принцип**: Настраиваются доверительные отношения между Kubernetes и GitLab (как OIDC-провайдером). Кластер может валидировать временный JWT-токен (`CI_JOB_JWT_TOKEN` или `CI_JOB_JWT_V2`), который генерируется для каждой CI-задачи.
    * **Статус**: Современный и безопасный подход, также известный как **[Workload Identity Federation](https://docs.gitlab.com/ee/ci/secrets/authenticate_with_oidc.html)**.
    * **Преимущества**:
      * Временные токены (срок жизни — длительность задачи)
      * Нет необходимости хранить секреты в GitLab
      * Гранулярный контроль доступа через ServiceAccount
      * Аудит всех действий в Kubernetes

    * **Настройка в Kubernetes:**

      ```bash
      # 1. Создаём ServiceAccount с аннотациями для Workload Identity
      kubectl create -f - <<EOF
      apiVersion: v1
      kind: ServiceAccount
      metadata:
        name: gitlab-deploy-sa
        namespace: production
        annotations:
          # Для Yandex Cloud (через IAM)
          iam.yandexcloud.net/service-account-id: sa-xxxxxxxxxxxxxxxxx
          # Для локального аринта (если используется Vault CSI)
          secrets-store.csi.k8s.io/used: "true"
      EOF
      
      # 2. Создаём Role с минимальными правами
      kubectl create -f - <<EOF
      apiVersion: rbac.authorization.k8s.io/v1
      kind: Role
      metadata:
        name: gitlab-deploy-role
        namespace: production
      rules:
      - apiGroups: ["apps"]
        resources: ["deployments"]
        verbs: ["get", "list", "update", "patch"]
      - apiGroups: [""]
        resources: ["services", "configmaps"]
        verbs: ["get", "list", "update", "patch"]
      EOF
      
      # 3. Привязываем ServiceAccount к Role
      kubectl create -f - <<EOF
      apiVersion: rbac.authorization.k8s.io/v1
      kind: RoleBinding
      metadata:
        name: gitlab-deploy-binding
        namespace: production
      subjects:
      - kind: ServiceAccount
        name: gitlab-deploy-sa
        namespace: production
      roleRef:
        kind: Role
        name: gitlab-deploy-role
        apiGroup: rbac.authorization.k8s.io
      EOF
      ```

## Практические сценарии

### Сценарий 1: Развертывание в "Push"-модели с Helm и Kubernetes Executor

Это рекомендуемый способ, сочетающий безопасность Kubernetes Executor и гибкость Helm.

1. **Подготовьте кластер для Runner'а:**

    ```bash
    # Создаем отдельный namespace для Runner'а для изоляции
    kubectl create ns gitlab-runner
    # Создаем ServiceAccount, который будет использовать Pod с Runner'ом
    kubectl create sa gitlab-runner-sa -n gitlab-runner
    # ВАЖНО: В реальных проектах используйте гранулярные права вместо cluster-admin
    # Привязываем ServiceAccount к роли cluster-admin для простоты примера
    kubectl create clusterrolebinding gitlab-runner-admin --clusterrole=cluster-admin --serviceaccount=gitlab-runner:gitlab-runner-sa
    ```

2. **Зарегистрируйте Runner** с executor'ом `kubernetes` и разрешите использование ServiceAccount в `config.toml`. Подробнее в **[руководстве по Runner'ам](gitlab_ci_runners_executors.md)**.

3. **Настройте доступ к GitLab Container Registry:**
    * Создайте **Deploy Token** (`Settings > Repository > Deploy Tokens`) с правом `read_registry`.
    * Создайте секрет в Kubernetes, который поды будут использовать для скачивания образов:

        ```bash
        kubectl create secret docker-registry gitlab-registry \
          --docker-server=<ваш_gitlab_registry_url> \
          --docker-username=<имя_пользователя_deploy_token> \
          --docker-password=<пароль_deploy_token> \
          --namespace=<ваш_namespace>
        ```

4. **Настройте `.gitlab-ci.yml`:**

    ```yaml
    deploy_to_prod:
      stage: deploy
      image: name: dwolf/helm-kubectl-docker:latest # Образ с kubectl и helm
      tags: [kubernetes] # Тег вашего runner'а, работающего в K8s
      variables:
        # Указываем, какой ServiceAccount использовать для этой задачи
        KUBERNETES_SERVICE_ACCOUNT_OVERWRITE: gitlab-runner-sa 
      script:
        # Аутентификация в кластере происходит автоматически через токен ServiceAccount
        - echo "Deploying to production namespace..."
        
        # Развертывание с помощью Helm
        - helm upgrade --install my-app-release ./charts/my-app \
          --namespace production \
          --set image.tag=$CI_COMMIT_SHORT_SHA \
          --set image.pullSecrets[0](name=gitlab-registry
      rules:
        - if: '$CI_COMMIT_BRANCH == "main"'
    ```

### Сценарий 2: Переход на "Pull"-модель (GitOps)

Для реализации этой модели используется связка из CI-пайплайна и GitOps-агента.

* **Ответственность GitLab CI**:
    1. Собрать Docker-образ с тегом `$CI_COMMIT_SHA`.
    2. Сделать коммит в **репозиторий конфигурации**, обновив тег образа в `values.yaml` или Kustomize-манифесте.

* **Ответственность GitOps-агента (например, ArgoCD)**:
    1. Обнаружить изменение в репозитории конфигурации.
    2. Автоматически применить изменения в кластере.

Подробные инструкции по настройке инструментов — в **[обзоре методологии GitOps](../../../GitOps/GitOps_overview.md)** и **[руководстве по ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md)**.

## Дополнительная информация

### Лучшие практики

Для большинства проектов рекомендуется начинать с **`Push`-модели**, используя Kubernetes Executor, и по мере роста требований к безопасности переходить к **`Pull`-модели (GitOps)**. Ключевым аспектом безопасности является использование гранулярных прав RBAC — никогда не предоставляйте права `cluster-admin` для задач CI/CD в production. Вместо этого создавайте `Role` и `RoleBinding` с минимально необходимыми правами для каждого приложения.

При работе с образами всегда используйте **иммутабельные теги** (`CI_COMMIT_SHORT_SHA`, `CI_COMMIT_TAG`), так как `latest` является анти-паттерном. Изолируйте Runner'ы в отдельных `namespace` с настроенными `NetworkPolicy` и `ResourceQuota`. Для аутентификации предпочтительным современным методом является **OIDC (Workload Identity Federation)**, который позволяет использовать временные токены вместо долгоживущих секретов. Также рекомендуется включать аудит действий ServiceAccount в Kubernetes для отслеживания всех изменений.

### Устранение неполадок

При возникновении проблем в первую очередь стоит проверить права доступа и сетевые настройки. Ошибка **`ImagePullBackOff`** обычно связана с отсутствием или неверной конфигурацией `imagePullSecrets` в нужном `namespace`. Ошибки вида **`Error: pods is forbidden`** указывают на недостаточные RBAC-права у `ServiceAccount` — их можно отладить с помощью `kubectl auth can-i`. Если же Runner не может связаться с API-сервером (`Connection timed out`), проверьте `NetworkPolicy` и правила файрвола.

Более подробную информацию о настройке можно найти в следующих документах:

* **[Руководство по GitLab Runners](./gitlab_ci_runners_executors.md)** — детальная конфигурация исполнителей.
* **[Концепции окружений и развертываний](../Concepts/environments_and_deployments.md)** — управление `environment` и `deployment`.
