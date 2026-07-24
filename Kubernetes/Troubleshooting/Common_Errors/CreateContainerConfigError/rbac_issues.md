# CreateContainerConfigError: Проблемы с RBAC и ServiceAccount

## Определения

**RBAC-related CreateContainerConfigError** — состояние пода, возникающее из-за невозможности `kubelet` подготовить конфигурацию контейнера по причине проблем с правами доступа или отсутствия необходимых объектов `ServiceAccount`. 

Хотя в стандартном Kubernetes `kubelet` использует собственную идентичность для чтения ConfigMap и Secret, ошибки RBAC и конфигурации ServiceAccount могут блокировать запуск пода в специфических сценариях (CSI-драйверы, проекционные тома, защищенные окружения).

Подробные определения ошибки: [definitions.md](./definitions.md).
Обзор RBAC в Kubernetes: [rbac_overview.md](../../../Security/rbac/rbac_overview.md).

## Основные концепции

### Почему возникают проблемы с правами

В большинстве случаев `CreateContainerConfigError` из-за RBAC/SA возникает в следующих ситуациях:

1.  **Отсутствие ServiceAccount:** Под ссылается на `serviceAccountName`, который не существует в текущем Namespace. Кubelet не может создать проекционный том с токеном.
2.  **CSI Secret Store:** При использовании CSI-драйверов для внешних хранилищ секретов (Vault, AWS Secrets Manager) драйвер может использовать **ServiceAccount пода** для аутентификации. Если у SA нет прав на работу с провайдером секретов, монтирование тома завершится ошибкой.
3.  **Ограничения NodeRestriction:** В защищенных кластерах плагин `NodeRestriction` может блокировать `kubelet` доступ к ресурсу, если API-сервер считает, что этот ресурс не должен быть доступен данному узлу.
4.  **Проблемы с токенами (Automount):** Если `automountServiceAccountToken: true`, но системные настройки запрещают создание токенов или есть ошибки в `ClusterRole` для контроллера токенов.

### Типичное сообщение в Events

```text
Error: container_linux.go:348: starting container process caused "process_linux.go:402: container init caused \"rootfs_linux.go:58: mounting \\\"/var/lib/kubelet/pods/.../volumes/kubernetes.io~service-account-token/default-token-xxxxx\\\" ...\""
# Или более явное:
Error: serviceaccount "my-sa" not found
```

## Практические сценарии

### Сценарий 1: ServiceAccount не найден

Самая простая и частая причина. Под ссылается на несуществующий аккаунт.

**Диагностика:**
```bash
# Проверка SA в спецификации пода
kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}'
# → custom-sa

# Проверка существования SA
kubectl get serviceaccount custom-sa
# → Error from server (NotFound): serviceaccounts "custom-sa" not found
```

**Решение:** Создайте ServiceAccount или исправьте имя в манифесте пода.

### Сценарий 2: Использование CSI Secret Store

При использовании `secrets-store.csi.k8s.io` под должен иметь SA с правами, позволяющими драйверу действовать от его имени.

**Симптом:** Под застрял в `CreateContainerConfigError`, в описании — ошибка от CSI-драйвера.

**Диагностика прав через impersonation:**
```bash
# Проверка: может ли SA "читать" секреты (имитация проверки драйвером)
kubectl auth can-i get secret --as=system:serviceaccount:<namespace>:<sa-name>
# → no
```

**Решение:** Создайте `Role` и `RoleBinding`, разрешающие доступ к необходимым ресурсам.

### Сценарий 3: Ошибки проекции токенов (Token Projection)

В современных кластерах (v1.20+) токены SA проецируются как тома. Если в кластере проблемы с `ServiceAccountIssuer` или настройками API-сервера, это вызовет ошибку на этапе формирования конфигурации контейнера.

**Диагностика:**
```bash
kubectl describe pod <pod-name> | grep -A 5 "Volumes:"
# Проверьте наличие тома типа projected для serviceaccount-token
```

### Сценарий 4: Ограничения Namespace

Role и RoleBinding для ServiceAccount должны находиться в том же Namespace, что и сам под (если не используются ClusterRoles).

**Решение:** Убедитесь, что `metadata.namespace` в `RoleBinding` совпадает с Namespace пода.

## Список проверок (Checklist)

| Что проверить | Команда / Метод |
|---------------|-----------------|
| **Существование SA** | `kubectl get sa <name>` |
| **Namespace SA** | Убедиться, что SA и Pod в одном Namespace |
| **Automount** | Проверить `automountServiceAccountToken` в спецификации Pod/SA |
| **CSI Driver logs** | Если используется внешний Vault/AWS, проверить логи CSI-подов |
| **Events** | `kubectl describe pod` — искать ошибки монтирования токена |

## Дополнительная информация

### Связанные ресурсы

- [Общая диагностика CreateContainerConfigError](./diagnostics.md)
- [Проблемы с Secret](./secret_issues.md)
- [Подробно о ServiceAccounts](../../../Security/rbac/bindings.md)
- [Конфигурация Roles и RoleBindings](../../../Security/rbac/roles.md)
- [CSI Driver — архитектура](../../../Storage/CSI/csi_overview.md)
