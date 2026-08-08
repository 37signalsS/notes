# CreateContainerConfigError: Проблемы с Secret

## Определения

**Secret-related CreateContainerConfigError** — критическое состояние пода, возникающее на этапе подготовки к запуску контейнера, когда `kubelet` не может сформировать спецификацию из-за проблем с объектами `Secret`. Это блокирует создание контейнера в рантайме (container runtime), так как внешние зависимости для переменных окружения или томов недоступны.

Подробные определения ошибки и жизненный цикл пода: [definitions.md](./definitions.md).
Основы работы с секретами: [secrets_basics.md](../../../Base/secrets/secrets_basics.md).

## Основные концепции

### Механизм возникновения ошибки

1.  **SyncPod Loop:** `kubelet` получает команду на запуск пода и начинает резолвить зависимости.
2.  **API Fetch:** `kubelet` запрашивает содержимое всех Secret, указанных в `spec.containers[].envFrom` или `spec.volumes[]`, через API-сервер.
3.  **Validation & Mapping:**
    *   Если секрет не найден (404) или доступ запрещен (403), `kubelet` не может сопоставить ключи с переменными окружения или смонтировать файлы.
    *   Для томов `kubelet` создает локальную директорию на узле и пытается записать в нее данные секрета.
4.  **Блокировка:** При любой неудаче на этих этапах под переходит в `CreateContainerConfigError`.

### Типичные причины возникновения ошибки

| Сообщение в Events | Причина | Статус ресурса |
| :--- | :--- | :--- |
| `secret "x" not found` | Секрет не существует в данном Namespace | **Missing** |
| `secret "x" not found: key "y" not found` | Секрет существует, но в нем нет требуемого ключа | **Key Missing** |
| `Error: Secret "x" is not a valid secret type` | Несоответствие типа (например, ожидался TLS для Ingress) | **Invalid Type** |
| `forbidden: user "x" cannot get resource "secrets"` | У ServiceAccount пода нет прав на чтение секрета | **RBAC Error** |

### Лимиты и ограничения

*   **Размер:** Максимальный размер одного объекта Secret (и ConfigMap) — **1 MiB**. Превышение лимита приведет к ошибке при создании самого секрета или его чтении.
*   **Иммутабельность (`immutable: true`):** С K8s 1.21 позволяет отключить отслеживание изменений `kubelet`-ом. Это снижает нагрузку на API-сервер, но требует пересоздания пода при необходимости обновления данных.

## Практические сценарии

### Сценарий 1: Секрет отсутствует (Namespace mismatch)

Самая частая причина — манифест пода ссылается на секрет, который создан в другом Namespace.

**Диагностика:**
```bash
# Проверка наличия в Namespace пода
kubectl get secret <secret-name> -n <namespace>
# → Error from server (NotFound): secrets "<secret-name>" not found
```

### Сценарий 2: Отсутствие прав доступа (RBAC)

Если секрет существует, но `kubelet` не может его прочитать от имени пода (в специфических конфигурациях) или если приложение использует SDK.

**Диагностика через impersonation:**
```bash
# Проверка прав ServiceAccount пода
kubectl auth can-i get secret/<secret-name> --as=system:serviceaccount:<ns>:<sa-name>
# → no (или yes)
```

### Сценарий 3: Внешние менеджеры секретов (HashiCorp Vault / CSI)

При использовании **Secrets Store CSI Driver**, секреты не существуют в K8s как нативные объекты до момента монтирования. Ошибки в `SecretProviderClass` приведут к `CreateContainerConfigError`.

**Диагностика:**
```bash
# Проверка событий пода на наличие ошибок от CSI драйвера
kubectl describe pod <pod-name> | grep -A 5 "Events:"
# Ищите сообщения вида: "failed to mount secrets: ..."
```

**Решение:** Проверьте доступность Vault, корректность `Role` в Vault и привязку `ServiceAccount` к этой роли.

### Сценарий 4: Ошибки в Projected Volumes

Если секрет используется в составе `projected` тома вместе с другими источниками (ConfigMap, Downward API).

**Симптом:** Ошибка в одном источнике блокирует весь том и, соответственно, старт контейнера.

### Сценарий 5: Использование опциональных секретов (Optional)

Позволяет избежать `CreateContainerConfigError`, если секрет не является критическим.

```yaml
env:
- name: OPTIONAL_SECRET
  valueFrom:
    secretKeyRef:
      name: my-secret
      key: api-key
      optional: true  # Под запустится, даже если секрета нет
```

## Список проверок (Checklist)

| Проверка | Команда |
| :--- | :--- |
| **Existence** | `kubectl get secret -n <pod-namespace>` |
| **Data Integrity** | `kubectl get secret <name> -o jsonpath='{.data}'` (проверка наличия ключей) |
| **RBAC Permissions** | `kubectl auth can-i get secret/<name> --as=system:serviceaccount:<ns>:<sa>` |
| **Size Limit** | `kubectl get secret <name> -o json | wc -c` (не более 1 MiB) |
| **Mount Status** | Для CSI: проверьте `SecretProviderClass` и логи драйвера |

## Дополнительная информация

### Сравнение с ConfigMap

| Аспект | ConfigMap | Secret |
| :--- | :--- | :--- |
| **Формат данных** | UTF-8 текст | Base64 (бинарные данные) |
| **Безопасность** | Открытый текст | Base64 (требуется шифрование в etcd) |
| **Обновление** | Автоматически (для томов) | Автоматически (для томов) |

### Связанные ресурсы

- [Общая диагностика CreateContainerConfigError](./diagnostics.md)
- [Профилактика и мониторинг](./prevention.md)
- [Проблемы с ConfigMap](./configmap_issues.md)
- [Проблемы с RBAC](./rbac_issues.md)
- [Безопасность секретов (Encryption at Rest)](../../../Base/secrets/security.md)
- [Интеграция Vault с Kubernetes](../../../Vault/guides/vault_kubernetes_integration.md)
