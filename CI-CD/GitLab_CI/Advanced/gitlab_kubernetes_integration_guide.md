# Комплексное руководство по интеграции GitLab CI с Kubernetes

Это руководство объединяет информацию из нескольких заметок в единый источник правды, охватывающий различные стратегии и практические подходы к интеграции GitLab с Kubernetes, от базовой "push" модели до продвинутого GitOps.

См. также:
*   [GitOps и ArgoCD](../../../GitOps/ArgoCD.md)

## 1. Обзор стратегий интеграции

Существует несколько подходов к интеграции GitLab с Kubernetes, каждый со своими преимуществами и недостатками.

### 1.1. Подход 1: Встроенная ("нативная") интеграция GitLab (Не рекомендуется)

GitLab предлагает встроенный механизм для подключения к кластеру, нацеленный на максимальную автоматизацию "из коробки".

**Ключевые недостатки и риски:**

*   **Требование `cluster-admin` доступа:** Для своей работы GitLab требует полных административных прав в кластере, что является серьезной угрозой безопасности и нарушает принцип наименьших привилегий.
*   **Хрупкость:** Механизм может быть нестабильным и конфликтовать с уже используемыми инструментами (например, попытка установить свой Nginx Ingress Controller, когда у вас уже используется другой).
*   **Ограниченная гибкость:** Отсутствует возможность ограничить доступ GitLab только одним неймспейсом.

Из-за этих недостатков нативная интеграция редко используется в серьезных продуктивных средах.

### 1.2. Подход 2: Управление через `kubectl` в пайплайне ("Push" модель)

Это более гибкий, прозрачный и контролируемый подход. Вся логика развертывания описывается явно в `.gitlab-ci.yml` с помощью команд `kubectl` или `helm`. CI/CD система "проталкивает" (push) изменения в кластер.

**Для реализации этого подхода требуется два компонента:**
1.  **Образ с инструментами:** Docker-образ, содержащий утилиты `kubectl` и/или `helm`, который будет использоваться в CI-задачах.
2.  **Авторизация в кластере:** Безопасный способ предоставить CI-задаче права для выполнения команд в Kubernetes.

### 1.3. Подход 3: GitOps — декларативное управление состоянием ("Pull" модель)

GitOps — это эволюция подхода "Управление через `kubectl`", которая решает фундаментальные проблемы "push" модели. **Git-репозиторий становится единственным источником правды.** Агент, установленный в кластере (например, ArgoCD), "притягивает" (pull) изменения из Git и приводит кластер в соответствие с ними.

---

## 2. Реализация "Push" модели: Авторизация и развертывание

Рассмотрим детально, как настроить управление кластером из CI-пайплайна.

### Шаг 1: Настройка авторизации

Существует несколько способов предоставить GitLab Runner'у доступ к Kubernetes.

#### Способ 1: Авторизация через `KUBE_CONFIG` в CI/CD переменных (Простой, но менее безопасный)

Этот способ состоит в том, чтобы добавить переменную `KUBE_CONFIG` для подключения к удаленному кластеру в переменные GitLab CI.

1.  Получите конфигурацию `kubeconfig` с мастер-ноды кластера в формате base64:
    ```bash
    cat /path/to/your/.kube/config | base64 -w 0 ; echo
    ```

2.  В вашем проекте GitLab перейдите в **Settings -> CI/CD** и раскройте раздел **Variables**.

3.  Нажмите **Add variable** и добавьте переменную:
    *   **Key:** `K8S_CONFIG`
    *   **Value:** Вставьте содержимое, скопированное с мастер-ноды.
    *   **Flags:** Пометьте переменную как **"Protected"** и **"Masked"**.

4.  Пример использования в `.gitlab-ci.yml`:
    ```yaml
    stages: 
      - kubectl

    kubectl-check:
      stage: kubectl
      image:
        name: bitnami/kubectl:1.21.13 # Образ с kubectl
        entrypoint: [""]
      variables:
        KUBECONFIG: /tmp/.kubeconfig
      script:
        - echo "$K8S_CONFIG" | base64 -d > $KUBECONFIG
        - kubectl get nodes
    ```
    Этот метод требует сетевой доступности между runner'ом и API-сервером Kubernetes.

#### Способ 2: GitLab Runner с Kubernetes Executor (Рекомендуемый)

Это рекомендуемый и более безопасный подход, при котором GitLab Runner устанавливается непосредственно в сам кластер Kubernetes.

1.  **Подготовьте кластер:**
    ```bash
    # Создаем неймспейс для раннера
    kubectl create ns gitlab-runner

    # Создаем ServiceAccount для раннера
    kubectl create sa gitlab-runner-sa -n gitlab-runner

    # Даем ServiceAccount нужные права (для примера cluster-admin, в проде используйте гранулярные права)
    kubectl create clusterrolebinding gitlab-runner-admin --clusterrole=cluster-admin --serviceaccount=gitlab-runner:gitlab-runner-sa
    ```

2.  **Зарегистрируйте Runner** с executor'ом `kubernetes` и добавьте в его конфигурацию (`config.toml`) разрешение на использование ServiceAccount:
    ```toml
    [[runners]]
      name = "kubernetes-runner"
      executor = "kubernetes"
      [runners.kubernetes]
        namespace = "gitlab-runner"
        # service_account_overwrite_allowed разрешает пайплайну использовать указанный SA
        service_account_overwrite_allowed = ".*"
    ```

3.  **Использование в `.gitlab-ci.yml`:**
    ```yaml
    stages: 
      - kubectl

    kubectl-check-in-cluster:
      stage: kubectl
      tags:
        - kubernetes # Тег вашего раннера
      image:
        name: bitnami/kubectl:1.21.13
      variables:
        # Переопределяем ServiceAccount для Pod'а, в котором будет выполняться задача
        KUBERNETES_SERVICE_ACCOUNT_OVERWRITE: gitlab-runner-sa
      script:
        # Конфигурация kubectl для использования встроенного ServiceAccount токена
        - kubectl config set-cluster local --server=https://kubernetes.default.svc --certificate-authority=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        - kubectl config set-context local --cluster=local
        - kubectl config set-credentials user --token=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
        - kubectl config use-context local --user=user
        - kubectl get nodes
    ```
    Токен для `ServiceAccount` автоматически монтируется в каждый Pod, он всегда актуальный и имеет короткий срок жизни. Это наиболее безопасный и идиоматичный способ.

#### Способ 3: Техническая учетная запись в IdP (Корпоративный вариант)

*   **Принцип:** Если кластер интегрирован с внешним провайдером идентификации (LDAP, Active Directory), можно создать специальную техническую учетную запись для CI/CD. Пайплайн будет использовать логин/пароль этой учетной записи для получения временного токена доступа к кластеру, эмулируя действия обычного пользователя.
*   **Применимость:** Актуально для крупных организаций с централизованным управлением доступом.

#### Способ 4: OIDC/JWT-аутентификация (Продвинутый)

*   **Принцип:** Использовать встроенную переменную GitLab `CI_JOB_JWT_TOKEN`. Если настроить доверительные отношения между Kubernetes и GitLab как OIDC-провайдером, кластер сможет валидировать JWT-токен из пайплайна. Это позволяет выполнять действия от имени пользователя, запустившего пайплайн, или от имени конкретного проекта/ветки.
*   **Статус:** Это современный и безопасный подход, соответствующий концепции "Workload Identity Federation".

### Шаг 2: Практический пример развертывания с Helm

Этот пример использует "push" модель для развертывания приложения, упакованного в Helm-чарт.

#### 2.1. Предварительная подготовка

1.  **Работающий кластер Kubernetes.**
2.  **Helm-чарт:** Ваше приложение упаковано в Helm-чарт (например, в директории `charts/`).
3.  **Доступ к GitLab Container Registry:** Кластеру нужен доступ для скачивания образов.

#### 2.2. Настройка доступа Kubernetes к GitLab Container Registry

Чтобы кластер Kubernetes мог скачивать Docker-образы из вашего приватного GitLab Container Registry, ему нужен секрет типа `docker-registry`.

1.  **Создайте Deploy Token в GitLab:**
    *   Перейдите в `Settings > Repository > Deploy Tokens`.
    *   Создайте токен с правами (scope) **`read_registry`**.
    *   Сохраните сгенерированные **имя пользователя** и **пароль**.

2.  **Создайте секрет `docker-registry` в Kubernetes:**
    ```bash
    kubectl create secret docker-registry gitlab-registry \
      --docker-server=<ваш_gitlab_registry_url> \
      --docker-username=<имя_пользователя_deploy_token> \
      --docker-password=<пароль_deploy_token> \
      --namespace=<ваш_namespace>
    ```

3.  **Укажите `imagePullSecrets` в Helm-чарте** (в `values.yaml`):
    ```yaml
    image:
      pullSecrets:
        - name: gitlab-registry 
    ```

#### 2.3. Настройка `.gitlab-ci.yml` для развертывания

Добавьте новую стадию `deploy` и соответствующую задачу.

```yaml
stages: 
  - build
  - push
  - deploy

deploy_to_prod:
  stage: deploy
  image: 
    name: dwolf/helm-kubectl-docker:latest # Пример образа с нужными инструментами
  environment:
    name: production
    url: https://app.$CI_PROJECT_NAMESPACE.example.com
  script:
    # Пример использует переменные KUBE_URL и KUBE_TOKEN (Способ 1). 
    # Для продакшена рекомендуется использовать Kubernetes Executor (Способ 2), 
    # тогда настройка контекста будет выглядеть как в примере 'kubectl-check-in-cluster'.
    - kubectl config set-cluster k8s --server="$KUBE_URL" --insecure-skip-tls-verify=true
    - kubectl config set-credentials gitlab --token="$KUBE_TOKEN"
    - kubectl config set-context default --cluster=k8s --user=gitlab
    - kubectl config use-context default
    
    # Развертывание или обновление с помощью Helm
    - helm upgrade --install \
      --namespace production \
      --set image.tag=$CI_COMMIT_SHORT_SHA \
      --set ingress.host=app.$CI_PROJECT_NAMESPACE.example.com \
      my-app-release \
      ./charts/my-app

  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

**Пояснения:**
*   **`image`**: Для выполнения команд `kubectl` и `helm` требуется специальный Docker-образ.
*   **`environment`**: Эта директива позволяет отслеживать развертывания в GitLab.
*   **`helm upgrade --install`**: Основная команда. `--install` создает релиз, если его нет.
*   `--set image.tag=$CI_COMMIT_SHORT_SHA`: Переопределяет `image.tag` в `values.yaml` на хеш коммита. Это гарантирует развертывание конкретной версии образа (иммутабельность).

---

### Шаг 3: Простой пример развертывания с kubectl apply

Этот пример демонстрирует базовый способ развертывания Kubernetes-манифестов с помощью `kubectl apply` непосредственно из GitLab CI. Он использует подход "push" для отправки изменений в кластер.

**Манифест деплоя (`templates/deploy/kubernetes.yaml`):**
```yaml
variables:
  DOCKER_IMAGE: $CI_REGISTRY_IMAGE
  DOCKER_TAG: $CI_COMMIT_SHA
  DEPLOYMENT_DATE: `date +%Y%m%d-%H-%M-%S`
  MANIFEST_FOLDER: "k8s"
  KUBECONFIG: ""

deploy-k8s:
  stage: deploy
  image:
    name: alpine:3.19
  script:
    - apk update && apk add gettext
    - wget https://storage.googleapis.com/kubernetes-release/release/v1.26.0/bin/linux/amd64/kubectl
    - chmod +x ./kubectl
    - ./kubectl create secret docker-registry regcred --docker-server=$CI_REGISTRY --docker-username=$CI_DEPLOY_USER --docker-password=$CI_DEPLOY_PASSWORD -n $CI_ENVIRONMENT_NAME || true
    - >-
       for MANIFEST in $MANIFEST_FOLDER/*; do
        envsubst < $MANIFEST | ./kubectl apply -n $CI_ENVIRONMENT_NAME -f -;
      done
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: on_success
    - when: never
```

**Пояснения:**
*   **`variables`**: Определяют переменные, используемые в задаче, такие как `DOCKER_IMAGE`, `DOCKER_TAG`, путь к манифестам (`MANIFEST_FOLDER`) и `KUBECONFIG`.
*   **`image`**: Используется легковесный образ `alpine:3.19`, в который устанавливаются `gettext` (для `envsubst`) и `kubectl`.
*   **Установка `kubectl`**: `kubectl` скачивается и устанавливается динамически.
*   **`kubectl create secret docker-registry regcred`**: Создает или обновляет секрет `regcred` для аутентификации в Container Registry. Использует переменные GitLab CI (`CI_REGISTRY`, `CI_DEPLOY_USER`, `CI_DEPLOY_PASSWORD`). Опция `|| true` предотвращает падение пайплайна, если секрет уже существует.
*   **`for MANIFEST in $MANIFEST_FOLDER/*; do ... done`**: Цикл проходит по всем файлам в указанной директории `k8s` (или другой, заданной в `MANIFEST_FOLDER`).
*   **`envsubst < $MANIFEST | ./kubectl apply -n $CI_ENVIRONMENT_NAME -f -`**: Использует `envsubst` для подстановки переменных (например, `$DOCKER_IMAGE`, `$DOCKER_TAG`) в Kubernetes-манифесты, а затем применяет их к кластеру в соответствующем `namespace`.
*   **`rules`**: Задача выполняется только при коммитах в ветку по умолчанию (`$CI_DEFAULT_BRANCH`).

**Важно:** Для корректной работы этого примера необходимо, чтобы переменная `KUBECONFIG` была настроена в GitLab CI/CD (как описано в **Способе 1: Авторизация через `KUBE_CONFIG`**). Также убедитесь, что манифесты Kubernetes (`*.yaml`) находятся в папке, указанной в `MANIFEST_FOLDER` (по умолчанию `k8s`), и содержат плейсхолдеры для подстановки переменных (например, `image: $DOCKER_IMAGE:$DOCKER_TAG`).

---

## 3. "Pull" модель: Принципы GitOps

GitOps решает фундаментальные проблемы "push" модели, делая процесс развертывания детерминированным, безопасным и прозрачным.

### 3.1. Проблемы классической "Push" модели

1.  **Рассинхронизация состояния (State Drift):** Истинное состояние кластера со временем отклоняется от того, что описано в Git.
    *   **Пример 1 (Ручные изменения):** Инженер для срочного исправления применяет `kubectl patch` напрямую в кластере. Следующий запуск CI/CD пайплайна, не зная об этом изменении, перезатрет его, что может привести к повторному возникновению проблемы.
    *   **Пример 2 (Ошибка конфигурации):** Пайплайн для обновления GitLab забыл указать подключение к внешней базе данных. GitLab запускается со своей внутренней, эфемерной базой. Пользователи работают два месяца, после чего под перезапускается, и все данные теряются. Git-репозиторий и реальное состояние были рассинхронизированы.

2.  **Недетерминизм и отсутствие идемпотентности:**
    *   **Mutable-теги:** Использование изменяемых тегов, таких как `latest` или `v1.2`, является анти-паттерном. Невозможно гарантировать, какая именно версия кода работает в кластере, так как разные узлы могут иметь закешированные образы с одним и тем же тегом, но разным содержимым.
    *   **Нестабильность сборки:** Повторная сборка из одного и того же коммита может дать бинарно разный результат из-за динамики зависимостей или кэша сборки.

Эти проблемы порождают **"страх перед развертыванием"**: если пайплайн запускается редко и является непредсказуемым, любой деплой становится рискованным событием.

### 3.2. Принципы GitOps

1.  **Pull-модель вместо Push:**
    *   **Пайплайн CI/CD больше не имеет прямого доступа к кластеру.** Его ответственность — собрать артефакт (образ) и обновить конфигурацию в Git-репозитории манифестов.
    *   **Агент GitOps (ArgoCD, Flux)** внутри кластера "наблюдает" за репозиторием с манифестами.
    *   При обнаружении расхождения агент "притягивает" (pull) изменения и приводит кластер в соответствие с Git.

2.  **Иммутабельные артефакты:**
    *   Каждый собранный образ должен быть версионирован и неизменяем. В качестве тега используется хеш коммита (`CI_COMMIT_SHORT_SHA`) или дайджест образа (`sha256:...`).

3.  **Разделение репозиториев:**
    *   **Репозиторий приложения:** Содержит исходный код. CI/CD пайплайн здесь собирает образ.
    *   **Репозиторий конфигурации:** Содержит Kubernetes-манифесты (Helm, Kustomize). CI/CD пайплайн обновляет здесь `values.yaml`, указывая новый тег/дайджест образа. Именно за этим репозиторием следит GitOps-агент.

**Преимущества GitOps:**
-   **Безопасность:** У CI нет прямых доступов к кластеру.
-   **Надежность и предсказуемость:** Git является единственным источником истины.
-   **Простота отката:** Для отката достаточно выполнить `git revert` в репозитории конфигурации.
-   **Прозрачность:** Вся история изменений кластера хранится в системе контроля версий.

## 4. Заключение

Хотя "нативная" интеграция GitLab с Kubernetes предлагает быстрый старт, ее недостатки в безопасности и гибкости делают ее малопригодной для продакшена.

**Наиболее сбалансированным и рекомендуемым подходом** для большинства случаев является использование **GitLab Runner с Kubernetes Executor'ом** в рамках "push" модели, так как он обеспечивает хороший баланс между безопасностью, гибкостью и простотой настройки.

Для максимальной безопасности, надежности и следования современным практикам стоит рассмотреть **GitOps-подход**, который является современным стандартом для эксплуатации приложений в Kubernetes.