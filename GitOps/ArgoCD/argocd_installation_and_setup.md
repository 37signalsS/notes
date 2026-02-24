## Практические сценарии

### Практический Пример: Установка и Настройка ArgoCD

#### Подготовка Стенда

1. **Локальный Kubernetes-кластер:** Для тестирования удобно использовать MiniKube (запущенный через Docker Desktop) или Kind.
    * Проверка статуса MiniKube: `minikube status`
    * Запуск MiniKube: `minikube start`
2. **Сборка и Загрузка Docker-образов (опционально):** Если используются локально собранные образы, их нужно передать в MiniKube, чтобы кластер мог их использовать.
    * Создание Docker-образов (например, `app:1.0`, `app:2.0`) локально.
    * Передача собранных образов в MiniKube: `minikube image load <image_name>:<tag>`
3. **Подготовка Манифестов:** Kubernetes Deployment и Service манифесты для тестового приложения (например, Python Flask app или Nginx) помещаются в Git-репозиторий. Для работы ArgoCD эти манифесты должны быть доступны в репозитории (обычно в отдельной папке).

#### Установка ArgoCD

1. **Создание Namespace для ArgoCD:** Рекомендуется устанавливать ArgoCD в отдельный Namespace для изоляции.

    ```bash
    kubectl create namespace argocd
    ```

2. **Развертывание ArgoCD:** Применение официального YAML-манифеста в кластере.

    ```bash
    kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
    ```

3. **Проверка статуса подов ArgoCD:** Ожидание запуска всех подов в Namespace `argocd`.

    ```bash
    kubectl get pods -n argocd
    ```

#### Доступ к ArgoCD UI

1. **Проброс портов:** Для доступа к веб-интерфейсу ArgoCD через локальный адрес.

    ```bash
    kubectl port-forward svc/argocd-server -n argocd 8080:443
    ```

    (Интерфейс будет доступен по `https://localhost:8080`, нужно будет игнорировать предупреждения о самоподписанном сертификате).

2. **Получение административного пароля:** Извлечение автоматически сгенерированного пароля из секрета Kubernetes.

    ```bash
    kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
    ```

3. **Вход в UI:** Открытие `https://localhost:8080` в браузере, использование `admin` в качестве логина и полученного пароля. Рекомендуется сменить пароль после первого входа.

#### Установка и Настройка ArgoCD CLI (argocd)

1. **Скачивание ArgoCD CLI:**

    ```bash
    curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
    ```

    (Для других ОС выберите соответствующую версию.)

2. **Установка прав на выполнение:**

    ```bash
    chmod +x argocd-linux-amd64
    ```

3. **Перемещение в PATH:**

    ```bash
    sudo mv argocd-linux-amd64 /usr/local/bin/argocd
    ```

4. **Проверка версии:**

    ```bash
    argocd version
    ```

5. **Логин в ArgoCD через CLI:**

    ```bash
    argocd login localhost:8080 --username admin
    ```

    (Используйте полученный ранее пароль. CLI достаточно дружелюбен и поддерживает табуляцию.)

#### Добавление Git-репозитория в ArgoCD

ArgoCD должен знать, из каких репозиториев брать манифесты. Репозитории можно добавлять с использованием различных методов аутентификации.

1. **Добавление репозитория через CLI (примеры):**

    * **Публичный репозиторий:**

        ```bash
        argocd repo add https://github.com/argoproj/argocd-example-apps.git
        ```

    * **Приватный репозиторий с SSH ключом:** (Рекомендуется, ключ должен быть доступен в окружении ArgoCD)

        ```bash
        argocd repo add git@gitlab.com:my-group/my-repo.git --ssh-private-key-path <ПУТЬ_К_ПРИВАТНОМУ_КЛЮЧУ>
        ```

        (Для нестандартных SSH портов, например, `ssh://git@gitlab.com:2222/my-group/my-repo.git`)
    * **Приватный репозиторий с логином/паролем:**

        ```bash
        argocd repo add https://gitlab.com/my-group/my-repo.git --username <USERNAME> --password <PASSWORD>
        ```

    * **Использование токенов:** Токены (например, для GitHub или GitLab) позволяют выдавать более гранулированные права доступа, что повышает безопасность.

2. **Проверка статуса репозитория:**

    ```bash
    argocd repo list
    ```

    Убедитесь, что статус `Status: Successful`.

#### Создание и Синхронизация Приложения

1. **Подготовка манифеста `Application`:** Создайте YAML-файл, например `my-application.yaml`.

    Пример содержимого `my-application.yaml`:

    ```yaml
    apiVersion: argoproj.io/v1alpha1
    kind: Application
    metadata:
      name: guestbook-app
      namespace: argocd
    spec:
      project: default
      source:
        repoURL: https://github.com/argoproj/argocd-example-apps.git
        targetRevision: HEAD
        path: guestbook
      destination:
        server: https://kubernetes.default.svc
        namespace: default # Или другой целевой неймспейс для вашего приложения
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
        - CreateNamespace=true
    ```

2. **Развертывание приложения (Application) в ArgoCD:**

    * **Через `kubectl`:** Примените манифест `Application`.

        ```bash
        kubectl apply -f my-application.yaml
        ```

    * **Через ArgoCD CLI:**

        ```bash
        argocd app create guestbook-app --repo https://github.com/argoproj/argocd-example-apps.git --path guestbook --dest-server https://kubernetes.default.svc --dest-namespace default --sync-policy Automated --self-heal --prune --upsert
        ```

3. **Наблюдение за Развертыванием:**

    * **Через UI:** Отслеживание состояния приложения в веб-интерфейсе ArgoCD.
    * **Через CLI:**

        ```bash
        argocd app get guestbook-app
        argocd app list
        ```

#### Обновление и Мониторинг Приложения

1. **Обновление Приложения:** Измените версию образа (например, с `nginx:1.27` на `nginx:1.28`) и/или количество реплик в Deployment-манифесте в вашем Git-репозитории. Затем выполните `git push`.
2. **Применение Изменений (автоматически):** ArgoCD автоматически обнаружит изменения в Git (если `syncPolicy.automated` и `selfHeal: true` включены) и инициирует rolling update в кластере, создавая новые поды с новой версией и постепенно удаляя старые.
    * **Процесс CI/CD:** CI-пайплайн может быть настроен на автоматическое обновление тега образа в манифесте приложения в Git-репозитории после успешной сборки и тестирования. ArgoCD затем подхватит это изменение.
3. **Проверка Обновленной Версии:** Подтвердите, что приложение обновлено и работает с новой версией (через UI, логи подов, доступ к приложению).

### Пример Установки в Специфичном Окружении

**Контекст:** Шаги выполняются на мастер-ноде кластера `sbox.example.com`.

```bash
ssh sbox.example.com
ssh master-1.<uma_nonb3oBaTena> # например, 5000001
sudo -i
```

#### 1. Настройка Ingress-контроллера

Поскольку ArgoCD использует gRPC (базирующийся на HTTP/2), а стандартный `nginx-ingress-controller` может не поддерживать его "из коробки" для passthrough-трафика, требуется дополнительная настройка. Включаем `ssl-passthrough`, чтобы TLS-сессия терминировалась на сервере ArgoCD, а не на Ingress.

```bash
kubectl patch ds -n ingress-nginx nginx-ingress-controller --type='json' -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--enable-ssl-passthrough"}]’
```

#### 2. Конфигурация Ingress-ресурса

Создайте манифест `ingress.yml` и укажите в нем хост, по которому будет доступен ArgoCD.

```yaml
# ingress.yml
...
- host: argocd.__USERNAME__.edu.example.com
...
```

Замените `__USERNAME__` на ваше имя пользователя.

#### 3. Развертывание ArgoCD

```bash
kubectl create ns argocd
kubectl apply -f . -n argocd # Применяются все манифесты из текущей директории
```

#### 4. Получение Пароля Администратора

По умолчанию αρχический пароль для пользователя `admin` совпадает с именем пода `argocd-server`.

```bash
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-server -o name | cut -d/ -f2
```

После этого можно перейти в UI по адресу `https://argocd.<ваше_имя_пользователя>.edu.example.com` и войти с логином `admin` и полученным паролем.

#### 5. Настройка Репозитория и Приложения

Для демонстрации работы создается отдельный Git-репозиторий с манифестами приложения.

* **Подготовка SSH-ключей:** ArgoCD, как и любой Git-клиент, требует аутентификации для доступа к приватным репозиториям. Необходимо сгенерировать SSH-ключ, добавить публичную часть в GitLab, а приватную — в ArgoCD.

    ```bash
    # Генерация ключа
    ssh-keygen -t ed25519 -f ~/.ssh/example.com_ed25519
    
    # Добавление публичного ключа в GitLab (https://gitlab.example.com/profile/keys)
    cat ~/.ssh/example.com_ed25519.pub
    ```

* **Добавление репозитория в ArgoCD:** В настройках ArgoCD (`Settings -> Repositories -> Connect repo using SSH`) укажите URL репозитория и вставьте содержимое **приватного** ключа (`cat ~/.ssh/example.com_ed25519`).

* **Создание Приложения (Application):**
    В UI ArgoCD нажмите "Create Application" и заполните поля:
  * **Application Name**: `textserver` (пример)
  * **Project**: `default`
  * **Sync Policy**: `Automatic` (для автоматического применения изменений из Git)
  * **Repository URL**: `git@gitlab.example.com:s000297/argoapp` (пример)
  * **Path**: `.` (путь к манифестам внутри репозитория)
  * **Revision**: `HEAD` (отслеживать последнюю версию)
  * **Destination Cluster URL**: `https://kubernetes.default.svc` (текущий кластер)
  * **Namespace**: `textserver` (целевой неймспейс для приложения)

#### 6. Демонстрация GitOps в Действии

* Проверка работы: `curl argoapp.<ваше_имя_пользователя>.edu.example.com` должен вернуть `Hello from argo!`.

* **Внесение изменений:** Измените что-либо в манифестах в Git-репозитории (например, текст ответа в `values.yaml` для Helm-чарта) и сделайте `git push`.

* **Автоматическая синхронизация:** ArgoCD обнаружит расхождение ("OutOfSync") и автоматически применит изменения к кластеру, возвращая его в желаемое состояние. Повторный запрос `curl` вернет уже обновленный результат.
