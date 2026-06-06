# Kubeconfig: Подключение к кластеру Kubernetes

## Определения

**kubeconfig** — файл формата YAML, содержащий параметры конфигурации для подключения к API-серверу Kubernetes. Используется утилитой `kubectl`, а также другими клиентами (Lens, Helm, SDK) для аутентификации и выбора целевого кластера.

**Контекст (context)** — именованная группа параметров, объединяющая кластер, пользователя и (опционально) пространство имен (namespace) по умолчанию. Позволяет быстро переключаться между различными окружениями (например, dev, staging, prod).

**Переменная KUBECONFIG** — переменная окружения, содержащая путь к одному или нескольким файлам конфигурации. По умолчанию `kubectl` ищет файл по пути `~/.kube/config`.

## Основные концепции

### Структура файла

Файл конфигурации состоит из следующих ключевых секций:

| Секция | Назначение |
| :--- | :--- |
| **`clusters`** | Список кластеров: URL API-сервера и данные CA (Certificate Authority) для проверки подлинности сервера. |
| **`users`** | Учетные данные пользователей: клиентские сертификаты, токены или параметры внешних плагинов аутентификации. |
| **`contexts`** | Связки между кластером и пользователем. Здесь же указывается `namespace` по умолчанию для контекста. |
| **`current-context`** | Указывает, какой контекст является активным в данный момент. |

### Методы аутентификации

| Метод | Поле в kubeconfig | Описание |
| :--- | :--- | :--- |
| **Клиентские сертификаты** | `client-certificate-data`, `client-key-data` | Использование X.509 сертификатов. Стандарт для администраторов и системных компонентов. |
| **Bearer Token** | `token` | Статический токен или JWT (ServiceAccount). Часто используется для временного доступа или в CI/CD. |
| **Exec Plugin** | `exec` | Вызов внешней утилиты для получения токена (например, `aws eks get-token` или `gcloud auth`). |

Подробнее о механизмах проверки личности: [Аутентификация в Kubernetes](../Security/authentication.md).

### Принцип работы контекста

Контекст позволяет абстрагироваться от деталей подключения. Команда `kubectl` использует параметры текущего контекста для формирования запроса:

```text
Запрос = [Кластер (URL + CA)] + [Пользователь (Credentials)] + [Namespace]
```

## Практические сценарии

### Получение kubeconfig

#### Для кластеров Bare Metal (kubeadm/Kubespray)

После инициализации через `kubeadm` файл администратора создается по пути `/etc/kubernetes/admin.conf`.

```bash
# Копирование конфига на локальную машину
scp root@master-node:/etc/kubernetes/admin.conf ~/.kube/config
```

#### Для облачных кластеров

```bash
# Google Kubernetes Engine (GKE)
gcloud container clusters get-credentials cluster-name --zone europe-west1-b
# → Fetching cluster endpoint and auth data.
# → kubeconfig entry generated for cluster-name.

# Amazon EKS
aws eks update-kubeconfig --name cluster-name --region eu-central-1
# → Added new context arn:aws:eks:eu-central-1:1234567890:cluster/cluster-name to /home/user/.kube/config
```

#### Для локальных кластеров

* **Minikube:** `minikube start` автоматически добавляет контекст `minikube`.
* **Kind:** `kind export kubeconfig --name my-cluster`.

### Управление контекстами

```bash
# Просмотр текущего активного контекста
kubectl config current-context
# → my-production-cluster

# Список всех доступных контекстов
kubectl config get-contexts
# → CURRENT   NAME          CLUSTER       USER          NAMESPACE
# → *         prod          prod-k8s      admin-user    default
# →           staging       stage-k8s     dev-user      testing

# Переключение на другой контекст
kubectl config use-context staging
# → Switched to context "staging".

# Смена пространства имен по умолчанию для текущего контекста
kubectl config set-context --current --namespace=my-namespace
# → Context "staging" modified.
```

### Работа с несколькими файлами конфигурации

Если файлы разделены, их можно объединить через переменную окружения:

```bash
# Использование нескольких файлов одновременно
export KUBECONFIG=~/.kube/config:~/.kube/dev-config:~/.kube/prod-config

# Слияние всех файлов в один (результат в stdout)
kubectl config view --flatten
```

## Дополнительная информация

### Безопасность и права доступа

Файл `kubeconfig` содержит чувствительные данные (приватные ключи, токены), дающие полный доступ к кластеру.

* **Права доступа:** Устанавливайте права `600` на файлы конфигурации (`chmod 600 ~/.kube/config`).
* **Разделение привилегий:** Не передавайте `admin.conf` обычным пользователям. Создавайте для них отдельные `ServiceAccount` с ограниченным RBAC.
* **Ротация:** Регулярно обновляйте сертификаты. Подробнее: [Управление сертификатами](certificate_management.md).

### Инструменты для работы с контекстами

| Инструмент | Назначение |
| :--- | :--- |
| **kubectx** | Быстрое переключение между контекстами кластеров. |
| **kubens** | Быстрое переключение между пространствами имен (namespaces). |
| **[kubeswitches](../ToolsUtilities/kubeswitches/kubeswitch_overview.md)** | Менеджер для работы с сотнями изолированных файлов kubeconfig. |

### Устранение проблем (Troubleshooting)

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **error: context "X" does not exist** | `kubectl config get-contexts` | Убедитесь, что контекст есть в списке. Проверьте опечатки в имени. |
| **Unable to connect to the server** | `kubectl config view` | Проверьте поле `server` (URL). Убедитесь, что API-сервер доступен по сети. |
| **x509: certificate expired** | `openssl x509 -in <cert> -noout -dates` | Обновите сертификаты в кластере или получите новый kubeconfig. |
| **Forbidden / Unauthorized** | `kubectl auth can-i --list` | Проверьте права пользователя в текущем контексте и актуальность токена. |

### Связанные темы

* [Управление сертификатами](certificate_management.md) — обновление данных в конфиге.
* [Аутентификация в Kubernetes](../Security/authentication.md) — глубокое погружение в методы проверки.
* [RBAC: Контроль доступа](../Security/rbac/rbac_overview.md) — управление правами пользователя из конфига.
* [Инсталляция кластера: kubeadm](../Installation/kubeadm/cluster_initialization.md).
