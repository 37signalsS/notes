# Kubeconfig: Подключение к кластеру Kubernetes

## Определения

**kubeconfig** — YAML-файл конфигурации для доступа к Kubernetes API. Используется утилитой `kubectl` и другими клиентами для подключения к кластеру. Содержит информацию о кластерах, учетных данных пользователей и контекстах.

**Контекст (context)** — именованная комбинация кластера, пользователя и пространства имен по умолчанию. Переключение контекстов позволяет быстро менять целевой кластер.

**По умолчанию:** `kubectl` ищет конфигурацию по пути `~/.kube/config`. Путь можно переопределить через переменную окружения `KUBECONFIG`.

## Основные концепции

### Структура файла

Файл `kubeconfig` состоит из четырёх основных секций:

| Секция | Назначение |
| :--- | :--- |
| **`clusters`** | Список кластеров с URL API-сервера и CA-сертификатом |
| **`users`** | Учетные данные для аутентификации (сертификаты, токены) |
| **`contexts`** | Связь кластера и пользователя (опционально: namespace) |
| **`current-context`** | Активный контекст по умолчанию |

### Принцип работы контекстов

Контекст связывает три компонента:

```
Context = Cluster + User + Namespace (опционально)
```

**Пример:**

- Cluster: `production-cluster` → `https://prod-api.example.com:6443`
- User: `admin-user` → сертификат администратора
- Namespace: `default`

При переключении контекста `kubectl` начинает работать с указанным кластером от имени указанного пользователя.

### Пример kubeconfig

```yaml
apiVersion: v1
kind: Config
clusters:
- name: kubernetes-cluster
  cluster:
    certificate-authority-data: <base64 ca.crt>
    server: https://kube-apiserver.example.com:6443
users:
- name: system:node:node01
  user:
    client-certificate-data: <base64 kubelet.crt>
    client-key-data: <base64 kubelet.key>
contexts:
- name: default-context
  context:
    cluster: kubernetes-cluster
    user: system:node:node01
    namespace: default
current-context: default-context
```

### Методы аутентификации

| Метод | Поле в kubeconfig | Применение |
| :--- | :--- | :--- |
| **Client Certificate** | `client-certificate-data`, `client-key-data` | Стандарт для компонентов Control Plane |
| **Bearer Token** | `token` | ServiceAccount, временный доступ |
| **Exec Plugin** | `exec` | Внешние утилиты (aws-iam-authenticator, gke-gcloud-auth-plugin) |
| **Username/Password** | `username`, `password` | Устаревший метод, не рекомендуется |

> **Важно:** Client Certificate — наиболее распространённый метод для аутентификации компонентов кластера. Подробнее: [Управление сертификатами](certificate_management.md).

## Практические сценарии

### Получение kubeconfig

**Bare Metal (kubeadm/Kubespray):**

```bash
# Kubespray создаёт admin.conf на мастер-нодах
scp <user>@<control-node>:<inventory>/artifacts/admin.conf ~/.kube/config
```

**Облачные провайдеры:**

```bash
# GKE
gcloud container clusters get-credentials <cluster-name> --zone <zone>

# EKS
aws eks update-kubeconfig --name <cluster-name> --region <region>

# AKS
az aks get-credentials --name <cluster-name> --resource-group <rg>

# Yandex Cloud
yc managed-kubernetes cluster get-credentials --id <cluster-id>
```

**Локальные кластеры:**

- **Minikube:** `minikube start` автоматически настраивает контекст
- **Kind:** `kind export kubeconfig --name <cluster-name>`

### Управление контекстами

```bash
# Просмотр текущего контекста
kubectl config current-context

# Список всех контекстов
kubectl config get-contexts

# Переключение контекста
kubectl config use-context <context-name>

# Просмотр конфигурации
kubectl config view

# Просмотр с расшифровкой секретов
kubectl config view --raw --minify
```

### Работа с несколькими конфигурациями

```bash
# Объединение нескольких файлов
export KUBECONFIG=~/.kube/config:~/.kube/production:~/.kube/staging

# Слияние в один файл
kubectl config view --raw --merge > ~/.kube/merged-config

# Временное использование другого файла
kubectl --kubeconfig=/path/to/other-config.yaml get pods
```

### Безопасность kubeconfig

| Практика | Описание |
| :--- | :--- |
| **Ограничение прав** | Не использовать admin.conf для повседневных задач |
| **Шифрование** | Хранить файл в зашифрованном виде на рабочих станциях |
| **Rotation** | Регулярно обновлять сертификаты и токены |
| **Backup** | Резервное копирование перед изменениями |

> **Предупреждение:** Файл `admin.conf` предоставляет полный доступ к кластеру. Не копируйте его на ненадёжные машины.

## Дополнительная информация

### Переменные окружения

| Переменная | Назначение |
| :--- | :--- |
| `KUBECONFIG` | Путь к файлу конфигурации (или список через `:`) |
| `KUBERNETES_MASTER` | Переопределение URL API-сервера |

### Инструменты для работы с контекстами

| Инструмент | Описание |
| :--- | :--- |
| **[kubectx](https://github.com/ahmetb/kubectx)** | Быстрое переключение между контекстами |
| **[kubeswitch](../ToolsUtilities/kubeswitches/index.md)** | Менеджер профилей kubeconfig |
| **[Lens](../ToolsUtilities/lens/definitions_and_concepts.md)** | GUI для управления кластерами |

### Troubleshooting

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **context does not exist** | `kubectl config get-contexts` | Проверить имя контекста, пересоздать kubeconfig |
| **certificate has expired** | `openssl x509 -in <cert> -noout -dates` | Обновить сертификаты — [certificate_management.md](certificate_management.md) |
| **unauthorized** | `kubectl auth can-i --list` | Проверить токены/RBAC — [authentication.md](../Security/authentication.md) |
| **connection refused** | `curl -k https://<api-server>:6443/healthz` | Проверить доступность API Server |

### Связанные темы

- [Управление сертификатами](certificate_management.md) — ротация сертификатов в kubeconfig
- [Обновление кластера](upgrading_clusters.md) — генерация нового kubeconfig при обновлении
- [Аутентификация в Kubernetes](../Security/authentication.md) — методы аутентификации
- [kubeadm: Инициализация кластера](../Installation/kubeadm/cluster_initialization.md) — создание admin.conf
