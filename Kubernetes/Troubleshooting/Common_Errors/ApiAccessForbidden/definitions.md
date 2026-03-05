# Api Access Forbidden: Определения

## Определения

**`401 Unauthorized`** — Kubernetes не смог аутентифицировать запрос. Проблема с токеном, сертификатом или другим методом аутентификации.

**`403 Forbidden`** — Kubernetes аутентифицировал запрос, но у субъекта нет прав (RBAC) на выполнение запрошенной операции.

> - RBAC: [`../../../Security/rbac/rbac_overview.md`](../../../Security/rbac/rbac_overview.md)
> - Authentication: [`../../../Security/authentication.md`](../../../Security/authentication.md)
> - ServiceAccount: [`../../../Security/rbac/roles.md`](../../../Security/rbac/roles.md)
> - Troubleshooting: [`../troubleshooting_overview.md`](../troubleshooting_overview.md)

### Различия

| Код | Этап | Причина | Решение |
|-----|------|---------|---------|
| **401** | Authentication | Неверный токен, истекший сертификат | Обновить credentials |
| **403** | Authorization | Недостаточно прав RBAC | Исправить Role/RoleBinding |

## Основные концепции

### Модель аутентификации и авторизации

```
Запрос к API
    ↓
Аутентификация (Кто вы?)
    ↓
401 если не удалось
    ↓
Авторизация RBAC (Что можно делать?)
    ↓
403 если нет прав
    ↓
200 OK
```
