# Kubeconfig: Подключение к кластеру Kubernetes

> **Связанные разделы:**
>
> * [Управление сертификатами](certificate_management.md) — сертификаты для аутентификации в kubeconfig
> * [Обновление кластера](upgrading_clusters.md) — генерация нового kubeconfig при обновлении

## Определения

**`kubeconfig`** — это YAML-файл, который используется утилитой `kubectl` и другими клиентами для подключения к кластеру Kubernetes. Он содержит всю необходимую информацию для выбора кластера, аутентификации пользователя и определения пространства имен по умолчанию.

## Основные концепции

Файл `kubeconfig` состоит из трех основных блоков, которые связываются между собой через **контексты**.

1. **`clusters` (Кластеры)**
    * Описывает целевые кластеры Kubernetes.
    * Каждый кластер имеет символическое имя и содержит ключевые параметры:
        * `server`: URL API-сервера кластера.
        * `certificate-authority-data`: Base64-кодированный сертификат центра сертификации (CA) для проверки подлинности API-сервера.

2. **`users` (Пользователи)**
    * Описывает учетные данные пользователей для аутентификации в кластере.
    * Каждый пользователь имеет имя и данные для аутентификации, например:
        * `client-certificate-data`: Клиентский сертификат.
        * `client-key-data`: Клиентский ключ.
        * `token`: Токен носителя (bearer token).

3. **`contexts` (Контексты)**
    * Связывает пользователя (`user`) с кластером (`cluster`). Контекст — это именованная комбинация `cluster`, `user` и, опционально, `namespace` по умолчанию для этого сочетания.
    * Именно контексты позволяют легко переключаться между разными кластерами или пользователями.

Файл также содержит поле `current-context`, которое указывает `kubectl`, какой контекст использовать по умолчанию, если он не указан явно в команде.

### Пример `kubeconfig` для `kubelet`

```yaml
apiVersion: v1
kind: Config
clusters:
- name: kubernetes-cluster
  cluster:
    certificate-authority-data: <base64-кодированный ca.crt>
    server: https://kube-apiserver.example.com:6443
users:
- name: system:node:node01.example.com
  user:
    client-certificate-data: <base64-кодированный kubelet.crt>
    client-key-data: <base64-кодированный kubelet.key>
contexts:
- name: default-context
  context:
    cluster: kubernetes-cluster
    user: system:node:node01.example.com
current-context: default-context
```

* `clusters`: Список кластеров. Каждый кластер определяет:
  * `server`: URL-адрес `kube-apiserver`.
  * `certificate-authority-data`: Base64-кодированный сертификат корневого CA для проверки подлинности сервера.

* `users`: Список пользователей. Каждый пользователь определяет учетные данные для аутентификации, например:
  * `client-certificate-data`: Клиентский сертификат в Base64.
  * `client-key-data`: Клиентский приватный ключ в Base64.
* `contexts`: Список контекстов. Контекст — это именованная комбинация `cluster` и `user`, определяющая, к какому кластеру с какими учетными данными подключаться.
* `current-context`: Определяет, какой из контекстов будет использоваться по умолчанию утилитой `kubectl` и другими клиентами.

## Практические сценарии

### Получение файла Kubeconfig

* **Bare Metal (с помощью Kubespray)**
    1. **Генерация**: В процессе установки [Kubespray](../Installation/Kubespray/overview.md) использует `kubeadm`, который создает `kubeconfig` с правами администратора (`/etc/kubernetes/admin.conf`) на мастер-нодах.
    2. **Копирование на узел управления**: Ansible-сценарий Kubespray автоматически копирует этот файл на узел, с которого производился запуск, обычно в директорию `<inventory_dir>/artifacts/admin.conf`.
    3. **Перенос на локальную машину**: Файл необходимо скопировать с узла управления на вашу рабочую станцию, где установлен `kubectl`. По умолчанию `kubectl` ищет конфигурацию по пути `~/.kube/config`.

        ```bash
        # Пример копирования файла конфигурации
        scp <user>@<kubespray-control-node-ip>:<path-to-inventory>/artifacts/admin.conf ~/.kube/config
        ```

* **Облачные провайдеры (GKE, EKS, AKS)**
  * Конфигурация генерируется и добавляется в локальный `~/.kube/config` автоматически с помощью CLI-утилит провайдера (`gcloud container clusters get-credentials`, `aws eks update-kubeconfig`, `az aks get-credentials`).

* **Локальные кластеры (Minikube, Kind)**
  * Инструменты, такие как [Minikube](https://minikube.sigs.k8s.io/docs/) или [Kind](../Installation/kind_quickstart.md), автоматически создают и настраивают `kubeconfig` при создании кластера.
