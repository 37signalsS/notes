# CreateContainerConfigError: Проблемы с Secret

## Определения

**Secret-related CreateContainerConfigError** — состояние пода, возникающее на этапе подготовки к запуску контейнера, когда `kubelet` не может сформировать спецификацию из-за проблем с объектами `Secret`. Это критическая ошибка, которая блокирует создание контейнера в рантайме (container runtime).

Подробные определения ошибки и жизненный цикл пода: [definitions.md](./definitions.md).
Основы работы с секретами: [secrets_basics.md](../../../Base/secrets/secrets_basics.md).

## Основные концепции

### Типичные причины возникновения ошибки

| Сообщение в Events | Причина | Статус ресурса |
| :--- | :--- | :--- |
| `secret "x" not found` | Секрет не существует в данном Namespace | **Missing** |
| `secret "x" not found: key "y" not found` | Секрет существует, но в нем нет требуемого ключа | **Key Missing** |
| `Error: Secret "x" is not a valid secret type` | Тип секрета не соответствует способу использования (например, ожидался TLS) | **Invalid Type** |
| `forbidden: user "x" cannot get resource "secrets"` | У ServiceAccount пода нет прав на чтение секрета | **RBAC Error** |

### Способы использования Secret и риски

1.  **Переменные окружения (`env`, `envFrom`):**
    *   При использовании `envFrom` отсутствие секрета полностью блокирует запуск пода.
    *   Если секрет обновлен, под **не подхватит** изменения автоматически — требуется рестарт пода.
2.  **Монтирование как тома (`volumes`):**
    *   Если секрет отсутствует, под застрянет в `CreateContainerConfigError` (или `ContainerCreating` в зависимости от версии K8s).
    *   Изменения в секрете обновляются в файловой системе пода автоматически (через период синхронизации `kubelet`, обычно 1 минута).
3.  **Использование в `imagePullSecrets`:**
    *   Приводит не к `CreateContainerConfigError`, а к `ImagePullBackOff`.

### Иммутабельные секреты (Immutable Secrets)

Начиная с Kubernetes 1.21 (GA), секреты можно помечать как неизменяемые (`immutable: true`). Это снижает нагрузку на API-сервер, так как `kubelet` перестает отслеживать изменения. Если такой секрет будет удален, под, использующий его, может столкнуться с ошибкой при перезапуске.

## Практические сценарии

### Сценарий 1: Секрет отсутствует в Namespace

Самая частая причина. Под ссылается на `db-pass`, который забыли создать или создали в другом Namespace.

**Диагностика:**
```bash
kubectl get secret db-pass -n <namespace>
# → Error from server (NotFound): secrets "db-pass" not found
```

**Решение:** Создайте секрет. Рекомендуется использовать `stringData` для автоматического кодирования.
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-pass
stringData:
  password: "mypassword"
```

### Сценарий 2: Отсутствует конкретный ключ (Key mismatch)

Секрет существует, но имя ключа в манифесте пода (`key: pass`) не совпадает с ключом в секрете (`password`).

**Диагностика:**
```bash
# Просмотр ключей без декодирования значений
kubectl get secret db-pass -o jsonpath='{.data}'
# → {"password":"..."}  -- ключ "pass" отсутствует
```

**Решение:** Исправьте ключ в `deployment.yaml` или добавьте недостающий ключ в секрет.
```bash
kubectl patch secret db-pass -p '{"stringData":{"pass":"mypassword"}}'
# → secret/db-pass patched
```

### Сценарий 3: Использование опциональных секретов (Optional)

Чтобы отсутствие секрета не блокировало запуск приложения (например, если конфиг необязателен), используйте поле `optional: true`.

```yaml
env:
- name: API_KEY
  valueFrom:
    secretKeyRef:
      name: my-secret
      key: key
      optional: true  # Позволит поду запуститься, переменная будет пустой
```

### Сценарий 4: Внешние менеджеры секретов (HashiCorp Vault / CSI)

При использовании **Secret Store CSI Driver**, секреты не существуют в Kubernetes как нативные объекты до момента монтирования. Ошибки в `SecretProviderClass` или правах доступа к Vault приведут к `CreateContainerConfigError`.

**Диагностика:**
```bash
kubectl describe pod <pod-name>
# Ищите ошибки в событиях от CSI-драйвера (например, "failed to mount secrets")
```

Подробнее: [Внешние менеджеры секретов](../../../Base/secrets/external_managers.md).

### Сценарий 5: Перезапуск при обновлении секретов

Если секреты используются как переменные окружения, их обновление требует перезапуска деплоймента.

```bash
kubectl rollout restart deployment <deployment-name>
# → deployment.apps/my-app restarted
```

## Список проверок (Checklist)

| Проверка | Команда |
| :--- | :--- |
| **Namespace** | `kubectl get secret -n <pod-namespace>` |
| **Имена и ключи** | `kubectl get secret <name> -o jsonpath='{.data}'` |
| **Права доступа** | `kubectl auth can-i get secret/<name> --as=system:serviceaccount:<ns>:<sa>` |
| **Тип секрета** | `kubectl get secret <name> -o jsonpath='{.type}'` |
| **Размер секрета** | Убедитесь, что секрет не превышает 1 МиБ |

## Дополнительная информация

### Сравнение с ConfigMap

| Аспект | ConfigMap | Secret |
| :--- | :--- | :--- |
| **Безопасность** | Открытый текст | Base64 (не шифрование) |
| **Обновление** | Автоматически для томов | Автоматически для томов |
| **Рекомендация** | Настройки приложения | Пароли, токены, ключи |

### Связанные ресурсы

- [Общая диагностика CreateContainerConfigError](./diagnostics.md)
- [Профилактика и мониторинг](./prevention.md)
- [Проблемы с ConfigMap](./configmap_issues.md)
- [Проблемы с RBAC](./rbac_issues.md)
- [Безопасность секретов (Encryption at Rest)](../../../Base/secrets/security.md)
