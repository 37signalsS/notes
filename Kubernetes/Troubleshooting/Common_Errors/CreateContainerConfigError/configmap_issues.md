# CreateContainerConfigError: Проблемы с ConfigMap

## Определения

**ConfigMap-related CreateContainerConfigError** — критическое состояние пода, возникающее на этапе подготовки среды выполнения контейнера, когда агент `kubelet` не может успешно разрешить ссылки на объекты `ConfigMap`. 

В отличие от ошибок времени выполнения приложения, эта проблема блокирует создание контейнера в Container Runtime (CRI), так как внешние зависимости для формирования переменных окружения (`env`, `envFrom`) или файловых проекций (`volumes`) недоступны или некорректны. Поскольку контейнер не запущен, логи приложения отсутствуют, и диагностика полностью полагается на события API-сервера.

Подробные определения ошибки и жизненный цикл пода: [definitions.md](./definitions.md).
Основы работы с ConfigMap: [ConfigMap (Base)](../../../Base/configmap.md).

## Основные концепции

### Механизм возникновения ошибки (SyncPod Workflow)

1.  **SyncPod Loop:** `kubelet` получает спецификацию пода от API-сервера и запускает цикл синхронизации.
2.  **Dependency Resolution:** Агент идентифицирует все ссылки на ConfigMap в разделах `env`, `envFrom` и `volumes`.
3.  **API Fetching:** `kubelet` запрашивает содержимое объектов через API-сервер. 
4.  **Data Processing:**
    *   **env/envFrom:** `kubelet` сопоставляет ключи ресурса с переменными окружения. Если ресурс помечен как обязательный (по умолчанию), любой сбой (404 Not Found или 403 Forbidden) прерывает процесс.
    *   **volumes:** Агент подготавливает локальную директорию на узле (`/var/lib/kubelet/pods/...`) и записывает в нее данные (включая `binaryData`).
5.  **Блокировка:** Если разрешение зависимостей не завершено успешно, вызов CRI `CreateContainer` не производится, поду присваивается статус `CreateContainerConfigError`.

### Типичные причины возникновения ошибки

| Сообщение в Events | Причина | Статус ресурса |
| :--- | :--- | :--- |
| `configmap "x" not found` | Ресурс не существует в текущем Namespace | **Missing** |
| `configmaps "x" not found: key "y" not found` | Ресурс существует, но в нем нет требуемого ключа | **Key Missing** |
| `forbidden: user "x" cannot get resource "configmaps"` | Недостаточно прав у ServiceAccount пода (RBAC) или блокировка NodeRestriction | **Forbidden** |
| `Error: ConfigMap "x" is not a valid configmap` | Превышение лимитов размера или повреждение метаданных | **Invalid** |

### Способы использования и риски

1.  **Переменные окружения (`env`, `envFrom`):**
    *   При использовании `envFrom` отсутствие ресурса блокирует запуск всего контейнера.
    *   **Ограничение:** Обновление ConfigMap **не подхватывается** работающим процессом автоматически (требуется рестарт пода).
2.  **Монтирование как тома (`volumes`):**
    *   Отсутствие ресурса блокирует запуск (если не `optional: true`).
    *   Обновление происходит через `kubelet` sync (~60 сек). При использовании `subPath` обновление файлов внутри контейнера **невозможно** без перезапуска.
3.  **Нативные Sidecar-контейнеры (K8s 1.29+):**
    *   Сбой в конфигурации sidecar-контейнера (init-контейнер с `restartPolicy: Always`) блокирует запуск основных контейнеров приложения.

### Лимиты и параметры управления

*   **Размер:** Максимальный размер одного объекта ConfigMap ограничен **1 MiB**. Для больших файлов конфигурации рекомендуется использовать PVC.
*   **BinaryData:** Для нетекстовых данных (сертификаты, `.jks`) используйте поле `binaryData`. Попытка записать бинарный контент в `data` приведет к ошибкам кодировки UTF-8.
*   **Иммутабельность (`immutable: true`):** С K8s 1.21 позволяет оптимизировать работу `kubelet` (отключается Watch). Ресурс нельзя редактировать; для изменений создается новый объект, что гарантирует контролируемый Rollout.

## Практические сценарии

### Сценарий 1: ConfigMap не найден (Namespace mismatch)

Самая частая причина. Ресурс создан в `dev`, а под запущен в `prod`.

**Диагностика:**
```bash
# Проверка наличия ресурса в нужном namespace
kubectl get configmap app-config -n <namespace>
# → Error from server (NotFound): configmaps "app-config" not found
```

### Сценарий 2: Отсутствие ключа (Key mismatch)

Манифест пода ссылается на ключ `DB_HOST`, а в ConfigMap указан `HOST`.

**Диагностика через JSONPath:**
```bash
# Просмотр ключей без вывода значений (для больших конфигов)
kubectl get configmap app-config -o jsonpath='{.data}' | jq 'keys'
# → [ "HOST", "PORT" ] -- ключа DB_HOST нет
```

### Сценарий 3: Права доступа (RBAC) и NodeRestriction

Даже если ресурс существует, `kubelet` может получить отказ 403 Forbidden.
1. **RBAC:** У ServiceAccount пода нет прав `get` на ConfigMap.
2. **NodeRestriction:** Admission-контроллер запрещает узлу читать конфиги, которые не используются его подами.

**Диагностика:**
```bash
# Имитация проверки прав от имени SA пода
kubectl auth can-i get configmap/app-config --as=system:serviceaccount:<ns>:<sa-name>
# → no
```

### Сценарий 4: Опциональные ссылки (Optional)

Чтобы отсутствие ConfigMap не блокировало запуск (например, для локальной отладки), используйте `optional: true`.

```yaml
env:
- name: DEBUG_CONFIG
  valueFrom:
    configMapKeyRef:
      name: non-critical-cfg
      key: debug-level
      optional: true # Под запустится, если ресурса нет
```

### Сценарий 5: Перезапуск при обновлении (Rollout Restart)

Если ConfigMap используется как `env`, его изменение требует пересоздания подов.

```bash
# Безопасный перезапуск всех подов деплоймента
kubectl rollout restart deployment <deployment-name>
```

## Список проверок (Checklist)

| Проверка | Действие |
| :--- | :--- |
| **Namespace Correlation** | Убедитесь, что Pod и ConfigMap в одном Namespace |
| **Key Validation** | Сверьте имена ключей в `configMapKeyRef.key` и `.data` ресурса |
| **Optional Flag** | Используйте `optional: true` для необязательных параметров |
| **Immutable Integrity** | Проверьте `immutable: true` при невозможности редактирования |
| **Size Constraint** | Убедитесь, что объект не превышает 1 MiB |
| **RBAC Audit** | Проверьте `kubectl auth can-i` для ServiceAccount пода |

## Дополнительная информация

### Сравнение с Secret

| Аспект | ConfigMap | Secret |
| :--- | :--- | :--- |
| **Тип данных** | UTF-8 текст / BinaryData | Base64 (бинарные/строки) |
| **Безопасность** | Открытый текст | Требует шифрования (KMS/etcd) |
| **Размер** | До 1 MiB | До 1 MiB |
| **Назначение** | Флаги, конфиги, скрипты | Пароли, токены, TLS-ключи |

### Связанные ресурсы

- [Общая диагностика CreateContainerConfigError](./diagnostics.md)
- [Профилактика и мониторинг](./prevention.md)
- [Проблемы с Secret](./secret_issues.md)
- [Проблемы с RBAC и ServiceAccount](./rbac_issues.md)
- [Детально об обновлении ConfigMap](../../../Base/ConfigMap/update_and_rollout.md)
