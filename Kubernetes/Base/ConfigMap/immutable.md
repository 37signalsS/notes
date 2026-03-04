# Неизменяемые (Immutable) ConfigMap

## Определения

**Immutable ConfigMap** — ConfigMap с установленным флагом `immutable: true`, который запрещает любые изменения после создания.

## Основные концепции

### Назначение

Immutable ConfigMap используются для конфигураций, которые не должны меняться в течение жизни приложения. Это предотвращает случайные или нежелательные изменения.

### Преимущества

* **Безопасность:** Предотвращает случайные или вредоносные изменения.
* **Производительность:** Снижает нагрузку на `kube-apiserver` и `kubelet`, так как им больше не нужно следить за изменениями этого объекта.
* **Предсказуемость:** Гарантирует, что для обновления конфигурации требуется полноценный `rollout` деплоймента, что делает процесс более контролируемым.

## Практические сценарии

### Создание неизменяемой ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
immutable: true # Делает ConfigMap неизменяемой
data:
  LOG_LEVEL: "info"
  MAX_CONNECTIONS: "100"
```

### Попытка изменения (ошибка)

При попытке изменить immutable ConfigMap:

```bash
kubectl patch configmap app-config -p '{"data":{"LOG_LEVEL":"debug"}}'
```

Результат:
```
Error from server (BadRequest): error when patching "configmap/app-config": cannot modify fields other than 'metadata' for immutable configmap
```

### Обновление immutable ConfigMap

Для обновления необходимо:

1. Удалить старую ConfigMap: `kubectl delete configmap app-config`
2. Создать новую с обновлёнными данными

Или изменить манифест и применить с флагом `--force`:
```bash
kubectl apply -f configmap.yaml --force
```

### Когда использовать immutable ConfigMap

| Сценарий | Рекомендация |
| :--- | :--- |
| Конфигурация приложения (версия) | ✅ Immutable |
| Статические файлы конфигурации | ✅ Immutable |
| Часто меняющиеся настройки | ❌ Mutable |
| Конфигурация для CI/CD | ✅ Immutable |
| Feature flags | ❌ Mutable |

## Дополнительная информация

### Сравнение mutable и immutable ConfigMap

| Характеристика | Mutable | Immutable |
| :--- | :--- | :--- |
| Изменяемость | Можно изменять | Нельзя изменять |
| Нагрузка на API server | Выше | Ниже |
| Требует перезапуска | Опционально | Обязательно (при обновлении) |
| Безопасность | Стандартная | Повышенная |
| Use case | Dev, динамические настройки | Production, стабильная конфигурация |

### Связанные документы

* [Создание ConfigMap](./creation.md)
* [Лучшие практики](./best_practices.md)
* [Безопасность Secret](../secrets/security.md)
