# ArgoCD: Декларативный CI/CD для Kubernetes

## Определения

**ArgoCD** — это декларативный [GitOps-инструмент](../GitOps/GitOps_overview.md) непрерывной доставки (CD) для Kubernetes. Он автоматизирует развертывание приложений и синхронизирует состояние кластера с Git-репозиторием, который выступает как единственный источник истины (Single Source of Truth).

## Базовые концепции

### Для чего нужен ArgoCD?

*   **Автоматизация Развертывания:** Устраняет ручное управление развертыванием через `kubectl apply`.
*   **Мониторинг Расхождений:** Постоянно следит за расхождением между состоянием Git и кластера и корректирует его при необходимости.
*   **Мультикластерность:** Работает с несколькими кластерами (по умолчанию видит кластер, на котором установлен, остальные нужно добавлять).
*   **Контроль Версий:** Все изменения проходят через Git, обеспечивая полный контроль версий.
*   **Поддержка Форматов:** Работает со стандартными Kubernetes-манифестами, Helm-чартами и Kustomize. Поддержка Helm и Kustomize особенно полезна для параметризации манифестов, Helm рекомендуется для больших проектов, Kustomize — для небольших.

### Особенности ArgoCD

*   **Веб-интерфейс:** Позволяет визуально отслеживать состояние приложений, просматривать манифесты, логи подов и события, что очень удобно для мониторинга.
*   **CLI:** Предоставляет расширенные возможности управления через командную строку.
*   **Интеграция с RBAC:** Возможность управления правами доступа пользователей к приложениям и кластерам.
*   **ApplicationSet (App of Apps):** Автоматическое создание приложений на основе шаблонов. Позволяет управлять группами приложений или развертывать одно приложение на нескольких кластерах из одного `ApplicationSet` манифеста, значительно повышая уровень абстракции.
*   **Интеграция с CI-инструментами:** ArgoCD выполняет роль CD, CI-инструменты (например, GitLab CI) — роль CI (сборка, тестирование). CI-пайплайн может менять тег образа в манифестах в Git-репозитории, а ArgoCD автоматически подхватит это изменение и развернет новую версию.

### Манифест `Application`

ArgoCD Application — это Kubernetes-ресурс, который описывает, откуда брать конфигурацию приложения (Git-репозиторий, путь, ветка/тег) и куда его развертывать (целевой кластер, неймспейс).

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/argoproj/argocd-example-apps.git # URL Git-репозитория
    targetRevision: HEAD # Ветка, тег или коммит. Для тестирования может быть указана конкретная ветка разработчика.
    path: guestbook # Путь к манифестам в репозитории
  destination:
    server: https://kubernetes.default.svc # Целевой кластер (kubernetes.default.svc для текущего)
    namespace: guestbook # Целевой неймспейс
  syncPolicy:
    automated:
      prune: true # Удалять ресурсы, отсутствующие в Git (при удалении Application - удаляет все его ресурсы)
      selfHeal: true # Восстанавливать изменения, внесенные вне Git (удаленные вручную объекты будут восстановлены)
    syncOptions:
    - CreateNamespace=true # Создавать неймспейс, если он не существует
```

### Синхронизация в ArgoCD

*   **Автоматическая (`syncPolicy.automated: true`):** Изменения в Git немедленно применяются к кластеру. ArgoCD постоянно опрашивает Git-репозиторий на предмет изменений.
*   **Ручная:** Пользователь подтверждает развертывание через веб-интерфейс или CLI.

### Стратегии Развертывания

ArgoCD поддерживает сложные стратегии развертывания:

*   **Canary Deployment:** Постепенный переход трафика от старой версии к новой, с возможностью мониторинга и отката.
*   **Blue/Green Deployment:** Резкий переход трафика на новую версию с возможностью быстрого отката к предыдущей.

### Управление секретами

По умолчанию ArgoCD не работает с зашифрованными секретами напрямую. Для безопасного хранения секретов в Git (Secrets-in-Git) требуются сторонние инструменты:
*   **[Sealed Secrets](../../Kubernetes/Security/sealed_secrets_overview.md)**: Шифрует секреты в Git, которые может расшифровать только контроллер в кластере.
*   **[HashiCorp Vault](../Vault/vault_overview.md)**: Интеграция через плагины, например, `argo-vault-plugin`.
*   **[SOPS (Secrets OPerationS)](../../Security/Tools/sops_overview.md)**: Позволяет шифровать значения в YAML/JSON файлах.

## Практические сценарии

### Практический Пример: Установка и Настройка ArgoCD

#### Подготовка Стенда

1.  **Локальный Kubernetes-кластер:** Для тестирования удобно использовать MiniKube (запущенный через Docker Desktop) или Kind.
    *   Проверка статуса MiniKube: `minikube status`
    *   Запуск MiniKube: `minikube start`
2.  **Сборка и Загрузка Docker-образов (опционально):** Если используются локально собранные образы, их нужно передать в MiniKube, чтобы кластер мог их использовать.
    *   Создание Docker-образов (например, `app:1.0`, `app:2.0`) локально.
    *   Передача собранных образов в MiniKube: `minikube image load <image_name>:<tag>`
3.  **Подготовка Манифестов:** Kubernetes Deployment и Service манифесты для тестового приложения (например, Python Flask app или Nginx) помещаются в Git-репозиторий. Для работы ArgoCD эти манифесты должны быть доступны в репозитории (обычно в отдельной папке).

#### Установка ArgoCD

1.  **Создание Namespace для ArgoCD:** Рекомендуется устанавливать ArgoCD в отдельный Namespace для изоляции.

    ```bash
    kubectl create namespace argocd
    ```

2.  **Развертывание ArgoCD:** Применение официального YAML-манифеста в кластере.

    ```bash
    kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
    ```

3.  **Проверка статуса подов ArgoCD:** Ожидание запуска всех подов в Namespace `argocd`.

    ```bash
    kubectl get pods -n argocd
    ```

#### Доступ к ArgoCD UI

1.  **Проброс портов:** Для доступа к веб-интерфейсу ArgoCD через локальный адрес.

    ```bash
    kubectl port-forward svc/argocd-server -n argocd 8080:443
    ```

    (Интерфейс будет доступен по `https://localhost:8080`, нужно будет игнорировать предупреждения о самоподписанном сертификате).

2.  **Получение административного пароля:** Извлечение автоматически сгенерированного пароля из секрета Kubernetes.

    ```bash
    kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
    ```

3.  **Вход в UI:** Открытие `https://localhost:8080` в браузере, использование `admin` в качестве логина и полученного пароля. Рекомендуется сменить пароль после первого входа.

#### Установка и Настройка ArgoCD CLI (argocd)

1.  **Скачивание ArgoCD CLI:**

    ```bash
    curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
    ```

    (Для других ОС выберите соответствующую версию.)

2.  **Установка прав на выполнение:**

    ```bash
    chmod +x argocd-linux-amd64
    ```

3.  **Перемещение в PATH:**

    ```bash
    sudo mv argocd-linux-amd64 /usr/local/bin/argocd
    ```

4.  **Проверка версии:**

    ```bash
    argocd version
    ```

5.  **Логин в ArgoCD через CLI:**

    ```bash
    argocd login localhost:8080 --username admin
    ```

    (Используйте полученный ранее пароль. CLI достаточно дружелюбен и поддерживает табуляцию.)

#### Добавление Git-репозитория в ArgoCD

ArgoCD должен знать, из каких репозиториев брать манифесты. Репозитории можно добавлять с использованием различных методов аутентификации.

1.  **Добавление репозитория через CLI (примеры):**

    *   **Публичный репозиторий:**
        ```bash
        argocd repo add https://github.com/argoproj/argocd-example-apps.git
        ```
    *   **Приватный репозиторий с SSH ключом:** (Рекомендуется, ключ должен быть доступен в окружении ArgoCD)
        ```bash
        argocd repo add git@gitlab.com:my-group/my-repo.git --ssh-private-key-path <ПУТЬ_К_ПРИВАТНОМУ_КЛЮЧУ>
        ```
        (Для нестандартных SSH портов, например, `ssh://git@gitlab.com:2222/my-group/my-repo.git`)
    *   **Приватный репозиторий с логином/паролем:**
        ```bash
        argocd repo add https://gitlab.com/my-group/my-repo.git --username <USERNAME> --password <PASSWORD>
        ```
    *   **Использование токенов:** Токены (например, для GitHub или GitLab) позволяют выдавать более гранулированные права доступа, что повышает безопасность.

2.  **Проверка статуса репозитория:**

    ```bash
    argocd repo list
    ```

    Убедитесь, что статус `Status: Successful`.

#### Создание и Синхронизация Приложения

1.  **Подготовка манифеста `Application`:** Создайте YAML-файл, например `my-application.yaml`.

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

2.  **Развертывание приложения (Application) в ArgoCD:**

    *   **Через `kubectl`:** Примените манифест `Application`.

        ```bash
        kubectl apply -f my-application.yaml
        ```

    *   **Через ArgoCD CLI:**

        ```bash
        argocd app create guestbook-app --repo https://github.com/argoproj/argocd-example-apps.git --path guestbook --dest-server https://kubernetes.default.svc --dest-namespace default --sync-policy Automated --self-heal --prune --upsert
        ```

3.  **Наблюдение за Развертыванием:**

    *   **Через UI:** Отслеживание состояния приложения в веб-интерфейсе ArgoCD.
    *   **Через CLI:**

        ```bash
        argocd app get guestbook-app
        argocd app list
        ```

#### Обновление и Мониторинг Приложения

1.  **Обновление Приложения:** Измените версию образа (например, с `nginx:1.27` на `nginx:1.28`) и/или количество реплик в Deployment-манифесте в вашем Git-репозитории. Затем выполните `git push`.
2.  **Применение Изменений (автоматически):** ArgoCD автоматически обнаружит изменения в Git (если `syncPolicy.automated` и `selfHeal: true` включены) и инициирует rolling update в кластере, создавая новые поды с новой версией и постепенно удаляя старые.
    *   **Процесс CI/CD:** CI-пайплайн может быть настроен на автоматическое обновление тега образа в манифесте приложения в Git-репозитории после успешной сборки и тестирования. ArgoCD затем подхватит это изменение.
3.  **Проверка Обновленной Версии:** Подтвердите, что приложение обновлено и работает с новой версией (через UI, логи подов, доступ к приложению).

### Пример Установки в Специфичном Окружении (на базе example.com)

Данный пример демонстрирует установку и настройку ArgoCD в учебном кластере Kubernetes.

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

*   **Подготовка SSH-ключей:** ArgoCD, как и любой Git-клиент, требует аутентификации для доступа к приватным репозиториям. Необходимо сгенерировать SSH-ключ, добавить публичную часть в GitLab, а приватную — в ArgoCD.

    ```bash
    # Генерация ключа
    ssh-keygen -t ed25519 -f ~/.ssh/example.com_ed25519
    
    # Добавление публичного ключа в GitLab (https://gitlab.example.com/profile/keys)
    cat ~/.ssh/example.com_ed25519.pub
    ```

*   **Добавление репозитория в ArgoCD:** В настройках ArgoCD (`Settings -> Repositories -> Connect repo using SSH`) укажите URL репозитория и вставьте содержимое **приватного** ключа (`cat ~/.ssh/example.com_ed25519`).

*   **Создание Приложения (Application):**
    В UI ArgoCD нажмите "Create Application" и заполните поля:
    *   **Application Name**: `textserver` (пример)
    *   **Project**: `default`
    *   **Sync Policy**: `Automatic` (для автоматического применения изменений из Git)
    *   **Repository URL**: `git@gitlab.example.com:s000297/argoapp` (пример)
    *   **Path**: `.` (путь к манифестам внутри репозитория)
    *   **Revision**: `HEAD` (отслеживать последнюю версию)
    *   **Destination Cluster URL**: `https://kubernetes.default.svc` (текущий кластер)
    *   **Namespace**: `textserver` (целевой неймспейс для приложения)

#### 6. Демонстрация GitOps в Действии

После создания приложения ArgoCD синхронизирует его состояние с Git.

*   Проверка работы: `curl argoapp.<ваше_имя_пользователя>.edu.example.com` должен вернуть `Hello from argo!`.

*   **Внесение изменений:** Измените что-либо в манифестах в Git-репозитории (например, текст ответа в `values.yaml` для Helm-чарта) и сделайте `git push`.

*   **Автоматическая синхронизация:** ArgoCD обнаружит расхождение ("OutOfSync") и автоматически применит изменения к кластеру, возвращая его в желаемое состояние. Повторный запрос `curl` вернет уже обновленный результат.

## Дополнительная информация

### Устранение неполадок (Troubleshooting)

*   **Ошибки синхронизации:** Проверяйте логи подов ArgoCD (`kubectl logs -n argocd <pod_name>`).
*   **Доступ к репозиторию:** Убедитесь, что ArgoCD имеет корректные учетные данные или SSH-ключи для доступа к Git-репозиторию.
*   **Проблемы с образами:** Если поды не запускаются, проверьте, доступен ли Docker-образ в кластере (например, `minikube image load`).
*   **Конфликты ресурсов:** Используйте `argocd app diff <app_name>` для просмотра различий между Git и состоянием кластера.
*   **"Self-Healing" и "Prune":** Параметр `selfHeal: true` восстанавливает ресурсы, удаленные вручную из кластера. Параметр `prune: true` удаляет ресурсы из кластера, которые больше не присутствуют в Git-репозитории.
*   **Удаление Application:** Если необходимо удалить приложение и все его ресурсы:
    ```bash
    argocd app delete <app_name> --cascade=true
    ```
    Или, если `Application` был создан через `kubectl apply -f`:
    ```bash
    kubectl delete -f my-application.yaml
    ```

### Интеграция ArgoCD с метриками DORA
Подробное описание метрик DORA содержится в документе: [Метрики DORA (DevOps Research and Assessment)](../../CI-CD/Core_Concepts/dora_metrics.md). ArgoCD предоставляет встроенный экспортер метрик для Prometheus, которые можно использовать для отслеживания ключевых показателей DORA:

*   **Deployment Frequency (Частота развертывания)**: отслеживается через количество успешных синхронизаций.
*   **Change Fail Rate (Процент ошибок при изменениях)**: процент синхронизаций со статусом `Failed`.
*   **Mean Time to Recovery (MTTR - Среднее время восстановления)**: время между неудачной синхронизацией и последующей успешной.
*   **Lead Time for Changes (Время выполнения изменений)**: время от коммита до успешной синхронизации в кластере.

ArgoCD предоставляет метрики трех видов: собственные, RepoServer и Application Controller.

#### Метрики Application Controller
Отвечает за приложения:
*   **Application Sync Status:** Статус синхронизации приложений. Используется для построения ChangeFailRate.
*   **Resource Health:** Состояние ресурсов (модулей, служб, подов). Обнаруживает сбои или чрезмерное использование ресурсов, что может указывать на FailRate.
*   **Application Deployment History:** История развертываний и откатов. Помогает отслеживать Deployment Frequency и Change Fail Rate.
*   **Performance Deployment History:** Показатели производительности (потребление ресурсов, время отклика) во время развертывания.
*   **Error and Event Log:** Журналы ошибок и событий. Важен для диагностики и сокращения MTTR.

#### Метрики RepoServer
Отвечает за взаимодействие с Git и Docker Registry:
*   **Git Repository Sync:** Состояние синхронизации репозитория (ошибки, время выборки). Влияет на Lead Time.
*   **Resource Caching:** Отслеживает кэшированные ресурсы в репозитории. Оптимизирует Lead Time.
*   **Authentication and Access:** Журналы доступа и безопасности.
*   **Resource Integrity:** Целостность ресурсов. Обнаруживает повреждения данных, что влияет на Change Fail Rate.
*   **Resource Usage:** Потребление процессора и памяти RepoServer. Влияет на Deployment Frequency, Lead Time и Change Fail Rate.

#### Метрики ArgoCD (собственные)
*   **API Request Metrics:** Запросы к API ArgoCD (количество, время ответа, частота ошибок).
*   **User Authentication and Authorization:** События контроля доступа.
*   **Resource Usage:** Потребление ресурсов сервером ArgoCD.
*   **Application Activity:** Сбор информации об операциях (создание, чтение, обновление, удаление) развертывания приложений.
*   **Dashboard Metrics:** Базовые метрики для диагностики, доступные в веб-интерфейсе ArgoCD.

### Ограничения мониторинга с ArgoCD

*   **Неполное покрытие:** Не всегда удается отследить все части пайплайна.
*   **Сложность системы:** Множество разработчиков и команд затрудняют полное понимание происходящего.
*   **Отсутствие стандартов сбора данных:** Приходится интегрировать различные подходы (метрики, логи).
*   **Изолированная аналитика:** Данные из разных источников могут быть плохо связаны между собой.

### Дополнение ArgoCD инструментом Keptn

Keptn — инструмент, который дополняет возможности ArgoCD для более комплексного мониторинга и контроля непрерывной доставки.

**Основные возможности Keptn:**
*   **Предварительная оценка состояния (Quality Gates):** Перед развертыванием любой нагрузки в кластере.
*   **Определение готовности приложения:** Когда приложение готово к работе.
*   **Декларативная проверка работоспособности:** Используя декларативный подход, что соответствует ArgoCD.
*   **Стандартизация Pre/Post-deployment задач:** Для различных типов развертываний.
*   **Наблюдаемость за всем циклом развертывания:** Более полное покрытие.

**Принцип работы Keptn:**
Не требует сложной настройки. Достаточно добавить аннотации к Deployments: `keptn.sh/app`, `keptn.sh/workload`, `keptn.sh/version` или стандартные аннотации Kubernetes `app.kubernetes.io/part-of`, `app.kubernetes.io/version`.

**CDI (Custom Resource Definitions) Keptn:**
*   **Конфигурируемые вручную:** `App`, `TaskDefinition`, `EvaluationDefinition`, `EvaluationProviders`, `Metric`.
*   **Создаваемые автоматически:** `Workloads`, `WorkloadsInstances`, `Task`, `Version`.