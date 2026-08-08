# Kubeconfig: Подключение к кластеру Kubernetes

## Определения

**Kubeconfig (конфигурационный файл Kubernetes)** — стандартный YAML-файл, который утилита `kubectl` (а также другие клиенты, например `helm`, `k9s`, клиентские библиотеки на Go/Python) использует для организации информации о кластерах, пользователях, пространствах имен и механизмах аутентификации.

По умолчанию `kubectl` ищет этот файл по пути `~/.kube/config`.

**Context (Контекст)** — логическая связка внутри kubeconfig, объединяющая три элемента:
1. **Cluster:** куда подключаться (API server URL, CA сертификат).
2. **User:** с какими учетными данными подключаться (клиентские сертификаты, токены, плагины авторизации).
3. **Namespace (опционально):** пространство имен по умолчанию для этого контекста.

## Структура файла Kubeconfig

Стандартный файл `kubeconfig` состоит из четырех основных секций:

```yaml
apiVersion: v1
kind: Config
preferences: {}

# 1. Секция кластеров (Где находится API?)
clusters:
- cluster:
    certificate-authority-data: LS0tLS1... # Base64 корневого сертификата кластера (CA)
    server: https://192.168.1.100:6443     # URL API-сервера
  name: prod-cluster
- cluster:
    insecure-skip-tls-verify: true         # Пропуск проверки сертификата (небезопасно!)
    server: https://10.0.0.5:6443
  name: dev-cluster

# 2. Секция пользователей (Кто подключается?)
users:
- name: admin-user
  user:
    client-certificate-data: LS0tLS...     # Base64 сертификата клиента
    client-key-data: LS0tLS...             # Base64 приватного ключа
- name: cicd-service-account
  user:
    token: eyJhbG...                       # Статический Bearer токен (ServiceAccount)
- name: aws-iam-user
  user:
    exec:                                  # Использование внешнего плагина (например, aws-iam-authenticator)
      apiVersion: client.authentication.k8s.io/v1beta1
      command: aws
      args:
      - eks
      - get-token
      - --cluster-name
      - my-eks-cluster

# 3. Секция контекстов (Связка Cluster + User + Namespace)
contexts:
- context:
    cluster: prod-cluster
    user: admin-user
    namespace: kube-system
  name: prod-admin
- context:
    cluster: dev-cluster
    user: cicd-service-account
    namespace: default
  name: dev-cicd

# 4. Текущий контекст
current-context: prod-admin                # Какой контекст использует kubectl прямо сейчас
```

### Разбор параметров аутентификации

В секции `user` может использоваться только один метод аутентификации одновременно. Kubernetes поддерживает несколько вариантов:
1. **Client Certificates:** (`client-certificate-data` + `client-key-data`). Наиболее частый способ аутентификации администраторов, создаваемый утилитой `kubeadm`.
2. **Bearer Tokens:** (`token`). Используется для ServiceAccounts (обычно в CI/CD пайплайнах).
3. **Exec Plugins:** (`exec`). Вызов внешней бинарной утилиты (AWS CLI, gcloud, kubelogin) для динамического получения токена (часто OIDC/SSO).
4. **Basic Auth:** (`username` + `password`). Устаревший и крайне небезопасный метод. Отключен по умолчанию во многих современных дистрибутивах.

**Глубокое погружение: Exec Plugins и OIDC (Стандарт 2026 года)**
В современных инфраструктурах использование статических токенов или сертификатов для людей считается антипаттерном. Доступ делегируется корпоративному Identity Provider (IdP) через OIDC (Okta, Keycloak, Azure AD) с использованием плагина `kubelogin`.

*Пример современного безопасного пользователя с OIDC:*
```yaml
users:
- name: oidc-user
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1
      command: kubectl
      args:
      - oidc-login
      - get-token
      - --oidc-issuer-url=https://idp.example.com/
      - --oidc-client-id=kubernetes-cli
      - --oidc-extra-scope=profile,email,groups
      # Критически важно: кэширование токена в защищенном хранилище ОС, а не в открытом виде на диске
      - --token-cache-storage=keyring
      interactiveMode: IfAvailable
```
В этой схеме `kubeconfig` не содержит никаких секретов. При запуске `kubectl`, плагин `kubelogin` открывает браузер для SSO-аутентификации с поддержкой MFA и PKCE (Proof Key for Code Exchange), получает короткоживущий JWT-токен и передает его API-серверу, обеспечивая прозрачную фоновую ротацию (refresh).

## Практические сценарии

### 1. Просмотр текущей конфигурации

```bash
# Просмотр всего файла с маскировкой секретов (токенов/сертификатов)
kubectl config view

# Просмотр полного файла (включая секреты)
kubectl config view --raw

# Получить имя текущего контекста
kubectl config current-context
# → prod-admin
```

### 2. Управление контекстами (Переключение между кластерами)

```bash
# Показать все доступные контексты
kubectl config get-contexts

# Переключиться на контекст 'dev-cicd'
kubectl config use-context dev-cicd
# → Switched to context "dev-cicd".

# Установить пространство имен по умолчанию для текущего контекста
kubectl config set-context --current --namespace=monitoring
```

### 3. Объединение нескольких Kubeconfig (KUBECONFIG env)

Частая задача для DevOps-инженеров — управление десятками кластеров, конфигурации которых выдаются в виде отдельных файлов.

Вместо того чтобы вручную копировать YAML-блоки, можно использовать переменную окружения `KUBECONFIG`:

```bash
# Экспорт переменной с несколькими путями (разделитель - двоеточие)
export KUBECONFIG=~/.kube/config:~/.kube/prod.yaml:~/.kube/dev.yaml

# Теперь kubectl "видит" контексты из всех трех файлов.
kubectl config get-contexts

# Чтобы слить их в один постоянный файл:
kubectl config view --flatten > ~/.kube/config_merged
mv ~/.kube/config_merged ~/.kube/config
unset KUBECONFIG
```

### 4. Создание Kubeconfig для ServiceAccount (для CI/CD)

Если вам нужно дать доступ CI/CD системе (например, GitLab CI) к кластеру, использовать сертификат `admin.conf` небезопасно. Правильный путь — создать `ServiceAccount` с ограниченными правами (RBAC) и сгенерировать для него kubeconfig.

```bash
# 1. Узнаем URL API-сервера
SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')

# 2. Получаем имя Secret, связанного с ServiceAccount
SECRET_NAME=$(kubectl get serviceaccount cicd-user -n default -o jsonpath='{.secrets[0].name}')

# 3. Извлекаем CA и Токен
CA=$(kubectl get secret/$SECRET_NAME -n default -o jsonpath='{.data.ca\.crt}')
TOKEN=$(kubectl get secret/$SECRET_NAME -n default -o jsonpath='{.data.token}' | base64 --decode)

# 4. Формируем kubeconfig
echo "
apiVersion: v1
kind: Config
clusters:
- name: default-cluster
  cluster:
    certificate-authority-data: ${CA}
    server: ${SERVER}
contexts:
- name: default-context
  context:
    cluster: default-cluster
    namespace: default
    user: default-user
current-context: default-context
users:
- name: default-user
  user:
    token: ${TOKEN}
" > cicd-kubeconfig.yaml
```
*Внимание: начиная с Kubernetes 1.24, секреты для ServiceAccount не создаются автоматически. Токен нужно запрашивать через `kubectl create token` (временный) или создавать Secret типа `kubernetes.io/service-account-token` вручную (постоянный).*

Подробнее о создании постоянных токенов: **[ServiceAccounts](../Security/service_accounts.md)**.

## Инструменты для удобной работы

Вместо длинных команд `kubectl config ...` инженеры используют специализированные инструменты:

1. **kubectx**: Утилита для быстрого переключения между контекстами.
   ```bash
   kubectx prod-admin
   kubectx - # Вернуться к предыдущему контексту
   ```
2. **kubens**: Аналогичная утилита для быстрого переключения пространств имен.
   ```bash
   kubens monitoring
   ```
3. **k9s**: Терминальный UI для Kubernetes, который позволяет переключать контексты горячими клавишами (`:ctx`).

## Диагностика и устранение проблем

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`Unable to connect to the server: x509: certificate has expired`** | Истек клиентский сертификат в kubeconfig | Обратитесь к администратору кластера или обновите сертификаты (например, `kubeadm certs renew` на мастере и скопируйте новый `/etc/kubernetes/admin.conf`). |
| **`error: You must be logged in to the server (Unauthorized)`** | Токен отозван, ServiceAccount удален, или истек срок сессии OIDC | Получите новый токен или выполните повторный логин через плагин (например, `aws eks get-token`). |
| **`error: context "foo" does not exist`** | Опечатка в имени контекста или неверный файл | Проверьте список: `kubectl config get-contexts`. Убедитесь, что переменная `KUBECONFIG` указывает на правильный файл. |
| **`Unable to connect... no route to host` / `connection refused`** | API-сервер недоступен по сети, либо неверный IP в kubeconfig | Проверьте строку `server` в kubeconfig. Возможно, вы пытаетесь подключиться к внутреннему IP (10.x.x.x) из внешней сети, не используя VPN. |
| **`x509: certificate signed by unknown authority`** | Поле `certificate-authority-data` отсутствует или не соответствует сертификату сервера | Обновите CA-данные в конфиге или временно используйте `insecure-skip-tls-verify: true` (только для тестирования). |

## Дополнительная информация

### Лучшие практики безопасности

* **Принцип наименьших привилегий:** Никогда не раздавайте разработчикам файл `/etc/kubernetes/admin.conf` (или `~/.kube/config` с мастер-узла). Генерируйте отдельные kubeconfig с ограниченными правами (через RoleBinding).
* **Срок жизни:** Используйте OIDC (OpenID Connect) для аутентификации пользователей. Kubeconfig с OIDC не содержит вечных секретов, а использует токены с коротким сроком жизни (TTL), которые автоматически обновляются.
* **Защита файла:** Убедитесь, что файл `~/.kube/config` имеет права доступа `600` (`chmod 600 ~/.kube/config`), чтобы другие пользователи системы не могли его прочитать.
* **Изоляция сред (Isolation):** Не храните Production и Development контексты в одном файле. Используйте раздельные файлы и объединяйте их через переменную окружения `KUBECONFIG` (например, `export KUBECONFIG=~/.kube/dev.yaml:~/.kube/prod.yaml`) во избежание случайного применения манифестов не в тот кластер.
* **Безопасное хранение кэша (Exec Plugins):** Если используется OIDC-плагин (например, `kubelogin`), всегда настраивайте флаг `--token-cache-storage=keyring`, чтобы кэш токенов сохранялся в зашифрованном хранилище ОС (Keychain/Secret Service), а не в plaintext-файлах.

### Связанные темы

* [Аутентификация в Kubernetes](../Security/authentication.md) — подробный разбор всех методов проверки личности.
* [Управление сертификатами](certificate_management.md) — ротация и обновление данных в PKI.
* [RBAC: Контроль доступа](../Security/rbac/rbac_overview.md) — как ограничить права ServiceAccount или пользователя из kubeconfig.
* [Troubleshooting: API Access Forbidden](../Troubleshooting/Common_Errors/ApiAccessForbidden/index.md) — решение проблем с авторизацией (401/403).
