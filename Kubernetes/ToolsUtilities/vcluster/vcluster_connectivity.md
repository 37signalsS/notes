# vCluster — подключение и доступ

## Определения

**vCluster connectivity** — совокупность методов подключения к виртуальному кластеру и настройки доступа к ресурсам хост-кластера (хранилища, сетевые ресурсы, API). Включает механизмы получения kubeconfig, правила синхронизации объектов и организацию внешнего доступа к контрольному плану (Control Plane).

**kubeconfig vCluster** — файл конфигурации, содержащий учетные данные для доступа к Kubernetes API виртуального кластера. Технически запросы проходят через syncer-прокси, который обеспечивает прозрачную маршрутизацию к внутреннему API-серверу.

**SSL Passthrough** — режим работы Ingress-контроллера, при котором TLS-трафик передается на целевой сервис (API-сервер vCluster) без дешифрации на уровне балансировщика. Это необходимо, так как API-сервер использует взаимную TLS-аутентификацию (mTLS).

## Основные концепции

### Способы получения kubeconfig

| Метод | Описание | Сценарий использования |
| :--- | :--- | :--- |
| **vcluster connect** | Автоматическое создание временного контекста в памяти или файле. | Быстрая отладка, ручное управление кластером. |
| **Флаг --export-kubeconfig** | Экспорт статического файла конфигурации по указанному пути. | Настройка CI/CD пайплайнов, передача доступа другим системам. |
| **Secret в хост-кластере** | Прямое чтение данных из Kubernetes Secret, создаваемого в namespace vCluster. | Автоматизация без использования CLI-инструмента. |
| **Флаг --update-current** | Обновление текущего контекста в системном `~/.kube/config`. | Постоянная работа с конкретным виртуальным кластером. |

### Механизмы синхронизации ресурсов

vCluster использует Syncer для обмена объектами между виртуальным и хостовым окружениями. Основные направления:

- **fromHost (из хоста):** импорт инфраструктурных ресурсов хост-кластера (StorageClasses, IngressClasses, PriorityClasses, Nodes) для их использования внутри vCluster.
- **toHost (в хост):** публикация ресурсов, созданных внутри vCluster (Pods, Services, Endpoints, Ingresses), в хост-кластер для их фактического исполнения и обеспечения сетевой доступности.

Подробное описание политик синхронизации: [Безопасность и синхронизация ресурсов](./vcluster_security_and_sync.md).

### Внешний доступ к API vCluster

Для обеспечения доступа к API-серверу vCluster за пределами хост-кластера обычно используется Ingress или Service типа LoadBalancer. При использовании Ingress обязательна поддержка **SSL passthrough**, так как аутентификация клиента происходит на уровне сертификатов, выпускаемых CA (Certificate Authority) виртуального кластера.

## Практические сценарии

### Подключение через vCluster CLI

```bash
# Интерактивное подключение (создает временный файл и запускает shell)
vcluster connect my-vcluster -n my-namespace

# Экспорт kubeconfig в конкретный файл для CI/CD
vcluster connect my-vcluster -n my-namespace \
  --export-kubeconfig ./vcluster_kubeconfig.yaml

# Обновление текущего контекста в ~/.kube/config (флаг -u)
vcluster connect my-vcluster -n my-namespace -u

# Проверка подключения
export KUBECONFIG=./vcluster_kubeconfig.yaml
kubectl get nodes

# Выполнение разовой команды внутри vCluster без смены контекста
vcluster connect my-vcluster -n my-namespace -- kubectl get pods -A
```

### Извлечение kubeconfig из Kubernetes Secret

Если доступ к CLI ограничен, можно получить конфиг напрямую через `kubectl` хост-кластера:

```bash
# Данные хранятся в секрете с именем vcluster-config (или аналогичным)
kubectl get secret -n <vcluster-namespace> vc-<vcluster-name> \
  -o jsonpath='{.data.config}' | base64 -d > kubeconfig.yaml

export KUBECONFIG=kubeconfig.yaml
kubectl get nodes
```

### Настройка синхронизации StorageClass (fromHost)

Позволяет пользователям vCluster использовать существующие системы хранения хост-кластера.

**Шаг 1: Настройка в vcluster.yaml (v0.20+)**

```yaml
# vcluster.yaml
sync:
  fromHost:
    storageClasses:
      enabled: true
```

**Шаг 2: Создание PVC внутри виртуального кластера**

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-pvc
spec:
  storageClassName: fast-ssd-storage  # Имя SC из хост-кластера
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
```

### Настройка синхронизации Ingress (toHost)

Позволяет публиковать приложения vCluster через Ingress-контроллер хоста.

**Шаг 1: Активация синхронизации в vcluster.yaml**

```yaml
# vcluster.yaml
sync:
  fromHost:
    ingressClasses:
      enabled: true
  toHost:
    ingresses:
      enabled: true
```

**Шаг 2: Создание Ingress внутри vCluster**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: app-ingress
spec:
  ingressClassName: nginx-public  # Класс из хост-кластера
  rules:
    - host: app.vcluster.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: frontend-svc
                port:
                  number: 80
```

### Доступ к API vCluster через Ingress хост-кластера

Для подключения к API-серверу vCluster без VPN или port-forward.

**Конфигурация vcluster.yaml:**

```yaml
# vcluster.yaml
networking:
  ingress:
    enabled: true
    host: "vcluster-api.example.com"
    annotations:
      # Пример для NGINX Ingress Controller
      nginx.ingress.kubernetes.io/ssl-passthrough: "true"
      kubernetes.io/ingress.class: nginx
  proxy:
    extraSANs:
      - "vcluster-api.example.com"
      - "1.2.3.4" # Внешний IP балансировщика (опционально)
```

**Особенности:**
- `extraSANs`: обязательный параметр, добавляет доменное имя в TLS-сертификат API-сервера.
- `ssl-passthrough`: трафик должен доходить до пода vCluster в зашифрованном виде.

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — установка и развертывание](./vcluster_installation.md)
- [vCluster — безопасность и синхронизация ресурсов](./vcluster_security_and_sync.md)
- [Kubeconfig и управление доступом](../../Operations/kubeconfig_and_connection.md)

### Внешние ссылки

- [vCluster Connectivity Guide (Official)](https://www.vcluster.com/docs/architecture/connectivity)
- [External Access to Virtual Clusters](https://www.vcluster.com/docs/features/external-access)
- [Exposing vCluster Applications](https://www.vcluster.com/docs/features/ingress)
