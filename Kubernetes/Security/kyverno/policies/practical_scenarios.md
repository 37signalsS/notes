# Библиотека политик Kyverno: Практические примеры

## Определения

**Политика (Policy)** — основной декларативный ресурс Kyverno, содержащий набор правил для автоматизации процессов безопасности, мутации или генерации объектов в кластере.

### Типы ресурсов

*   **ClusterPolicy**: Глобальный ресурс кластера, правила которого применяются ко всем пространствам имен (Namespaces).
*   **Policy**: Локальный ресурс, действующий только в рамках конкретного пространства имен.
*   **ValidatingPolicy / MutatingPolicy (v1.14+)**: Специализированные CEL-ресурсы для повышения производительности и нативной интеграции с Kubernetes API.

---

## Основные концепции

### Структура и стандарты

Примеры в библиотеке ориентированы на стандарты безопасности Kubernetes (PSS — Pod Security Standards) и используют синтаксис Kyverno YAML или CEL (Common Expression Language).

| Параметр | Описание |
| :--- | :--- |
| **`validationFailureAction`** | Режим реакции: `Audit` (запись в отчет) или `Enforce` (блокировка). |
| **`background`** | Включение фонового сканирования для существующих ресурсов (`true`/`false`). |
| **`match` / `exclude`** | Условия выбора ресурсов по типам, пространствам имен или субъектам. |

---

## Практические сценарии

### 1. Запрет привилегированных контейнеров (CEL)

Реализация стандарта **PSS Baseline**. Предотвращает запуск контейнеров, имеющих неограниченный доступ к ресурсам хоста.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: disallow-privileged-containers
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["pods"]
  validations:
    - expression: |
        (object.spec.containers + object.spec.?initContainers.orValue([]) + object.spec.?ephemeralContainers.orValue([])).all(c, 
          !has(c.securityContext) || !has(c.securityContext.privileged) || c.securityContext.privileged == false
        )
      message: "Привилегированные контейнеры запрещены."
```

### 2. Ограничение типов томов (hostPath)

Реализация стандарта **PSS Restricted**. Запрещает использование `hostPath`, предотвращая возможный побег из контейнера на файловую систему узла.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: restrict-host-path
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      resources: ["pods"]
  validations:
    - expression: |
        !has(object.spec.volumes) || object.spec.volumes.all(vol, !has(vol.hostPath))
      message: "Использование hostPath томов запрещено стандартами безопасности."
```

### 3. Автоматическая установка non-root (Мутация)

Автоматизирует процесс приведения ресурсов к безопасному виду, принудительно устанавливая `runAsNonRoot: true`, если это не противоречит логике приложения.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: mutate-run-as-non-root
spec:
  rules:
    - name: set-non-root
      match:
        any:
          - resources:
              kinds:
                - Pod
      mutate:
        patchStrategicMerge:
          spec:
            securityContext:
              runAsNonRoot: true
              runAsUser: 1000
```

### 4. Синхронизация ConfigMap между Namespace (Генерация)

Позволяет автоматически копировать конфигурации (например, настройки прокси или корпоративные сертификаты) во все новые пространства имен.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: sync-global-config
spec:
  rules:
    - name: copy-configmap
      match:
        any:
          - resources:
              kinds:
                - Namespace
      generate:
        kind: ConfigMap
        name: global-config
        namespace: "{{request.object.metadata.name}}"
        clone:
          namespace: default
          name: source-config
        synchronize: true
```

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Постепенное внедрение**: Новые политики следует внедрять в режиме `Audit` (или `Warn` для CEL). Используйте **[Policy Reports](../reports.md)** для анализа нарушений перед блокировкой.
2.  **Исключения (PolicyException)**: Вместо загромождения блока `exclude` внутри политики, используйте отдельный ресурс `PolicyException` для временных или специфических разрешений.
3.  **Исключение системных ресурсов**: Всегда добавляйте `exclude` для `kube-system`, `kyverno` и других критических инфраструктурных пространств имен, чтобы избежать блокировки кластера.
4.  **Валидация в CI/CD**: Используйте `kyverno CLI` для проверки манифестов на этапе сборки (Shift-Left Security).

### См. также

- **[Типы правил (подробный синтаксис)](../rules.md)** — match, validate, mutate, generate.
- **[Определения и структура](./definitions_and_concepts.md)** — база для написания манифестов.
- **[Фоновое сканирование](../background.md)** — аудит уже запущенных объектов.
- **[Отчеты (Policy Reports)](../reports.md)** — анализ результатов выполнения политик.
