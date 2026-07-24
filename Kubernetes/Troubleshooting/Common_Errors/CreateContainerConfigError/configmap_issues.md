# CreateContainerConfigError: Проблемы с ConfigMap

## Определения

**ConfigMap-related CreateContainerConfigError** — состояние пода, возникающее на этапе подготовки к запуску контейнера, когда `kubelet` не может сформировать спецификацию из-за проблем с объектами `ConfigMap`. Это критическая ошибка, блокирующая создание контейнера в рантайме.

Подробные определения ошибки и жизненный цикл пода: [definitions.md](./definitions.md).
Основы работы с ConfigMap: [ConfigMap (Base)](../../../Base/configmap.md).

## Основные концепции

### Типичные причины возникновения ошибки

| Сообщение в Events | Причина | Статус ресурса |
| :--- | :--- | :--- |
| `configmap "x" not found` | ConfigMap не существует в данном Namespace | **Missing** |
| `configmaps "x" not found: key "y" not found` | Ресурс существует, но в нем нет требуемого ключа | **Key Missing** |
| `forbidden: user "x" cannot get resource "configmaps"` | У ServiceAccount пода нет прав на чтение ресурса | **RBAC Error** |
| `Error: ConfigMap "x" is not a valid configmap` | Ресурс поврежден или имеет неверную структуру (редко) | **Invalid** |

### Способы использования и риски

1.  **Переменные окружения (`env`, `envFrom`):**
    *   При использовании `envFrom` отсутствие ресурса блокирует запуск.
    *   Обновление ConfigMap **не подхватывается** работающим процессом (требуется рестарт пода).
2.  **Монтирование как тома (`volumes`):**
    *   Отсутствие ресурса блокирует запуск.
    *   Обновление данных в томе происходит автоматически (~60 сек), но требует поддержки `hot-reload` со стороны приложения.
3.  **Использование `subPath`:**
    *   **Внимание:** Монтирование через `subPath` блокирует автоматическое обновление файлов в контейнере.

### Опциональные ссылки (Optional)

Чтобы отсутствие ConfigMap не блокировало запуск приложения (например, для необязательных настроек), используйте поле `optional: true`.

```yaml
env:
- name: LOG_LEVEL
  valueFrom:
    configMapKeyRef:
      name: my-config
      key: level
      optional: true # Позволит поду запуститься, переменная будет пустой
```

## Практические сценарии

### Сценарий 1: ConfigMap не найден (Namespace mismatch)

Самая частая причина. Ресурс создан в `dev`, а под запущен в `prod`.

**Диагностика:**
```bash
# Проверка наличия ресурса в нужном namespace
kubectl get configmap app-config -n <namespace>
# → Error from server (NotFound): configmaps "app-config" not found
```

**Решение:** Убедитесь, что ConfigMap и Pod находятся в одном Namespace. Пересоздайте ресурс в нужном пространстве имен.

### Сценарий 2: Отсутствие ключа (Key mismatch)

Манифест пода ссылается на ключ `DB_HOST`, а в ConfigMap указан `HOST`.

**Диагностика:**
```bash
# Просмотр ключей без вывода значений
kubectl get configmap app-config -o jsonpath='{.data}' | jq 'keys'
# → [ "HOST", "PORT" ] -- ключа DB_HOST нет
```

**Решение:** Исправьте опечатку в `Deployment` или добавьте ключ в ConfigMap:
```bash
kubectl patch configmap app-config -p '{"data":{"DB_HOST":"db.local"}}'
# → configmap/app-config patched
```

### Сценарий 3: Иммутабельные ConfigMap и ошибки обновления

Если ConfigMap помечен как `immutable: true`, вы не сможете его обновить. Для смены настроек нужно создать новый объект с новым именем.

**Диагностика:**
```bash
kubectl get configmap app-config -o jsonpath='{.immutable}'
# → true
```

**Решение:** Используйте паттерн с хешированием имен (например, через Kustomize `configMapGenerator`), чтобы каждое изменение конфигурации порождало новый ресурс и Rolling Update деплоймента.

### Сценарий 4: Права доступа (RBAC)

Если ресурс существует, но под застрял в `CreateContainerConfigError`, проверьте права ServiceAccount.

**Диагностика:**
```bash
# Имитация проверки прав от имени SA пода
kubectl auth can-i get configmap/app-config --as=system:serviceaccount:<namespace>:<sa-name>
# → no
```

**Решение:** Добавьте соответствующие права через `Role` и `RoleBinding`. Подробнее: [rbac_issues.md](./rbac_issues.md).

### Сценарий 5: Перезапуск при обновлении переменных окружения

Если ConfigMap используется как `env`, его изменение не дойдет до работающих подов.

**Решение:**
```bash
# Выполнение безопасного перезапуска всех подов деплоймента
kubectl rollout restart deployment <deployment-name>
# → deployment.apps/my-app restarted
```

## Список проверок (Checklist)

| Проверка | Команда / Действие |
| :--- | :--- |
| **Namespace** | `kubectl get cm -n <namespace>` |
| **Имена и ключи** | Сравните `configMapKeyRef.key` в Pod с ключами в `data` ресурса |
| **Optional** | Используйте `optional: true` для необязательных конфигов |
| **Immutable** | Проверьте `immutable: true` при проблемах с обновлением |
| **Events** | `kubectl describe pod` — основной источник имени отсутствующего ресурса |

## Дополнительная информация

### Сравнение с Secret

| Аспект | ConfigMap | Secret |
| :--- | :--- | :--- |
| **Данные** | Открытый текст | Base64 (не шифрование) |
| **Размер** | До 1 MiB | До 1 MiB |
| **Рекомендация** | Настройки, флаги, файлы | Пароли, токены, ключи |

### Связанные ресурсы

- [Общая диагностика CreateContainerConfigError](./diagnostics.md)
- [Профилактика и мониторинг](./prevention.md)
- [Проблемы с Secret](./secret_issues.md)
- [Проблемы с RBAC](./rbac_issues.md)
- [Основы ConfigMap (Base)](../../../Base/configmap.md)
