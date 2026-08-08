# Ошибки доступа к API: лучшие практики и превентивные меры

## Определения

**Лучшие практики безопасности API** — комплекс архитектурных и эксплуатационных мер, направленных на минимизацию рисков возникновения ошибок 401 (Аутентификация) и 403 (Авторизация/Admission), а также на ограничение "радиуса поражения" при компрометации субъектов.

**Принцип наименьших привилегий (Principle of Least Privilege, PoLP)** — базовый стандарт безопасности, требующий предоставления субъекту (пользователю или приложению) только того набора прав, который минимально необходим для выполнения его функций.

> Общий обзор безопасности RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)

## Основные концепции

### Стратегия предотвращения ошибок доступа

Эффективная защита строится на трех уровнях, каждый из которых предотвращает определенный класс ошибок 401/403.

| Уровень | Технология | Предотвращаемая проблема |
|---------|------------|--------------------------|
| **Аутентификация** | TokenRequest API / OIDC | Утечка бессрочных токенов, ошибки 401 из-за ротации. |
| **Авторизация** | Гранулярный RBAC | Ошибки 403 из-за избыточных прав или опечаток в ресурсах. |
| **Политики (Admission)** | ValidatingAdmissionPolicy (CEL) | Нарушение стандартов безопасности (PSA), блокировки 403. |

### Почему традиционные секреты SA (Static Tokens) опасны

До версии 1.22 Kubernetes автоматически создавал бессрочный JWT-токен в объекте `Secret` для каждого ServiceAccount. 
1. **Риск 401:** При компрометации токен сложно отозвать без удаления SA.
2. **Риск 403:** Автоматическое монтирование токена (`automountServiceAccountToken: true`) предоставляет подам права доступа к API "по умолчанию", что противоречит принципу PoLP.

## Практические сценарии

### Сценарий 1: Переход на проецируемые токены (Bound Tokens)

Используйте механизм `ServiceAccountTokenProjection` для получения кратковременных токенов, привязанных к жизненному циклу пода.

**Эталонная конфигурация (YAML):**
```yaml
spec:
  automountServiceAccountToken: false # Отключение стандартного токена
  containers:
  - name: secure-app
    volumeMounts:
    - mountPath: /var/run/secrets/tokens
      name: bound-token
  serviceAccountName: app-sa
  volumes:
  - name: bound-token
    projected:
      sources:
      - serviceAccountToken:
          audience: api-server
          expirationSeconds: 3600 # Токен действителен 1 час
          path: bound-token
```

### Сценарий 2: Использование нативных политик CEL (ValidatingAdmissionPolicy)

Вместо сложных внешних вебхуков (которые могут возвращать 403 из-за сетевых таймаутов), используйте нативные политики Kubernetes (1.30+).

**Пример политики (запрет удаления критических ConfigMap):**
```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: protect-critical-configs
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["DELETE"]
      resources: ["configmaps"]
  validations:
    - expression: "object.metadata.name != 'core-config'"
      message: "Удаление core-config запрещено политикой безопасности."
```

### Сценарий 3: Автоматизация аудита RBAC в CI/CD

Предотвращайте попадание некорректных RBAC-манифестов в кластер с помощью статического анализа.

**Инструменты:**
*   **Kube-bench:** Проверка кластера на соответствие CIS Benchmark.
*   **Checkov / Terrascan:** Сканирование YAML на наличие `ClusterRoleBinding` с избыточными правами.
*   **Krane:** Визуализация графа RBAC и поиск опасных связей.

```bash
# Пример проверки манифестов перед деплоем
checkov -d ./kubernetes-manifests/ --check CKV_K8S_1,CKV_K8S_49
```

### Сценарий 4: Мониторинг и алертинг ошибок 401/403

Настройте обнаружение аномалий в поведении приложений через метрики API-сервера.

**Prometheus Rule:**
```yaml
- alert: HighRateOfRBACForbidden
  # Отслеживание всплеска 403 ошибок для конкретных ServiceAccounts
  expr: sum(rate(apiserver_request_total{code="403"}[5m])) by (username, resource) > 1
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Подозрительная активность субъекта {{ $labels.username }}"
    description: "Субъект пытается получить доступ к {{ $labels.resource }}, но получает отказ."
```

## Дополнительная информация

### Чек-лист превентивных мер

1.  **Принудительный отказ от default:** Устанавливайте `automountServiceAccountToken: false` на уровне `default` ServiceAccount в каждом неймспейсе.
2.  **Изоляция через ResourceNames:** Для критических секретов всегда указывайте список разрешенных имен объектов.
3.  **Namespace-scoping:** Избегайте `ClusterRoleBinding` для приложений. Используйте `RoleBinding` даже при ссылке на `ClusterRole`.
4.  **Регулярная ротация CA:** Используйте `kubeadm certs renew` для предотвращения ошибок 401 из-за просроченных сертификатов управляющего слоя.
5.  **Контроль API Priority and Fairness:** Настройте лимиты для "шумных" потребителей, чтобы предотвратить 429/403 ошибки при перегрузке API.

### Связанные ресурсы

- [Алгоритм диагностики 401/403](diagnostics.md)
- [Практические примеры RBAC для 403](common.md)
- [Расширенные сценарии (Admission)](advanced.md)
- [Определения и модель безопасности API](definitions.md)
- [Официальный гайд по безопасности Kubernetes](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
