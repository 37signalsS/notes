# Ошибки доступа к API (`Forbidden` (403) / `Unauthorized` (401))

### Определение

Эти ошибки возникают при попытке доступа к ресурсам через `kubectl` или API Kubernetes.

* **401 Unauthorized:** Kubernetes не смог вас аутентифицировать. Проблема в вашем токене, сертификате или другом методе аутентификации.
* **403 Forbidden:** Kubernetes вас аутентифицировал, но у вас нет прав (RBAC) на выполнение запрошенной операции (например, `get pods` в определенном `namespace`).

### Основные концепции

* **Authentication:** Процесс проверки личности пользователя (кто вы?).
* **Authorization (RBAC):** Процесс проверки прав пользователя на выполнение действия (что вам можно делать?). Определяется через `Role`, `ClusterRole`, `RoleBinding` и `ClusterRoleBinding`.
* **Kubeconfig:** Файл, содержащий информацию для подключения к кластеру, включая учетные данные.

### Практические сценарии

#### Диагностика

Главный инструмент для отладки RBAC — `kubectl auth can-i`:

```bash
# Могу ли я смотреть поды в неймспейсе 'default'?
kubectl auth can-i get pods -n default

# Может ли это делать сервисный аккаунт 'my-sa'?
kubectl auth can-i list secrets -n kube-system --as=system:serviceaccount:default:my-sa
```

#### Решение

* **401:** Проверьте ваш `kubeconfig` (`kubectl config view`) или обновите токен/сертификат.
* **403:** Создайте или исправьте `Role`/`ClusterRole` и `RoleBinding`/`ClusterRoleBinding`, чтобы предоставить необходимые права.
