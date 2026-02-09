# Crossplane: Управление ресурсами Kubernetes (локальный пример)

### Управление ресурсами Kubernetes внутри кластера с помощью `provider-kubernetes` (локальный пример)

Этот сценарий демонстрирует, как Crossplane может управлять нативными ресурсами Kubernetes в том же кластере, где он установлен, используя `provider-kubernetes`. Это полезно для декларативного управления компонентами кластера или для расширения возможностей GitOps на ресурсы Kubernetes.

#### Предварительные требования

*   **Кластер Kubernetes:** Локальный (Minikube, Kind) или облачный.
*   **Установленный Crossplane:** Следуйте шагам по установке Crossplane из раздела "Установка Crossplane и его CLI" выше.

#### Установка и конфигурация `provider-kubernetes`

1.  **Установка `provider-kubernetes`:**
    Создайте файл `kubernetes-provider.yaml`:

    ```yaml
    apiVersion: pkg.crossplane.io/v1
    kind: Provider
    metadata:
      name: provider-kubernetes
    spec:
      package: xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v0.11.4 # Используйте актуальную версию
    ```

    Примените манифест:

    ```bash
    kubectl apply -f kubernetes-provider.yaml
    ```

    Убедитесь, что провайдер установлен и находится в статусе `HEALTHY`:

    ```bash
    kubectl get provider
    ```

2.  **Настройка `ProviderConfig` для управления текущим кластером:**
    `provider-kubernetes` необходимо предоставить разрешения для управления ресурсами. Создайте привязку роли кластера для ServiceAccount провайдера:

    ```bash
    SA=$(kubectl -n crossplane-system get sa -o name | grep provider-kubernetes | sed -e 's|serviceaccount\/|crossplane-system:|g')
    kubectl create clusterrolebinding provider-kubernetes-admin-binding --clusterrole cluster-admin --serviceaccount="${SA}"
    ```

    Затем создайте файл `config-in-cluster.yaml` для `ProviderConfig`:

    ```yaml
    apiVersion: kubernetes.crossplane.io/v1alpha1
    kind: ProviderConfig
    metadata:
      name: in-cluster-config
    spec:
      inCluster: {} # Использует учетные данные ServiceAccount, под которым работает провайдер.
    ```

    Примените манифест:

    ```bash
    kubectl apply -f config-in-cluster.yaml
    ```

#### Развертывание ресурса Kubernetes

Теперь вы можете использовать `provider-kubernetes` для создания нативных ресурсов Kubernetes. Например, создадим `Namespace` и `Deployment` с Nginx.

1.  **Создание `Namespace`:**
    Создайте файл `nginx-namespace.yaml`:

    ```yaml
    apiVersion: kubernetes.crossplane.io/v1alpha2
    kind: Object
    metadata:
      name: nginx-namespace
    spec:
      forProvider:
        manifest:
          apiVersion: v1
          kind: Namespace
          metadata:
            name: crossplane-nginx-example
            labels:
              app.crossplane.io/example: "true"
      providerConfigRef:
        name: in-cluster-config
    ```

    Примените манифест:

    ```bash
    kubectl apply -f nginx-namespace.yaml
    ```

    Проверьте создание пространства имен:

    ```bash
    kubectl get ns crossplane-nginx-example
    ```

2.  **Создание `Deployment` с Nginx:**
    Создайте файл `nginx-deployment.yaml`:

    ```yaml
    apiVersion: kubernetes.crossplane.io/v1alpha2
    kind: Object
    metadata:
      name: nginx-deployment
    spec:
      forProvider:
        manifest:
          apiVersion: apps/v1
          kind: Deployment
          metadata:
            name: nginx-deployment
            namespace: crossplane-nginx-example
            labels:
              app: nginx
          spec:
            replicas: 1
            selector:
              matchLabels:
                app: nginx
            template:
              metadata:
                labels:
                  app: nginx
              spec:
                containers:
                - name: nginx
                  image: nginx:latest
                  ports:
                  - containerPort: 80
      providerConfigRef:
        name: in-cluster-config
    ```

    Примените манифест:

    ```bash
    kubectl apply -f nginx-deployment.yaml
    ```

    Проверьте развертывание Nginx:

    ```bash
    kubectl get deployment -n crossplane-nginx-example
    kubectl get pods -n crossplane-nginx-example
    ```
