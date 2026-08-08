# Сценарии безопасности Kyverno

## Определения

**Сценарии безопасности** — практические руководства по реализации защитных механизмов кластера Kubernetes с использованием декларативных политик Kyverno. Сценарии охватывают превентивную блокировку угроз, автоматическое исправление конфигураций и непрерывный аудит на соответствие стандартам (PSS, CIS Benchmark).

В современной инфраструктуре (2025–2026) сценарии безопасности базируются на **CEL (Common Expression Language)** и интеграции с **Sigstore**, что обеспечивает нативную производительность и защиту на всех этапах жизненного цикла артефактов.

---

## Основные концепции

### Эшелонированная защита (Defense in Depth)

Применение Kyverno в контуре безопасности строится по принципу многоуровневого контроля:

| Уровень | Техническая реализация | Цель |
| :--- | :--- | :--- |
| **Admission Control** | `ValidatingPolicy` (CEL) | Блокировка небезопасных ресурсов до их попадания в API-сервер. |
| **Supply Chain** | `ImageValidatingPolicy` | Проверка подлинности образов, аттестаций SLSA и SBOM. |
| **Hardening** | `MutatingPolicy` | Автоматическая инъекция `securityContext` и меток безопасности. |
| **Post-deployment** | `Background Scan` | Выявление дрейфа конфигураций и нарушений в уже запущенных объектах. |

### Сосуществование с Pod Security Admission (PSA)

Kyverno дополняет встроенный механизм PSA, закрывая его архитектурные ограничения:
- **Гибкость**: Kyverno позволяет создавать исключения на уровне конкретных подов или правил через `PolicyException`.
- **Автоматизация**: Kyverno может исправлять (mutate) ресурсы, в то время как PSA умеет только блокировать.
- **Наблюдаемость**: Kyverno генерирует детализированные `PolicyReport`, видимые в интерфейсах мониторинга.

---

## Практические сценарии

### 1. Реализация профиля PSS Restricted (CEL)

**Проблема**: Стандартный PSA Restricted может быть слишком жестким или недостаточно гибким для специфических приложений.

**Решение**: Использование `ValidatingPolicy` для точечной проверки параметров Restricted-профиля с высокой производительностью.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: pss-restricted-hardening
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        resources: ["pods"]
  validations:
    - expression: |
        (object.spec.containers + object.spec.?initContainers.orValue([])).all(c, 
          has(c.securityContext) && 
          c.securityContext.allowPrivilegeEscalation == false &&
          c.securityContext.runAsNonRoot == true &&
          c.securityContext.capabilities.drop.contains("ALL")
        )
      message: "Нарушение стандартов PSS Restricted: проверьте привилегии и capabilities."
```

### 2. Верификация аттестаций SBOM и SLSA

**Проблема**: Факт подписи образа не гарантирует отсутствие уязвимостей или соответствие процесса сборки стандартам безопасности.

**Решение**: Проверка аттестаций (доказательств), прикрепленных к образу в реестре.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: verify-supply-chain-attestations
spec:
  rules:
    - name: check-sbom-presence
      imageReferences: ["ghcr.io/my-company/*"]
      attestations:
        - name: verify-cyclonedx
          type: "https://cyclonedx.org/bom"
          attestors:
            - entries:
                - keys:
                    publicKeys: "MFkwEwYHKo..."
# Политика заблокирует образ, если к нему не приложен подписанный SBOM.
```

### 3. Сетевое закаливание (Network Hardening)

**Проблема**: Использование небезопасных портов (например, 22/SSH) внутри контейнеров увеличивает риск горизонтального перемещения злоумышленника.

**Решение**: Валидация портов контейнеров через CEL-фильтры.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: disallow-unsafe-ports
spec:
  validations:
    - expression: |
        object.spec.containers.all(c, 
          !has(c.ports) || c.ports.all(p, p.containerPort != 22 && p.containerPort != 23)
        )
      message: "Использование портов SSH (22) и Telnet (23) внутри подов запрещено."
```

### 4. Автоматическая инъекция Security Context (Mutation)

**Проблема**: Ошибки конфигурации в манифестах разработчиков приводят к отказам в Admission Control.

**Решение**: Автоматическое приведение подов к безопасному виду без участия человека.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: auto-inject-hardening
spec:
  rules:
    - name: inject-root-prevention
      match:
        any:
          - resources:
              kinds: [Pod]
      mutate:
        patchStrategicMerge:
          spec:
            securityContext:
              runAsNonRoot: true
              seccompProfile:
                type: RuntimeDefault
```

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Shift-Left**: Интегрируйте `kyverno CLI` в CI-пайплайны для раннего обнаружения нарушений. Это снижает «шум» в Admission-контроллере.
2.  **Управление исключениями**: Для временных допусков используйте ресурс `PolicyException`. Никогда не редактируйте основную политику для решения локальных проблем одной команды.
3.  **Безопасность системных Namespace**: Всегда добавляйте `kube-system` и `kyverno` в `exclude` правил мутации, чтобы предотвратить циклические блокировки (Deadlocks).
4.  **Мониторинг дрейфа**: Используйте [Policy Reporter](../reporter.md) для анализа результатов фонового сканирования. Обычные ошибки в существующих ресурсах не должны игнорироваться.

### См. также

- **[Типы правил: глубокое погружение](../rules.md)** — синтаксис validate, mutate, verifyImages.
- **[Библиотека практических примеров](../policies/practical_scenarios.md)** — расширенный набор YAML для копирования.
- **[Система отчетов Policy Reports](../reports.md)** — как работать с результатами проверок.
- **[Security Context в Kubernetes](../../pod_security_context.md)** — описание параметров безопасности.
