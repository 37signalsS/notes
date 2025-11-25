# Практическое руководство: Динамические окружения (Review Apps) с Kubernetes

Это руководство демонстрирует полный цикл настройки и использования динамических окружений (Review Apps) в GitLab CI для развертывания приложений в Kubernetes. Мы будем использовать кастомный "оператор", который будет управлять созданием и удалением этих временных сред.

См. также:
*   [Управление окружениями и откат изменений в GitLab CI](./gitlab_ci_environments_and_rollbacks.md)
*   [Развертывание в Kubernetes с помощью GitLab CI и Helm](./gitlab_ci_kubernetes_helm_deploy.md)
*   [Стратегии интеграции GitLab CI с Kubernetes](./gitlab_kubernetes_integration_strategies.md)

---

## Часть 1: Подготовка кластера и развертывание Оператора

Прежде чем наше приложение сможет использовать динамические окружения, нам нужно развернуть в кластере сам сервис, который будет ими управлять — Оператор.

### 1.1. Подготовка ServiceAccount и получение токена
Оператору нужен доступ к API Kubernetes. Создадим для него `ServiceAccount` и `ClusterRoleBinding`.

1.  **Создайте Namespace и ServiceAccount:**
    ```bash
    kubectl create namespace users
    kubectl create serviceaccount deploy-admin -n users
    kubectl create clusterrolebinding deploy-admin-binding --clusterrole=cluster-admin --serviceaccount=users:deploy-admin
    ```
2.  **Получите и расшифруйте токен:**
    ```bash
    # Получаем имя секрета, связанного с ServiceAccount
    SECRET_NAME=$(kubectl get sa deploy-admin -n users -o jsonpath='{.secrets[0].name}')
    # Извлекаем и декодируем токен из секрета
    KUBE_TOKEN=$(kubectl get secret ${SECRET_NAME} -n users -o jsonpath='{.data.token}' | base64 --decode)
    echo $KUBE_TOKEN
    ```
    Сохраните этот токен.

### 1.2. Настройка и запуск пайплайна Оператора
1.  **Форкните репозиторий оператора** в свой GitLab.
2.  Перейдите в `Settings > CI/CD > Variables` форкнутого проекта.
3.  **Добавьте переменные:**
    *   `KUBE_URL`: URL вашего API-сервера Kubernetes.
    *   `KUBE_TOKEN`: Токен, полученный на предыдущем шаге. Пометьте его как **Masked** и **Protected**.
4.  Запустите пайплайн для ветки `main` вручную (`CI/CD > Pipelines > Run pipeline`), чтобы развернуть оператор в кластере. Убедитесь, что все задачи успешно выполнены.

## Часть 2: Настройка основного приложения

Теперь настроим проект нашего приложения для работы с оператором.

1.  **Форкните репозиторий приложения** в свою группу GitLab.
2.  **Создайте Access Token для GitLab API:**
    *   Перейдите в `User Settings > Access Tokens`.
    *   Создайте токен с правами (scope) `api`.
    *   **Сохраните этот токен**, он понадобится для шифрования.
3.  **Создайте Deploy Token для Container Registry:**
    *   В проекте приложения перейдите в `Settings > Repository > Deploy Tokens`.
    *   Создайте токен с правами `read_registry` и `write_registry`.
    *   **Сохраните имя пользователя и пароль** токена.
4.  **Зашифруйте секреты (опционально, но рекомендуется):**
    Для безопасного хранения токенов в переменных CI/CD их можно предварительно зашифровать с помощью `ansible-vault`.
    ```bash
    # Установите ansible, если не установлен
    # sudo apt-get install ansible
    
    # Зашифруйте GitLab API токен
    ansible-vault encrypt_string 'ВАШ_API_ACCESS_TOKEN' --name 'GITLAB_API_TOKEN_CRYPTED'

    # Зашифруйте пароль от Deploy Token
    ansible-vault encrypt_string 'ВАШ_DEPLOY_TOKEN_ПАРОЛЬ' --name 'CR_DEPLOY_PASSWORD_CRYPTED'
    ```
    Скопируйте полученные зашифрованные блоки.

5.  **Настройте переменные CI/CD в проекте приложения:**
    Перейдите в `Settings > CI/CD > Variables` и добавьте следующие переменные:
    *   `KUBE_URL`: URL API-сервера Kubernetes.
    *   `KUBE_TOKEN`: Токен ServiceAccount из Части 1.
    *   `GITLAB_API_TOKEN_CRYPTED`: Зашифрованный токен GitLab API.
    *   `CR_DEPLOY_PASSWORD_CRYPTED`: Зашифрованный пароль Deploy Token.
    *   `CR_DEPLOY_USER`: Имя пользователя Deploy Token (нешифрованное).

## Часть 3: Жизненный цикл Review App

1.  **Создайте feature-ветку** в репозитории вашего приложения (например, `feature/my-cool-feature`).
2.  **Внесите изменения** в код.
3.  **Создайте Merge Request (MR)** из вашей feature-ветки в `main`.

    *   **Важно:** Убедитесь, что `target branch` (целевая ветка) указывает на `main` вашего форка, а не родительского репозитория.

4.  **Автоматический запуск пайплайна:**
    *   Создание MR автоматически запустит пайплайн, который включает задачу `deploy_review`.
    *   Эта задача свяжется с оператором в Kubernetes, который создаст новое, изолированное окружение для вашей ветки.
    *   В виджете Merge Request появится ссылка на **"View app"**.

5.  **Просмотр и тестирование:**
    *   Перейдите по ссылке "View app", чтобы открыть развернутое приложение и протестировать изменения. URL будет уникальным для вашей ветки.

6.  **Остановка окружения:**
    *   Когда окружение больше не нужно (например, после слияния MR), перейдите в `Deployments > Environments`.
    *   Найдите ваше динамическое окружение (например, `review/feature-my-cool-feature`).
    *   Нажмите кнопку **Stop** (■).
    *   Это действие запустит задачу, определенную в `environment:on_stop` (в нашем случае `stop_review_app`), которая выполнит скрипт для удаления всех ресурсов, связанных с этим окружением.

Этот процесс позволяет эффективно тестировать изменения в изолированных, production-like средах, значительно повышая надежность и скорость разработки.
