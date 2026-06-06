# Хуки и тестирование в Helm

Механизм выполнения действий на определённых этапах жизненного цикла релиза и автоматизированной проверки корректности развёртывания.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Hook (Хук)** | Ресурс Kubernetes с аннотацией `helm.sh/hook`, выполняющий действия на этапах жизненного цикла релиза (миграции БД, бэкапы, инициализация). См. [Структура Helm-чарта](./helm_chart_structure.md) для общей организации файлов |
| **Test (Тест)** | Специальный хук с аннотацией `helm.sh/hook: test`. Запускается командой `helm test` для проверки корректности развёртывания |
| **hook-weight** | Аннотация `helm.sh/hook-weight`, определяющая порядок выполнения хуков (возрастание, отрицательные значения разрешены) |
| **hook-delete-policy** | Аннотация `helm.sh/hook-delete-policy`, определяющая когда удалять ресурс хука |

---

## Основные концепции

### Жизненный цикл хуков

Ресурс становится хуком при наличии аннотации `helm.sh/hook`.

| Хук | Когда выполняется |
|-----|-------------------|
| `pre-install` | Перед загрузкой ресурсов релиза |
| `post-install` | После установки всех ресурсов релиза |
| `pre-delete` | Перед удалением ресурсов релиза |
| `post-delete` | После удаления всех ресурсов релиза |
| `pre-upgrade` | Перед обновлением релиза |
| `post-upgrade` | После обновления релиза |
| `pre-rollback` | Перед откатом релиза |
| `post-rollback` | После отката релиза |

### Управление хуками

**Вес (`helm.sh/hook-weight`):** упорядочивает выполнение нескольких хуков на одном этапе. Выполнение — в порядке возрастания веса (отрицательные значения разрешены).

**Политика удаления (`helm.sh/hook-delete-policy`):** определяет, когда удалять ресурс хука (хуки не удаляются автоматически с релизом).

| Политика | Поведение |
|----------|-----------|
| `before-hook-creation` | Удаляет предыдущий хук перед запуском нового (по умолчанию) |
| `hook-succeeded` | Удаляет хук после успешного завершения |
| `hook-failed` | Удаляет хук при завершении с ошибкой |

### Механизм тестирования

1. **Расположение:** тестовые манифесты (обычно `Pod` или `Job`) — в директории `templates/tests/`.
2. **Аннотация:** ресурсы помечаются `helm.sh/hook: test`.
3. **Запуск:** `helm test <release_name>`.
4. **Результат:** тест успешен, если под-исполнитель завершается с кодом `0`.

---

## Практические сценарии

### Тест соединения с сервисом

Pod проверяет доступность сервиса внутри кластера.

**`templates/tests/test-connection.yaml`:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: "{{ .Release.Name }}-connection-test"
  annotations:
    "helm.sh/hook": test
spec:
  containers:
    - name: wget
      image: busybox
      command: ['wget']
      args: ['{{ .Release.Name }}-my-service:{{ .Values.service.port }}']
  restartPolicy: Never
```

### Post-install Job

Job запускается после установки релиза, выполняет задачу и удаляется при успехе.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: "{{ .Release.Name }}-post-install-job"
  annotations:
    "helm.sh/hook": post-install
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": hook-succeeded
spec:
  template:
    spec:
      containers:
        - name: post-install-container
          image: alpine:3.3
          command: ["/bin/sleep", "{{ default "10" .Values.sleepyTime }}"]
      restartPolicy: Never
  backoffLimit: 4
```

---

## См. также

- [Основные команды и рабочий процесс Helm](./helm_commands_and_workflow.md)
- [Практические сценарии Helm-чартов](./helm_chart_practical_scenarios.md)
- [Безопасность и лучшие практики Helm](./Advanced/security_best_practices.md)
