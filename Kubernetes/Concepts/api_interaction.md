# Взаимодействие с API Kubernetes

---
**Надёжность:** 10 (SSoT + Проектный контекст 2026)
**Свежесть:** Актуально на июль 2026
---

## Определение

Взаимодействие с **API-сервером Kubernetes** является основой управления кластером. API предоставляет RESTful интерфейс, через который пользователи и внутренние компоненты могут создавать, изменять, просматривать и удалять ресурсы.

## Основные способы взаимодействия

Существует три основных метода взаимодействия с API Kubernetes:

### 1. Инструмент командной строки (kubectl)

**kubectl** — основной инструмент для управления кластером.
*   **Настройка:** Требует настройки доступа через файл `kubeconfig` (обычно копируется из `/etc/kubernetes/admin.conf` на мастере после инициализации). Позволяет переключаться между контекстами для управления несколькими кластерами.

**Примеры команд:**
```bash
# Перечисление всех подов в default namespace
kubectl get pods

# Удаление пода по имени
kubectl delete pod <pod-name>

# Получение версии клиента и сервера кластера
kubectl version
```

### 2. Клиентские библиотеки (Client Libraries)

Используются для создания пользовательских приложений или сценариев автоматизации. Требуют импорта библиотеки, настройки аутентификации и создания объектов для взаимодействия с ресурсами.

**Пример на Python (библиотека `kubernetes`):**
```python
from kubernetes import client, config

# Загрузка конфигурации из ~/.kube/config
config.load_kube_config()

v1 = client.CoreV1Api()
print("Список подов с их IP-адресами и метками:")

# Получение всех подов во всех пространствах имен
ret = v1.list_pod_for_all_namespaces(watch=False)

for pod in ret.items:
    print(f"{pod.status.pod_ip}\t{pod.metadata.namespace}\t{pod.metadata.name}")
    
    # Вывод меток (labels)
    if pod.metadata.labels:
        print("  Ярлыки:")
        for k, v in pod.metadata.labels.items():
            print(f"    {k}: {v}")
    else:
        print("  Нет меток")
    print("-" * 30)
```

### 3. Прямые HTTP-запросы (Direct REST Calls)

Взаимодействие с API напрямую через HTTP-клиенты (например, `curl`). Требует знания конечной точки API (обычно `https://<cluster-ip>:<port>`) и путей для различных ресурсов.

**Пример вывода списка подов:**
```bash
# Список всех подов в default namespace через curl
curl -X GET https://<cluster-ip>:<port>/api/v1/namespaces/default/pods \
  -H "Authorization: Bearer <token>" --insecure
```

## Практические примеры

### Проверка через curl (прямой запрос)
```bash
# Получение списка подов в default namespace
curl -X GET $APISERVER/api/v1/namespaces/default/pods \
  --header "Authorization: Bearer $TOKEN" --insecure
```

### Проверка через kubectl
```bash
kubectl get pods -n default
```

## См. также
- [Архитектура Control Plane](./control_plane_architecture.md) — роль API-сервера в кластере.
- [Настройка kubeconfig и подключение](../Operations/kubeconfig_and_connection.md) — детали конфигурации доступа.
- [RBAC и права доступа](../Security/rbac/index.md) — как API-сервер ограничивает действия пользователей.
