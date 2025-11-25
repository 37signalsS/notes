# Развертывание в Kubernetes с помощью GitLab CI и Helm

Это руководство описывает процесс автоматического развертывания приложения в кластер Kubernetes с использованием Helm из пайплайна GitLab CI. Данный подход является логическим завершением цикла CI/CD, переводя артефакт (Docker-образ) из Container Registry в работающее приложение в продуктивной среде.

См. также:
*   [Практическое руководство: CI/CD пайплайн для Docker-приложений в GitLab](./gitlab_ci_docker_build_test_pipeline.md)
*   [Обзор Ansible](../Ansible/ansible_overview.md) (для сравнения подходов к развертыванию)

## 1. Предварительная подготовка

Перед настройкой развертывания необходимо выполнить несколько условий:
1.  **Работающий кластер Kubernetes:** У вас должен быть доступ к кластеру.
2.  **Helm-чарт:** Ваше приложение должно быть упаковано в Helm-чарт, который описывает все необходимые ресурсы Kubernetes (Deployment, Service, Ingress и т.д.). Обычно чарт находится в директории `.<helm_chart_name>/` или `charts/` в корне проекта.
3.  **Подготовка кластера:** Иногда требуется предварительная настройка кластера (создание ServiceAccount, Namespace и т.д.), которая может выполняться отдельным скриптом.

## 2. Шаг 1: Настройка доступа к Kubernetes из GitLab CI

GitLab Runner'у необходим безопасный доступ к API вашего кластера Kubernetes.

1.  **Получите адрес API и токен доступа:**
    *   Адрес API-сервера можно узнать командой `kubectl cluster-info`.
    *   Токен доступа для ServiceAccount, который будет использоваться для развертывания, можно получить из соответствующего секрета в Kubernetes.
2.  **Сохраните учетные данные в переменных GitLab CI:**
    *   Перейдите в `Settings > CI/CD > Variables` вашего проекта.
    *   Создайте переменную `KUBE_URL` и вставьте в нее адрес вашего Kubernetes API.
    *   Создайте переменную `KUBE_TOKEN`. Вставьте в нее токен доступа. **Обязательно** пометьте эту переменную как **"Protected"** (защищенная) и **"Masked"** (маскированная) для безопасности.

## 3. Шаг 2: Настройка доступа Kubernetes к GitLab Container Registry

Чтобы кластер Kubernetes мог скачивать Docker-образы из вашего приватного GitLab Container Registry, ему нужен секрет типа `docker-registry`.

1.  **Создайте Deploy Token в GitLab:**
    *   Перейдите в `Settings > Repository > Deploy Tokens`.
    *   Создайте новый токен. Дайте ему имя (например, `k8s-image-pull-token`).
    *   Предоставьте ему права (scope) **`read_registry`**.
    *   Сохраните сгенерированные **имя пользователя (username)** и **пароль (token)**. Этот токен нельзя будет посмотреть снова.

2.  **Создайте секрет в Kubernetes:**
    Выполните на своей локальной машине или в терминале с доступом к кластеру следующую команду, подставив полученные на предыдущем шаге данные:

    ```bash
    kubectl create secret docker-registry gitlab-registry \
      --docker-server=<ваш_gitlab_registry_url> \
      --docker-username=<имя_пользователя_deploy_token> \
  --docker-password=<пароль_deploy_token> \
      --namespace=<ваш_namespace>
    ```

3.  **Укажите `imagePullSecrets` в Helm-чарте:**
    Убедитесь, что в вашем Helm-чарте (например, в файле `values.yaml` или непосредственно в шаблоне Deployment) указано использование этого секрета:
    ```yaml
    image:
      repository: registry.example.com/group/project
      tag: latest
      pullPolicy: IfNotPresent
      # Указываем Kubernetes использовать наш секрет для скачивания образов
      pullSecrets:
        - name: gitlab-registry 
    ```

## 4. Шаг 3: Настройка `.gitlab-ci.yml` для развертывания

Добавьте новую стадию `deploy` и соответствующую задачу.

```yaml
stages:
  - build
  - test
  - push
  - deploy # Новая стадия развертывания

# ... (предыдущие стадии build, test, push)

deploy_to_prod:
  stage: deploy
  # Используем образ, содержащий kubectl и helm
  image: 
    name: registry.example.com/path/to/kube-helm-image:latest
  environment:
    # Указываем, что это развертывание в окружение 'production'
    name: production
    url: https://app.$CI_PROJECT_NAMESPACE.example.com # URL, где будет доступно приложение
  script:
    - echo "Deploying to Kubernetes..."
    # 1. Настройка контекста kubectl для подключения к кластеру
    - kubectl config set-cluster k8s --server="$KUBE_URL" --insecure-skip-tls-verify=true
    - kubectl config set-credentials gitlab --token="$KUBE_TOKEN"
    - kubectl config set-context default --cluster=k8s --user=gitlab
    - kubectl config use-context default
    
    # 2. Развертывание или обновление с помощью Helm
    - helm upgrade --install \
      --namespace production \
      --set image.tag=$CI_COMMIT_SHORT_SHA \
      --set ingress.host=app.$CI_PROJECT_NAMESPACE.example.com \
      my-app-release \
      ./<путь_к_чарту>

  rules:
    # Развертываем только из ветки main
    - if: '$CI_COMMIT_BRANCH == "main"'
```

### Пояснения к задаче `deploy_to_prod`:

*   **`image`**: Для выполнения команд `kubectl` и `helm` требуется специальный Docker-образ, в котором они установлены. Вы можете создать свой или использовать готовый.
*   **`environment`**: Эта директива позволяет отслеживать развертывания в GitLab. В разделе **Deployments > Environments** вы увидите статус вашего окружения `production` и ссылку на него (`url`).
*   **`script`**:
    1.  **Настройка `kubectl`**: Первые четыре команды настраивают `kubectl` внутри CI-задачи для аутентификации в вашем кластере, используя переменные `KUBE_URL` и `KUBE_TOKEN`, которые мы ранее сохранили.
    2.  **`helm upgrade --install`**: Это основная команда для развертывания.
        *   `--install`: Если релиза с таким именем нет, он будет создан. Если есть — обновлен.
        *   `--namespace`: Указывает namespace в Kubernetes для развертывания.
        *   `--set image.tag=$CI_COMMIT_SHORT_SHA`: Переопределяет параметр `image.tag` в `values.yaml` на короткий хеш коммита. Это гарантирует, что будет развернута именно та версия образа, которая была собрана в текущем пайплайне.
        *   `--set ingress.host=...`: Динамически задает хост для Ingress, чтобы приложение было доступно по правильному URL.
        *   `my-app-release`: Имя релиза в Helm.
        *   `./<путь_к_чарту>`: Путь к директории с вашим Helm-чартом.
*   **`rules`**: Ограничивает запуск этой задачи только для ветки `main`, чтобы предотвратить случайное развертывание в продакшен из feature-веток.

## 5. Проверка развертывания

После успешного выполнения пайплайна:
1.  Перейдите в раздел **Deployments > Environments** в вашем проекте GitLab.
2.  Найдите окружение `production` и нажмите на кнопку "Open" (▶), чтобы перейти по URL, указанному в `environment:url`.
3.  Вы должны увидеть ваше работающее приложение. (Иногда может потребоваться режим "инкогнито" в браузере, если есть проблемы с самоподписанными SSL-сертификатами).
