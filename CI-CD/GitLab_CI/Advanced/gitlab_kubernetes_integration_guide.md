# Интеграция GitLab CI с Kubernetes

## Определения

**Интеграция GitLab с Kubernetes** — это процесс настройки взаимодействия между CI/CD-пайплайнами GitLab и кластером Kubernetes для автоматического развертывания, тестирования и управления приложениями.

Существует три основных подхода к интеграции:

1.  **"Push"-модель (управляемая CI)**: GitLab CI/CD пайплайн, используя инструменты командной строки (`kubectl`, `helm`), напрямую "проталкивает" (push) изменения в кластер. Это наиболее распространенный и гибкий подход.
2.  **"Pull"-модель (GitOps)**: Агент, установленный в кластере (например, ArgoCD), отслеживает Git-репозиторий с манифестами и "притягивает" (pull) изменения. GitLab CI отвечает только за сборку образов и обновление конфигурации в Git.
3.  **Встроенная интеграция (устарела)**: Нативный механизм интеграции GitLab, который **не рекомендуется** к использованию из-за высоких требований к правам доступа и низкой гибкости.

## Основные концепции

### Сравнение стратегий развертывания

| Стратегия | Принцип работы | Безопасность | Гибкость | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **Push-модель (`kubectl`)** | Пайплайн GitLab CI получает доступ к API-серверу Kubernetes и выполняет команды. | Требует безопасного хранения и передачи учетных данных в CI. | Высокая, полный контроль над процессом развертывания. | **Рекомендуется** для большинства сценариев. |
| **Pull-модель (GitOps)** | Агент в кластере синхронизирует состояние с Git-репозиторием. Пайплайн CI не имеет прямого доступа к кластеру. | Высокая, учетные данные не покидают пределы кластера. | Высокая, но требует строгого следования декларативному подходу. | **Рекомендуется** для зрелых процессов и повышения безопасности. |
| **Встроенная интеграция** | GitLab управляет ресурсами в кластере через свой UI и API. | Низкая, требует прав `cluster-admin`. | Низкая, конфликтует с существующими инструментами. | **Не рекомендуется**. |

### Проблемы классической "Push"-модели

Несмотря на популярность, "Push"-модель имеет фундаментальные недостатки, которые привели к появлению GitOps:

1.  **Рассинхронизация состояния (State Drift):** Истинное состояние кластера со временем отклоняется от того, что описано в Git.
    *   **Пример (Ручные изменения):** Инженер для срочного исправления применяет `kubectl patch` напрямую в кластере. Следующий запуск CI/CD пайплайна, не зная об этом изменении, перезатрет его, что может привести к повторному возникновению проблемы.

2.  **Недетерминизм и отсутствие идемпотентности:**
    *   **Mutable-теги:** Использование изменяемых тегов, таких как `latest`, является анти-паттерном. Невозможно гарантировать, какая именно версия кода работает в кластере.
    *   **Нестабильность сборки:** Повторная сборка из одного и того же коммита может дать бинарно разный результат из-за динамики зависимостей.

### Принципы "Pull"-модели (GitOps)

GitOps решает проблемы "Push"-модели, базируясь на следующих принципах. Для более глубокого изучения см. **[Обзор методологии GitOps](../../../GitOps/GitOps_overview.md)**.

1.  **Pull-модель вместо Push:**
    *   Пайплайн CI/CD **не имеет прямого доступа к кластеру**. Его ответственность — собрать артефакт (образ) и обновить конфигурацию в Git-репозитории манифестов.
    *   **Агент GitOps (ArgoCD, Flux)** внутри кластера "наблюдает" за репозиторием и "притягивает" изменения.

2.  **Иммутабельные артефакты:**
    *   Каждый собранный образ версионируется и неизменяем. В качестве тега используется хеш коммита (`CI_COMMIT_SHORT_SHA`) или дайджест образа.

3.  **Разделение репозиториев:**
    *   **Репозиторий приложения:** Содержит исходный код.
    *   **Репозиторий конфигурации:** Содержит Kubernetes-манифесты (Helm, Kustomize). Именно за ним следит GitOps-агент.

### Способы авторизации в "Push"-модели

Ключевой задачей является безопасное предоставление CI-задаче прав для выполнения команд в Kubernetes.

1.  **Переменная `KUBE_CONFIG`**
    *   **Принцип**: Содержимое файла `kubeconfig` сохраняется в виде защищенной CI/CD-переменной в GitLab. Runner использует эту переменную для аутентификации.
    *   **Плюсы**: Простота настройки.
    *   **Минусы**: Менее безопасно, так как токен доступа является долгоживущим. Требует сетевой доступности от Runner'а до API-сервера кластера.

2.  **GitLab Runner с Kubernetes Executor**
    *   **Принцип**: Runner устанавливается непосредственно в кластер Kubernetes. Для каждой CI-задачи создается отдельный Pod. Используя `ServiceAccount` Kubernetes, задача автоматически получает токен доступа с коротким сроком жизни.
    *   **Плюсы**: **Наиболее безопасный и идиоматичный способ.**
    *   Подробное сравнение executor-ов можно найти в [соответствующем руководстве](../gitlab_ci_runners_executors.md).

3.  **Техническая учетная запись в IdP**
    *   **Принцип**: Для CI/CD создается специальная учетная запись в корпоративном провайдере идентификации (LDAP, AD).
    *   **Применимость**: Крупные организации с централизованным управлением доступом.

4.  **OIDC/JWT-аутентификация**
    *   **Принцип**: Настраиваются доверительные отношения между Kubernetes и GitLab (как OIDC-провайдером). Кластер может валидировать временный JWT-токен (`CI_JOB_JWT_TOKEN`), который генерируется для каждой CI-задачи.
    *   **Статус**: Современный и безопасный подход (Workload Identity Federation).

## Практические сценарии

### Сценарий 1: Развертывание в "Push"-модели с Helm и Kubernetes Executor

Это рекомендуемый способ, сочетающий безопасность Kubernetes Executor и гибкость Helm.

1.  **Подготовьте кластер для Runner'а:**
    ```bash
    kubectl create ns gitlab-runner
    kubectl create sa gitlab-runner-sa -n gitlab-runner
    # В реальных проектах используйте гранулярные права вместо cluster-admin
    kubectl create clusterrolebinding gitlab-runner-admin --clusterrole=cluster-admin --serviceaccount=gitlab-runner:gitlab-runner-sa
    ```

2.  **Зарегистрируйте Runner** с executor'ом `kubernetes` и разрешите использование ServiceAccount в `config.toml`:
    ```toml
    [[runners]]
      executor = "kubernetes"
      [runners.kubernetes]
        namespace = "gitlab-runner"
        service_account_overwrite_allowed = ".*"
    ```

3.  **Настройте доступ к GitLab Container Registry:**
    *   Создайте **Deploy Token** (`Settings > Repository > Deploy Tokens`) с правом `read_registry`.
    *   Создайте секрет в Kubernetes:
        ```bash
        kubectl create secret docker-registry gitlab-registry \
          --docker-server=<ваш_gitlab_registry_url> \
          --docker-username=<имя_пользователя_deploy_token> \
          --docker-password=<пароль_deploy_token> \
          --namespace=<ваш_namespace>
        ```

4.  **Настройте `.gitlab-ci.yml`:**
    ```yaml
    stages: [deploy]

    deploy_to_prod:
      stage: deploy
      image: name: dwolf/helm-kubectl-docker:latest # Образ с kubectl и helm
      tags: [kubernetes] # Тег вашего runner'а
      variables:
        KUBERNETES_SERVICE_ACCOUNT_OVERWRITE: gitlab-runner-sa 
      script:
        # Автоматическая конфигурация kubectl с использованием токена ServiceAccount
        - kubectl config set-cluster local --server=https://kubernetes.default.svc --certificate-authority=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        - kubectl config set-context local --cluster=local
        - kubectl config set-credentials user --token=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
        - kubectl config use-context local --user=user
        
        # Развертывание с помощью Helm
        - helm upgrade --install my-app-release ./charts/my-app \
          --namespace production \
          --set image.tag=$CI_COMMIT_SHORT_SHA \
          --set image.pullSecrets[0].name=gitlab-registry
      rules:
        - if: '$CI_COMMIT_BRANCH == "main"'
    ```

### Сценарий 2: Развертывание в "Push"-модели с `kubectl apply` и `KUBE_CONFIG`

Этот способ проще для старта, но менее безопасен.

1.  **Создайте переменную `K8S_CONFIG` в GitLab CI/CD:**
    *   **Key:** `K8S_CONFIG`
    *   **Value:** `cat ~/.kube/config | base64 -w 0`
    *   **Flags:** `Protected`, `Masked`

2.  **Настройте `.gitlab-ci.yml`:**
    ```yaml
    deploy-k8s:
      stage: deploy
      image: name: alpine:3.19
      variables:
        KUBECONFIG: /tmp/kubeconfig
        MANIFEST_FOLDER: "k8s"
      script:
        # Аутентификация
        - echo "$K8S_CONFIG" | base64 -d > $KUBECONFIG
        
        # Установка инструментов и развертывание
        - apk update && apk add gettext
        - wget -q -O /usr/local/bin/kubectl https://storage.googleapis.com/kubernetes-release/release/v1.26.0/bin/linux/amd64/kubectl && chmod +x /usr/local/bin/kubectl
        - >-
           for MANIFEST in $MANIFEST_FOLDER/*; do
            envsubst < $MANIFEST | kubectl apply -n $CI_ENVIRONMENT_NAME -f -;
          done
      rules:
        - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    ```
    *Примечание: `envsubst` используется для подстановки переменных окружения (например, `$CI_COMMIT_SHA`) в манифесты.*

### Сценарий 3: Переход на "Pull"-модель (GitOps)

Для реализации этой модели используется связка из CI-пайплайна и GitOps-агента.

*   **Ответственность GitLab CI**:
    1.  Собрать Docker-образ с тегом `$CI_COMMIT_SHA`.
    2.  Сделать коммит в **репозиторий конфигурации**, обновив тег образа в `values.yaml` или Kustomize-манифесте.

*   **Ответственность GitOps-агента (например, ArgoCD)**:
    1.  Обнаружить изменение в репозитории конфигурации.
    2.  Автоматически применить изменения в кластере.

Подробные инструкции по настройке specific-инструментов находятся в соответствующих разделах:
- **[Обзор методологии GitOps](../../../GitOps/GitOps_overview.md)**
- **[Пример реализации с помощью ArgoCD](../../../GitOps/ArgoCD.md)**
