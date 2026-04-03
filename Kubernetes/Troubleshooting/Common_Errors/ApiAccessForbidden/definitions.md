# Api Access Forbidden: Определения 401 и 403

## Definitions

**`401 Unauthorized`** — Kubernetes не смог аутентифицировать запрос. Личность субъекта не подтверждена. Проблема с токеном, сертификатом или другим методом аутентификации.

**`403 Forbidden`** — Kubernetes аутентифицировал запрос (личность известна), но у субъекта нет прав RBAC на выполнение запрошенной операции.

> Полное описание методов аутентификации: [../../../Security/authentication.md](../../../Security/authentication.md)
> Полное описание RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)

## Basic Concepts

### Различия 401 и 403

| Код | Этап | Вопрос | Причина | Куда смотреть |
|-----|------|--------|---------|---------------|
| **401** | Authentication | Кто вы? | Неверный токен, истекший сертификат | [authentication_methods.md](authentication_methods.md) |
| **403** | Authorization | Что можно делать? | Недостаточно прав RBAC | [common.md](common.md), [advanced.md](advanced.md) |

### Модель прохождения запроса

```
Запрос к API
    ↓
Аутентификация (Кто вы?)
    ├── Не удалось → 401 Unauthorized
    ↓
Авторизация RBAC (Что можно делать?)
    ├── Нет прав → 403 Forbidden
    ↓
200 OK (запрос выполнен)
```

### Ключевые субъекты (subjects)

Kubernetes идентифицирует запросы через три типа субъектов:

| Тип | Формат | Описание |
|-----|--------|----------|
| **User** | `username` | Внешний пользователь (OIDC, сертификат) |
| **Group** | `groupname` | Группа внешних пользователей |
| **ServiceAccount** | `system:serviceaccount:<namespace>:<name>` | Учетная запись приложения в кластере |

> **Важно:** `User` и `Group` не являются объектами Kubernetes — они управляются внешними системами аутентификации. `ServiceAccount` — объект Kubernetes.

## Practical Scenarios

### Сценарий 1: Быстрая идентификаация типа ошибки

```bash
# Запуск команды с подробным выводом
kubectl get pods -v=8 2>&1 | grep -i "HTTP/"

# Вывод:
# HTTP/1.1 401 Unauthorized → проблема аутентификации
# HTTP/1.1 403 Forbidden → проблема авторизации
```

### Сценарий 2: 401 — проверка текущего пользователя

```bash
# Кто я сейчас?
kubectl config view --minify -o jsonpath='{.users[0].name}'

# Проверка токена (если ServiceAccount)
kubectl auth can-i --list
# Если ошибка "Unauthorized" → 401, токен невалиден
```

### Сценарий 3: 403 — проверка прав ServiceAccount

```bash
# Какой SA у пода?
kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}'

# Есть ли права?
kubectl auth can-i get pods \
  --as=system:serviceaccount:<namespace>:<sa-name> \
  -n <namespace>
# no → 403, нужен RoleBinding
```

## Additional Information

### Почему 401 идёт перед 403

API-сервер всегда сначала проверяет личность (аутентификация), затем права (авторизация). Если запрос не прошёл аутентификацию, RBAC не проверяется — запрос отклоняется сразу с 401.

### Анонимные запросы

По умолчанию Kubernetes разрешает анонимные запросы (`system:anonymous`). Они получают минимальные права через встроенную роль `system:public-info-viewer`. Если анонимный запрос обращается к ресурсу вне этой роли — возвращается 403, а не 401 (запрос формально аутентифицирован как anonymous).

### Связанные ресурсы

- Методы аутентификации и 401: [authentication_methods.md](authentication_methods.md)
- Распространённые случаи 403: [common.md](common.md)
- Расширенные сценарии 403: [advanced.md](advanced.md)
- Диагностика: [diagnostics.md](diagnostics.md)
- RBAC объекты: [rbac_objects.md](rbac_objects.md)
- Лучшие практики: [best_practices.md](best_practices.md)
