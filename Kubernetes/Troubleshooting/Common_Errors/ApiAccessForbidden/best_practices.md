# Ошибки доступа к API: лучшие практики и превентивные меры

## Определения

**Лучшие практики RBAC** — комплекс мер по настройке прав доступа и механизмов аутентификации, направленный на минимизацию рисков возникновения ошибок 401/403 и ограничение "радиуса поражения" в случае компрометации субъекта.

**Принцип наименьших привилегий (Least Privilege)** — предоставление только тех прав, которые минимально необходимы для выполнения конкретной задачи.

> Общие лучшие практики RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)

## Основные концепции

### Ключевые принципы безопасности API

| Принцип | Что предотвращает | Способ реализации |
|---------|-------------------|-------------------|
| **Минимизация Verbs** | Случайное удаление или изменение | Использование `get`, `list` вместо `*` или `update` |
| **Bound Tokens** | Бессрочное использование украденных токенов | Использование `ServiceAccountTokenProjection` |
| **Изоляция Namespace** | Межпроектное влияние | Использование `Role` вместо `ClusterRole` везде, где это возможно |
| **Запрет на default SA** | Неконтролируемый доступ | Создание уникального `ServiceAccount` для каждого приложения |
| **Аудит на основе рисков**| Накопление "мертвых" прав | Использование инструментов анализа (rbac-lookup, Krane) |

### Почему автоматическое монтирование токенов опасно

По умолчанию Kubernetes монтирует токен `ServiceAccount` в каждый под. Если приложению не нужно обращаться к API, наличие этого токена в файловой системе — лишняя уязвимость. С версии 1.22 рекомендуется использовать кратковременные токены с привязкой к поду (Bound Service Account Tokens).

## Практические сценарии

### Сценарий 1: Использование проецируемых токенов (Bound Tokens)

Вместо использования стандартного секрета, который живет вечно, используйте токены с ограниченным сроком жизни и привязкой к аудитории.

**Манифест пода (YAML):**
```yaml
spec:
  containers:
  - name: my-app
    volumeMounts:
    - mountPath: /var/run/secrets/tokens
      name: vault-token
  serviceAccountName: my-sa
  volumes:
  - name: vault-token
    projected:
      sources:
      - serviceAccountToken:
          audience: vault
          expirationSeconds: 3600 # Токен протухнет через час
          path: vault-token
```

### Сценарий 2: Аудит избыточных прав

Регулярно проверяйте, кто в кластере имеет опасные права (например, доступ к секретам или возможность создавать поды).

**Инструменты и команды:**
```bash
# Поиск всех субъектов, имеющих права cluster-admin
kubectl get clusterrolebinding -o json | jq '.items[] | select(.roleRef.name=="cluster-admin") | .subjects'

# Использование rbac-lookup (сторонний инструмент) для поиска прав конкретного пользователя
rbac-lookup <user-name> --output wide

# Проверка: может ли SA 'default' в текущем namespace читать секреты
kubectl auth can-i get secrets --as=system:serviceaccount:$(kubectl config view --minify -o jsonpath='{..namespace}'):default
```

### Сценарий 3: Серверный мониторинг ошибок доступа

Настройте алертинг на основе метрик API-сервера для обнаружения попыток несанкционированного доступа или ошибок в конфигурации приложений.

**Prometheus Rule (YAML):**
```yaml
- alert: KubernetesAPIServerHighForbiddenErrors
  # Используем apiserver_request_total для серверного мониторинга
  expr: sum(rate(apiserver_request_total{code="403"}[5m])) by (resource, subresource) > 0.5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Высокий уровень 403 ошибок на API-сервере"
    description: "Ресурс {{ $labels.resource }} отклоняет запросы по причине Forbidden."

- alert: KubernetesAPIServerAuthFailures
  expr: sum(rate(apiserver_request_total{code="401"}[5m])) > 0.1
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Ошибки аутентификации (401) к API-серверу"
```

## Дополнительная информация

### Чек-лист безопасной настройки доступа

1.  **Индивидуальные SA:** Одно приложение — один ServiceAccount. Никогда не используйте `default`.
2.  **Явное отключение:** Если приложению не нужен доступ к API, установите `automountServiceAccountToken: false` в манифесте SA или Pod.
3.  **Ограничение по ресурсам:** Вместо `resources: ["*"]` перечисляйте только нужные: `["pods", "configmaps"]`.
4.  **Ограничение по именам:** Используйте `resourceNames` для защиты критических конфигураций.
5.  **Аудит:** Минимум раз в квартал проводите ревизию `ClusterRoleBinding` на наличие устаревших записей.
6.  **Инструментарий:** Интегрируйте `kube-bench` или `checkov` в CI/CD для автоматической проверки RBAC-манифестов.

### Связанные ресурсы

- [Алгоритм диагностики ошибок 401/403](diagnostics.md)
- [Распространенные ошибки (RBAC)](common.md)
- [Определения и модель безопасности API](definitions.md)
- [Официальный гайд по безопасности RBAC](https://kubernetes.io/docs/concepts/security/rbac-good-practices/)
