# Управление окружениями, развертываниями и откатами в GitLab CI

После того как приложение развернуто, начинается его жизненный цикл в определенной среде. GitLab предоставляет мощные инструменты для управления этими средами (окружениями), отслеживания истории развертываний и быстрого отката в случае проблем. Эта заметка объединяет теоретические концепции и практическое руководство по настройке.

См. также:
*   [Развертывание в Kubernetes с помощью GitLab CI и Helm](./gitlab_ci_kubernetes_helm_deploy.md)
*   [GitLab Flow](./gitlab_flow_tutorial.md)
*   [Стратегии интеграции GitLab CI с Kubernetes](./gitlab_kubernetes_integration_strategies.md)

---

## 1. Окружения (Environments) в GitLab

Ключевое слово `environment` в `.gitlab-ci.yml` не просто метка. Оно создает в GitLab объект "Окружение", который можно найти в разделе **Deployments > Environments**.

### 1.1. Статические окружения

Это долгоживущие окружения, такие как `staging` или `production`.

**Пример конфигурации:**
```yaml
deploy_production:
  stage: deploy
  script:
    - echo "Deploying to production..."
    - ./deploy.sh
  environment:
    name: production
    url: https://my-app.com # Прямая ссылка на приложение
```
-   `name: production`: Указывает, что задача относится к окружению `production`.
-   `url: https://my-app.com`: Добавляет кнопку "Open" в UI окружений, позволяя в один клик перейти к развернутому приложению.

### 1.2. Пользовательский интерфейс окружений

В разделе **Deployments > Environments** для каждого окружения GitLab предоставляет:
-   Визуальную историю развертываний.
-   Кнопку **Re-deploy** для повторного запуска последней успешной задачи развертывания.
-   Механизм отката изменений.

---

## 2. Откат изменений (Rollback)

Если после успешного развертывания выяснилось, что новая версия содержит критическую ошибку, необходимо выполнить откат.

### Способ 1: Встроенный механизм GitLab (рекомендуемый)

В UI окружений GitLab для каждого развертывания (кроме самого первого) есть кнопка **Rollback**.

-   **Принцип работы:** Нажатие на эту кнопку **не выполняет специальную логику отката**. Вместо этого GitLab просто **перезапускает задачу (`job`) от предыдущего успешного развертывания**. Если ваши развертывания идемпотентны и версионированы (например, через теги Docker-образов по хешу коммита), этот перезапуск вернет в окружение предыдущую стабильную версию.
-   **Преимущество:** Простота и надежность, не требует написания дополнительного кода.

### Способ 2: Ручная задача `rollback` с Helm

Вы можете создать в `.gitlab-ci.yml` явную задачу для отката, которая дает больше контроля над процессом.

```yaml
stages:
  - deploy
  - rollback

rollback_prod:
  stage: rollback
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual # Запускается только вручную
      allow_failure: true
  environment:
    name: production
    action: start
  image:
    name: centosadmin/kubernetes-helm:3.1.2
    entrypoint: [""]
  script:
    - # Настройка kubectl...
    - >
      helm rollback ${CI_PROJECT_PATH_SLUG}
      --namespace ${CI_PROJECT_PATH_SLUG}-${CI_ENVIRONMENT_NAME}
      --wait
      --timeout 300s
```
-   `when: manual`: Задача не будет запускаться автоматически, а будет ждать ручного запуска из UI пайплайна.
-   `script`: Содержит команду `helm rollback`, которая является идемпотентным способом вернуть предыдущую стабильную версию релиза.

---

## 3. Динамические окружения (Review Apps)

Это временные окружения, которые создаются автоматически для каждой feature-ветки (или Merge Request), чтобы протестировать изменения в изолированной среде перед слиянием с `main`.

### 3.1. Создание и именование

Для создания динамического окружения используются предопределенные переменные GitLab CI, например `$CI_COMMIT_REF_SLUG` (имя ветки, безопасное для URL).

```yaml
deploy_review_app:
  stage: deploy
  script:
    - ./deploy-review.sh
  environment:
    # Имя окружения уникально для каждой ветки
    name: review/$CI_COMMIT_REF_SLUG 
    url: https://$CI_COMMIT_REF_SLUG.example.com 
    # Указываем задачу для уничтожения этого окружения
    on_stop: stop_review_app 
```

### 3.2. Уничтожение динамических окружений

Чтобы временные окружения не потребляли ресурсы бесконечно, их необходимо удалять.

-   **Ручное удаление:** В UI окружений для каждого динамического окружения появляется кнопка "Stop". Нажатие на нее запускает задачу, указанную в `on_stop`.
-   **Автоматическое удаление:** Чтобы окружение удалялось само по истечении времени, используется `auto_stop_in`.

**Пример задачи для остановки:**
```yaml
stop_review_app:
  stage: cleanup
  script:
    - echo "Deleting review app..."
    - ./cleanup-review-app.sh
  when: manual # Задача запускается только по кнопке "Stop" или по триггеру on_stop
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    action: stop # Указывает, что это задача остановки окружения
```

**Пример с автоматической остановкой через 1 день:**
```yaml
deploy_review_app:
  # ...
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.example.com
    on_stop: stop_review_app
    auto_stop_in: 1 day
```

---

## 4. Практическое руководство: Review Apps с Kubernetes

Это руководство демонстрирует полный цикл настройки и использования динамических окружений (Review Apps) в GitLab CI для развертывания приложений в Kubernetes с помощью кастомного "оператора".

### 4.1. Часть 1: Подготовка кластера и развертывание Оператора

Прежде чем наше приложение сможет использовать динамические окружения, нам нужно развернуть в кластере сам сервис, который будет ими управлять — Оператор.

#### 4.1.1. Подготовка ServiceAccount и получение токена
Оператору нужен доступ к API Kubernetes. Создадим для него `ServiceAccount` и `ClusterRoleBinding`.

1.  **Создайте Namespace и ServiceAccount:**
    ```bash
    kubectl create namespace users
    kubectl create serviceaccount deploy-admin -n users
    kubectl create clusterrolebinding deploy-admin-binding --clusterrole=cluster-admin --serviceaccount=users:deploy-admin
    ```
2.  **Получите и расшифруйте токен:**
    ```bash
    SECRET_NAME=$(kubectl get sa deploy-admin -n users -o jsonpath='{.secrets[0].name}')
    KUBE_TOKEN=$(kubectl get secret ${SECRET_NAME} -n users -o jsonpath='{.data.token}' | base64 --decode)
    echo $KUBE_TOKEN
    ```
    Сохраните этот токен.

#### 4.1.2. Настройка и запуск пайплайна Оператора
1.  **Форкните репозиторий оператора** в свой GitLab.
2.  Перейдите в `Settings > CI/CD > Variables` форкнутого проекта.
3.  **Добавьте переменные:**
    *   `KUBE_URL`: URL вашего API-сервера Kubernetes.
    *   `KUBE_TOKEN`: Токен, полученный на предыдущем шаге. Пометьте его как **Masked** и **Protected**.
4.  Запустите пайплайн для ветки `main`, чтобы развернуть оператор в кластере.

### 4.2. Часть 2: Настройка основного приложения

Теперь настроим проект нашего приложения для работы с оператором.

1.  **Форкните репозиторий приложения** в свою группу GitLab.
2.  **Создайте Access Token для GitLab API** (`User Settings > Access Tokens`) с правами `api`. Сохраните его.
3.  **Создайте Deploy Token для Container Registry** (`Project Settings > Repository > Deploy Tokens`) с правами `read_registry` и `write_registry`. Сохраните имя пользователя и пароль.
4.  **(Опционально) Зашифруйте секреты** с помощью `ansible-vault` для безопасного хранения в переменных CI/CD.
    ```bash
    ansible-vault encrypt_string 'ВАШ_API_ACCESS_TOKEN' --name 'GITLAB_API_TOKEN_CRYPTED'
    ansible-vault encrypt_string 'ВАШ_DEPLOY_TOKEN_ПАРОЛЬ' --name 'CR_DEPLOY_PASSWORD_CRYPTED'
    ```
5.  **Настройте переменные CI/CD в проекте приложения:**
    *   `KUBE_URL`
    *   `KUBE_TOKEN`
    *   `GITLAB_API_TOKEN_CRYPTED`
    *   `CR_DEPLOY_PASSWORD_CRYPTED`
    *   `CR_DEPLOY_USER`

### 4.3. Часть 3: Жизненный цикл Review App

1.  Создайте `feature-ветку` в репозитории вашего приложения.
2.  Внесите изменения в код.
3.  Создайте **Merge Request (MR)** из вашей feature-ветки в `main`.
4.  **Автоматический запуск пайплайна:**
    *   Создание MR автоматически запустит пайплайн с задачей `deploy_review`.
    *   Эта задача свяжется с оператором в Kubernetes, который создаст новое, изолированное окружение для вашей ветки.
    *   В виджете Merge Request появится ссылка **"View app"**.
5.  **Просмотр и тестирование:**
    *   Перейдите по ссылке "View app", чтобы открыть развернутое приложение и протестировать изменения.
6.  **Остановка окружения:**
    *   Когда окружение больше не нужно, перейдите в `Deployments > Environments`.
    *   Найдите ваше динамическое окружение (например, `review/feature-my-cool-feature`).
    *   Нажмите кнопку **Stop** (■).
    *   Это действие запустит задачу `stop_review_app` (`environment:on_stop`), которая удалит все ресурсы, связанные с этим окружением.

Этот процесс позволяет эффективно тестировать изменения в изолированных, production-like средах, значительно повышая надежность и скорость разработки.
