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

2. **GitLab Runner с Kubernetes Executor**
    * **Принцип**: Runner устанавливается непосредственно в кластер Kubernetes. Для каждой CI-задачи создается отдельный Pod. Используя `ServiceAccount` Kubernetes, задача автоматически получает токен доступа с коротким сроком жизни.
    * **Плюсы**: **Наиболее безопасный и идиоматичный способ.**
    * См. **[Обзор Runner'ов и Executor'ов](gitlab_ci_runners_executors.md)** для подробного сравнения.

3. **OIDC/JWT-аутентификация**
    * **Принцип**: Настраиваются доверительные отношения между Kubernetes и GitLab (как OIDC-провайдером). Кластер может валидировать временный JWT-токен (`CI_JOB_JWT_TOKEN`), который генерируется для каждой CI-задачи.
    * **Статус**: Современный и безопасный подход, также известный как **[Workload Identity Federation](https://docs.gitlab.com/ee/ci/secrets/authenticate_with_oidc.html)**.

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
          --set image.pullSecrets[0].name=gitlab-registry
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

Подробные инструкции по настройке specific-инструментов находятся в соответствующих разделах:

* **[Обзор методологии GitOps](../../../GitOps/GitOps_overview.md)**
* **[Пример реализации с помощью ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md)**

## Дополнительная информация

### Лучшие практики

* **Начинайте с Push, развивайтесь до Pull:** Для большинства проектов `Push`-модель с Kubernetes Executor'ом является отличной отправной точкой. По мере роста сложности и требований к безопасности рассмотрите переход на `Pull`-модель (GitOps).
* **Гранулярные права (RBAC):** Никогда не используйте `cluster-admin` для CI/CD в production. Создавайте `Role` и `RoleBinding` с минимально необходимыми правами для каждого приложения (`helm install` требует прав на создание, обновление и чтение многих типов ресурсов).
* **Иммутабельные теги:** Всегда используйте неизменяемые теги для Docker-образов, такие как `CI_COMMIT_SHORT_SHA` или `CI_COMMIT_TAG`. Использование `latest` является анти-паттерном.
* **Изоляция Runner'ов:** Запускайте Runner'ы в выделенном, изолированном `namespace` с настроенными `NetworkPolicy` и `ResourceQuota`.

### Устранение неполадок

* **`ImagePullBackOff`**: Самая частая ошибка. Проверьте, что `imagePullSecrets` создан в правильном `namespace` и указан в `ServiceAccount` или непосредственно в манифесте `Deployment`. Убедитесь, что `Deploy Token` имеет права на чтение репозитория.
* **`Error: pods is forbidden`** (или другой ресурс): `ServiceAccount`, используемый задачей, не имеет необходимых RBAC-прав. Проверьте `Role` и `RoleBinding`. Используйте `kubectl auth can-i ... --as=system:serviceaccount:<ns>:<sa>` для отладки.
* **`Connection timed out`**: Runner не может связаться с API-сервером Kubernetes. Проверьте сетевые политики (`NetworkPolicy`), правила файрвола и корректность адреса API-сервера.
