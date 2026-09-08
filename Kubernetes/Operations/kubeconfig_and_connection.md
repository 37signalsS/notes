# Kubeconfig: Подключение к кластеру Kubernetes

## Определения

**Kubeconfig (конфигурационный файл Kubernetes)** — стандартный YAML-файл, который утилита `kubectl` (а также другие клиенты, например `helm`, `k9s`, клиентские библиотеки на Go/Python) использует для организации информации о кластерах, пользователях, пространствах имен и механизмах аутентификации.

По умолчанию `kubectl` ищет этот файл по пути `~/.kube/config`.

**Context (Контекст)** — логическая связка внутри kubeconfig, объединяющая три элемента:
1. **Cluster:** куда подключаться (API server URL, CA сертификат).
2. **User:** с какими учетными данными подключаться (клиентские сертификаты, токены, плагины авторизации).
3. **Namespace (опционально):** пространство имен по умолчанию для этого контекста.

## Предварительные требования

- **kubectl:** версия, совместимая с версией кластера (±1 minor version). Проверка: `kubectl version --client --short`.
- **Доступ к API-серверу:** сетевой маршрут до `kube-apiserver` (порт 6443 по умолчанию) или настроенный локальный прокси.
- **Корректный часовой пояс:** токены и сертификаты проверяются по времени; рассинхронизация часов между клиентом и API-сервером приводит к ошибкам аутентификации.
- **Права на файл:** у файла kubeconfig должны быть права `600` (`chmod 600 ~/.kube/config`), чтобы предотвратить чтение секретов другими пользователями системы.
- **Браузер (для OIDC):** если используется плагин `kubelogin`, требуется доступный браузер для SSO-флоу (или режим `--interactive-mode=non-interactive` для headless-сред).

## Основные концепции

### Структура файла

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
    token: eyJhbG...                       # Bearer токен (ServiceAccount)
- name: oidc-user
  user:
    exec:                                  # Внешний плагин аутентификации
      apiVersion: client.authentication.k8s.io/v1
      command: kubectl
      args:
      - oidc-login
      - get-token
      - --oidc-issuer-url=https://idp.internal.example.com/
      - --oidc-client-id=kubernetes-cli
      - --oidc-extra-scope=profile,email,groups
      - --token-cache-storage=keyring
      interactiveMode: IfAvailable

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
3. **Exec Plugins:** (`exec`). Вызов внешней бинарной утилиты (kubelogin, корпоративные скрипты) для динамического получения токена (часто OIDC/SSO).
4. **Basic Auth:** (`username` + `password`). Устаревший и крайне небезопасный метод. Отключен по умолчанию во многих современных дистрибутивах.

### Exec Plugins и OIDC

В современных инфраструктурах использование статических токенов или сертификатов для людей считается антипаттерном. Доступ делегируется корпоративному Identity Provider (IdP) через OIDC (Keycloak, Dex, Pinniped) с использованием плагина `kubelogin`.

В этой схеме `kubeconfig` не содержит никаких секретов. При запуске `kubectl`, плагин `kubelogin` открывает браузер для SSO-аутентификации с поддержкой MFA и PKCE (Proof Key for Code Exchange), получает короткоживущий JWT-токен и передает его API-серверу, обеспечивая прозрачную фоновую ротацию (refresh).

### Правила загрузки и приоритеты

`kubectl` и клиентские библиотеки (`client-go`) используют следующую логику загрузки конфигурации:

1. **Флаг `--kubeconfig`:** если указан, используется только этот файл.
2. **Переменная `KUBECONFIG`:** если установлена, `kubectl` сливает все файлы из списка (разделитель `:` в Linux/macOS, `;` в Windows) с учетом порядка: значения из последующих файлов переопределяют предыдущие для одинаковых ключей.
3. **Файл по умолчанию:** `~/.kube/config`, если ни один из вышеперечисленных источников не указан.

Если одновременно указан флаг `--kubeconfig` и `KUBECONFIG`, приоритет имеет флаг. Переменная окружения игнорируется.

### In-Cluster конфигурация

Поды, запущенные внутри кластера, не используют файл `kubeconfig` на диске. Вместо этого клиентские библиотеки (`client-go`) автоматически подтягивают конфигурацию из следующих источников:

- **ServiceAccount токен:** монтируется в путь `/var/run/secrets/kubernetes.io/serviceaccount/token`.
- **Root CA:** `/var/run/secrets/kubernetes.io/serviceaccount/ca.crt`.
- **Namespace:** `/var/run/secrets/kubernetes.io/serviceaccount/namespace`.
- **API Server URL:** передается через переменную окружения `KUBERNETES_SERVICE_HOST` и `KUBERNETES_SERVICE_PORT`.

Это позволяет приложениям получать доступ к Kubernetes API без явного указания kubeconfig-файла.

### Дополнительные поля

- **`preferences`:** необязательный блок для хранения пользовательских предпочтений (например, `colors: true`). Игнорируется большинством инструментов.
- **`extensions`:** нестандартные поля, используемые сторонними инструментами для хранения метаданных.

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

# Просмотр конфигурации конкретного контекста
kubectl config view --minify -o yaml
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

# Переименовать контекст
kubectl config rename-context old-name new-name

# Удалить контекст
kubectl config delete-context stale-context
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

Подробнее о создании постоянных токенов: **[ServiceAccounts](../Base/secrets/creating_secrets.md)**.

### 5. Ручное редактирование Kubeconfig

```bash
# Открыть текущий kubeconfig в редакторе $EDITOR
kubectl config edit

# После сохранения и закрытия редактора kubectl автоматически проверит валидность YAML.
# При наличии ошибок — предложит исправить или отменить изменения.
```

### 6. Резервное копирование и восстановление

```bash
# Создать резервную копию с timestamp
cp ~/.kube/config ~/.kube/config.backup.$(date +%Y%m%d%H%M%S)

# Экспорт конкретного контекста в отдельный файл
kubectl config view --minify --flatten --context=prod-admin > ~/.kube/prod-admin-backup.yaml

# Восстановить контекст из файла
kubectl config use-context prod-admin
```

### 7. Программный доступ через client-go

Клиентские библиотеки Kubernetes (на примере Go) используют kubeconfig через пакет `clientcmd`:

```go
package main

import (
    "context"
    "fmt"
    "k8s.io/client-go/tools/clientcmd"
)

func main() {
    // Загрузка конфигурации из стандартного пути или переменной KUBECONFIG
    config, err := clientcmd.BuildConfigFromFlags("", "")
    if err != nil {
        panic(err)
    }

    // Явное указание пути к kubeconfig
    config, err = clientcmd.BuildConfigFromFlags("", "/path/to/kubeconfig")
    if err != nil {
        panic(err)
    }

    fmt.Printf("API Server: %s\n", config.Host)
}
```

Для Python аналогичную функциональность предоставляет библиотека `kubernetes` через `config.load_kube_config()`.

### 8. In-Cluster доступ (внутри пода)

Если приложение работает внутри кластера и использует клиентскую библиотеку, никакой kubeconfig на диске не требуется:

```go
// client-go: автоматическое обнаружение in-cluster конфигурации
config, err := rest.InClusterConfig()
```

Этот метод читает переменные окружения `KUBERNETES_SERVICE_HOST`/`KUBERNETES_SERVICE_PORT` и монтированный ServiceAccount токен.

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
4. **kubeswitch**: Продвинутый менеджер контекстов для мультикластерных сред с поддержкой шаблонов и credential plugins.

## Диагностика и устранение проблем

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`Unable to connect to the server: x509: certificate has expired`** | Истек клиентский сертификат в kubeconfig | Обратитесь к администратору кластера или обновите сертификаты (например, `kubeadm certs renew` на мастере и скопируйте новый `/etc/kubernetes/admin.conf`). |
| **`error: You must be logged in to the server (Unauthorized)`** | Токен отозван, ServiceAccount удален, или истек срок сессии OIDC | Получите новый токен или выполните повторный логин через плагин (например, `kubectl oidc-login get-token`). |
| **`error: context "foo" does not exist`** | Опечатка в имени контекста или неверный файл | Проверьте список: `kubectl config get-contexts`. Убедитесь, что переменная `KUBECONFIG` указывает на правильный файл. |
| **`Unable to connect... no route to host` / `connection refused`** | API-сервер недоступен по сети, либо неверный IP в kubeconfig | Проверьте строку `server` в kubeconfig. Возможно, вы пытаетесь подключиться к внутреннему IP (10.x.x.x) из внешней сети, не используя VPN. |
| **`x509: certificate signed by unknown authority`** | Поле `certificate-authority-data` отсутствует или не соответствует сертификату сервера | Обновите CA-данные в конфиге или временно используйте `insecure-skip-tls-verify: true` (только для тестирования). |
| **`exec: \"kubelogin\": executable file not found in $PATH`** | Плагин аутентификации не установлен в системе | Установите `kubelogin` или другой exec-плагин и убедитесь, что он доступен в переменной `PATH`. |
| **`Unable to read CA certificate`** | Файл `certificate-authority` или `certificate-authority-data` поврежден/отсутствует | Проверьте права на файл CA или обновите `certificate-authority-data` из корректного корневого сертификата. |
| **`Too many redirects` / `OAuth2 login loop`** | Неверные параметры OIDC или неправильный флаг `--interactive-mode` | Проверьте `--oidc-issuer-url`, `--oidc-client-id` и убедитесь, что браузер может открыть страницу логина. Для headless-сред используйте `--interactive-mode=non-interactive` с заранее подготовленным refresh token. |

## Рекомендации и очистка

### Лучшие практики безопасности

- **Принцип наименьших привилегий:** Никогда не раздавайте разработчикам файл `/etc/kubernetes/admin.conf` (или `~/.kube/config` с мастер-узла). Генерируйте отдельные kubeconfig с ограниченными правами (через RoleBinding).
- **Срок жизни:** Используйте OIDC (OpenID Connect) для аутентификации пользователей. Kubeconfig с OIDC не содержит вечных секретов, а использует токены с коротким сроком жизни (TTL), которые автоматически обновляются.
- **Защита файла:** Убедитесь, что файл `~/.kube/config` имеет права доступа `600` (`chmod 600 ~/.kube/config`), чтобы другие пользователи системы не могли его прочитать.
- **Изоляция сред (Isolation):** Не храните Production и Development контексты в одном файле. Используйте раздельные файлы и объединяйте их через переменную окружения `KUBECONFIG` (например, `export KUBECONFIG=~/.kube/dev.yaml:~/.kube/prod.yaml`) во избежание случайного применения манифестов не в тот кластер.
- **Безопасное хранение кэша (Exec Plugins):** Если используется OIDC-плагин (например, `kubelogin`), всегда настраивайте флаг `--token-cache-storage=keyring`, чтобы кэш токенов сохранялся в зашифрованном хранилище ОС (Keychain/Secret Service), а не в plaintext-файлах.
- **Ротация токенов:** Периодически проверяйте срок действия токенов в kubeconfig. Для статических ServiceAccount токенов настройте алерты на истечение срока действия.
- **Сетевые ограничения:** Если кластер доступен только из внутренней сети, настройте файрвол так, чтобы порт 6443 был доступен только из доверенных подсетей.

### Очистка среды

```bash
# Удалить неиспользуемые контексты
kubectl config delete-context stale-context-1 stale-context-2

# Удалить неиспользуемых пользователей
kubectl config delete-user old-user

# Удалить неиспользуемые записи кластеров
kubectl config delete-cluster old-cluster

# Очистка кэша OIDC-плагина (kubelogin)
kubelogin token cache --cleanup

# Убрать неиспользуемые файлы kubeconfig
rm -f ~/.kube/old-config.yaml
```

## Крайние случаи

- **Множественные файлы KUBECONFIG:** При слиянии нескольких файлов через переменную окружения `KUBECONFIG` одинаковые имена контекстов/пользователей/кластеров переопределяются в порядке следования файлов. Это может привести к неожиданному использованию устаревших credentials. Всегда проверяйте итоговый контекст через `kubectl config current-context` после слияния.
- **Имена контекстов с пробелами и спецсимволами:** `kubectl config use-context` корректно обрабатывает имена с пробелами, если они заключены в кавычки: `kubectl config use-context "my cluster context"`.
- **IPv6-адреса в поле `server`:** Если API-сервер доступен по IPv6, используйте квадратные скобки: `server: https://[2001:db8::1]:6443`.
- **HTTP(S) прокси:** При работе через корпоративный прокси переменные `HTTP_PROXY`/`HTTPS_PROXY` влияют на подключение `kubectl`. Для прямого подключения к локальному API-серверу добавьте его в `NO_PROXY`.
- **Специальные символы в путях:** Если путь к kubeconfig содержит пробелы или не-ASCII символы, используйте кавычки при экспорте `KUBECONFIG` или флаге `--kubeconfig`.
- **Одновременный доступ несколькими версиями kubectl:** Файл `~/.kube/config` может быть несовместим со значительно более старой или новой версией `kubectl`. При обновлении kubectl наProduction-нодах проверяйте формат конфига.

## Дополнительная информация

### Связанные темы

* [Аутентификация в Kubernetes](../Security/authentication.md) — подробный разбор всех методов проверки личности.
* [RBAC: Контроль доступа](../Security/rbac/rbac_overview.md) — как ограничить права ServiceAccount или пользователя из kubeconfig.
* [Troubleshooting: API Access Forbidden](../Troubleshooting/Common_Errors/ApiAccessForbidden/common.md) — решение проблем с авторизацией (401/403).
