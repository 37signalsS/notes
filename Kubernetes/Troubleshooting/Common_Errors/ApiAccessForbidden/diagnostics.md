# Ошибки доступа к API: диагностика

## Определения

**Диагностика ошибок доступа к API (Application Programming Interface — интерфейс программирования приложений)** — системный процесс выявления причин отказов с кодами 401 и 403 в кластере Kubernetes. Основная цель — сокращение **MTTD (Mean Time To Detect — среднее время обнаружения)** и выбор корректного метода восстановления доступа.

> Краткая диагностика для типовых случаев: [common.md](common.md).
> Описание методов аутентификации: [authentication_methods.md](authentication_methods.md).

## Основные концепции

### Алгоритм диагностики

Процесс анализа строится по каскадному принципу: от идентификации типа ошибки к проверке прав конкретного субъекта.

```
Получена ошибка API
    ↓
Шаг 1: Определение кода ответа (401 или 403)
    ├── 401 → Проверка аутентификации (Кто вы?)
    └── 403 → Проверка авторизации (Что вам разрешено?)
         ↓
    Шаг 2: Идентификация субъекта (ServiceAccount, User, Group)
         ↓
    Шаг 3: Анализ прав RBAC (RoleBinding или ClusterRoleBinding)
         ↓
    Шаг 4: Применение исправлений
```

### Ключевые инструменты

| Инструмент | Назначение | Когда использовать |
|------------|------------|-------------------|
| `kubectl auth can-i` | Проверка прав субъекта | Ошибка 403 — подозрение на нехватку прав |
| `kubectl get rolebinding` | Поиск привязок в пространстве имён | Ошибка 403 — проверка связи **SA (ServiceAccount)** и роли |
| `kubectl describe sa` | Просмотр деталей **ServiceAccount** | Ошибка 401 — проверка токенов и аннотаций |
| `kubectl config view` | Проверка конфигурации **kubeconfig** | Ошибка 401 — неверный кластерный контекст |
| `-v=8` | **HTTP (HyperText Transfer Protocol)** трейс | Точное определение кода ошибки при неясном выводе |

## Практические сценарии

### Шаг 1: Определение типа ошибки

Для начала диагностики необходимо точно определить уровень отказа (аутентификация или авторизация). Используйте режим отладки для просмотра заголовков.

```bash
# Запуск команды с HTTP-трейсом
kubectl get pods -v=8 2>&1 | grep "HTTP/"

# Интерпретация:
# HTTP/1.1 401 Unauthorized → Ошибка аутентификации (личность не подтверждена)
# HTTP/1.1 403 Forbidden → Ошибка авторизации (недостаточно прав RBAC)
```

> Подробное описание различий кодов: [definitions.md](definitions.md).

### Шаг 2: Диагностика 401 Unauthorized

Если получен код 401, проверьте текущий контекст и валидность учетных данных.

```bash
# Проверка текущего контекста и пользователя
kubectl config current-context
kubectl config view --minify -o jsonpath='{.users[0].name}'

# Проверка токена ServiceAccount (для Kubernetes до 1.24)
kubectl get secret $(kubectl get serviceaccount default \
  -o jsonpath='{.secrets[0].name}') \
  -o jsonpath='{.data.token}' | base64 -d
```

**Основные причины:**

- Истечение срока действия токена **ServiceAccount**.
- Проблемы с клиентским сертификатом в **kubeconfig**.
- Несоответствие контекста целевому кластеру.

> Методы решения для 401: [authentication_methods.md](authentication_methods.md).

### Шаг 3: Диагностика 403 Forbidden

При ошибке 403 необходимо проверить, разрешено ли действие согласно **RBAC (Role-Based Access Control — управление доступом на основе ролей)**.

```bash
# Проверка прав текущего пользователя в Namespace
kubectl auth can-i get pods -n default

# Имитация запроса от имени конкретного ServiceAccount
kubectl auth can-i get pods \
  --as=system:serviceaccount:my-ns:my-sa \
  -n my-ns

# Вывод полного списка разрешенных действий для субъекта
kubectl auth can-i --list --as=system:serviceaccount:my-ns:my-sa
```

### Шаг 4: Идентификация ServiceAccount пода

Если ошибка возникает у приложения внутри кластера, проверьте, под каким аккаунтом запущен под.

```bash
# Получение имени ServiceAccount из манифеста пода
kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}'

# Проверка настроек ServiceAccount
kubectl get serviceaccount <sa-name> -n <namespace> -o yaml
```

### Шаг 5: Проверка привязок ролей

Найдите объекты, которые связывают **ServiceAccount** с правилами доступа.

```bash
# Поиск локальных RoleBinding
kubectl get rolebinding -n <namespace> -o wide

# Поиск глобальных ClusterRoleBinding
kubectl get clusterrolebinding -o wide | grep "system:serviceaccount:<namespace>:<sa-name>"
```

## Дополнительная информация

### Автоматизация проверки прав

Для оперативного анализа прав **ServiceAccount** можно использовать следующий сценарий:

```bash
#!/bin/bash
# Проверка прав ServiceAccount (SA)

SA=${1:?Укажите имя ServiceAccount}
NS=${2:-default}

echo "=== Анализ прав для $SA в Namespace $NS ==="

# Итоговый список разрешенных действий
kubectl auth can-i --list --as=system:serviceaccount:"$NS":"$SA"
```

### Связанные ресурсы

- [Определения ошибок 401/403](definitions.md)
- [Распространенные сценарии 403](common.md)
- [Объекты RBAC](rbac_objects.md)
