# Практические сценарии Kyverno

## Определения

**Практические сценарии Kyverno** — структурированный набор руководств по реализации концепции **Policy-as-Code** для решения типовых и продвинутых задач администрирования Kubernetes. Сценарии охватывают полный жизненный цикл ресурсов: от превентивной блокировки угроз до автоматизации операционных процессов и очистки устаревших данных.

Каждый сценарий представляет собой самодостаточное руководство с описанием проблемы, решением на YAML и рекомендациями по эксплуатации. Навигация по сценариям организована по операционным доменам (безопасность, автоматизация, очистка), чтобы администратор мог быстро найти релевантное руководство.

---

## Основные концепции

### Категории сценариев (Стандарт 2026)

В современной инфраструктуре использование Kyverno разделено на шесть стратегических направлений:

| Категория | Ключевые задачи | Основной источник |
| :--- | :--- | :--- |
| **Безопасность (PSS)** | Внедрение Pod Security Standards (Baseline, Restricted) и Hardening. | [Сценарии безопасности](./security_policies.md) |
| **Supply Chain Security** | Верификация подписей, аттестаций SLSA и содержимого SBOM. | [Очистка и верификация](./cleanup_verification.md) |
| **Автоматизация Платформы** | Синхронизация секретов, инъекция sidecar-контейнеров и меток. | [Автоматизация и комплаенс](./automation_compliance.md) |
| **Compliance & Audit** | Соответствие стандартам CIS, PCI DSS 4.0, NIS2 и HIPAA. | [Автоматизация и комплаенс](./automation_compliance.md) |
| **FinOps & Resource Mgmt** | Контроль лимитов, автоматическая очистка неиспользуемых ресурсов. | [Очистка и верификация](./cleanup_verification.md) |
| **Multi-tenancy Isolation** | Глубокая изоляция команд, автоматизация NetworkPolicies и квот. | [Автоматизация и комплаенс](./automation_compliance.md) |

### Матрица выбора сценария

Для определения нужного руководства воспользуйтесь таблицей соответствия задач:

| Задача | Категория | Рекомендуемый сценарий |
| :--- | :--- | :--- |
| Запретить привилегированные контейнеры | Безопасность | [PSS Restricted (CEL)](./security_policies.md#1-реализация-профиля-pss-restricted-cel) |
| Запретить небезопасные порты (SSH, Telnet) | Безопасность | [Network Hardening](./security_policies.md#3-сетевое-закаливание-network-hardening) |
| Автоматически добавить securityContext | Безопасность | [Auto-inject Security Context](./security_policies.md#4-автоматическая-инъекция-security-context-mutation) |
| Проверить подпись образа (Sigstore) | Supply Chain | [Keyless-верификация](./cleanup_verification.md#3-keyless-верификация-через-github-actions) |
| Проверить SBOM или аттестацию сборки | Supply Chain | [Верификация аттестаций](./security_policies.md#2-верификация-аттестаций-sbom-и-slsa) |
| Автоматически создать квоту для Namespace | Автоматизация | [Инициализация Namespace](./automation_compliance.md#3-инициализация-namespace-multi-tenancy) |
| Внедрить корпоративный прокси во все поды | Автоматизация | [Инъекция Proxy](./automation_compliance.md#4-глобальная-инъекция-proxy-настроек-mutation) |
| Заблокировать TLS ниже 1.3 (PCI DSS) | Compliance | [PCI DSS TLS](./automation_compliance.md#2-соответствие-pci-dss-40-контроль-шифрования) |
| Удалить завершенные Job или осиротевшие PV | Очистка | [Очистка ресурсов](./cleanup_verification.md#2-очистка-осиротевших-ресурсов-orphaned-resources) |
| Управление временными средами (TTL) | Очистка | [TTL-очистка](./cleanup_verification.md#1-автоматическая-очистка-временных-сред-ttl) |
| Интегрировать проверку в CI/CD | Автоматизация | [Shift-Left](./automation_compliance.md#1-интеграция-в-cicd-пайплайн-shift-left) |

---

## Стратегия внедрения сценариев

### Поэтапный процесс (Staged Rollout)

Любой сценарий должен внедряться поэтапно. Ускорение этого процесса — основная причина инцидентов в политике.

**Этап 1. Подготовка**
1. Определите проблему и выберите сценарий по матрице выше.
2. Убедитесь, что Kyverno установлен и работает (см. [install.md](../install.md)).
3. Проверьте RBAC-права: `kubectl auth can-i create policies.kyverno.io/validatingpolicy -A` (для v2) или `kubectl auth can-i create clusterpolicy` (для v1).
4. Убедитесь, что целевые Namespace не являются системными (`kube-system`, `kube-public`, `kyverno`).

**Этап 2. Тестирование (Dry-Run)**
1. Примените политику в режиме `Audit`:
   ```yaml
   # Для v1 (ClusterPolicy)
   spec:
     validationFailureAction: Audit

   # Для v2 (ValidatingPolicy)
   spec:
     validationActions: [Audit]
   ```
2. Проверьте отсутствие ошибок в логах контроллера:
   ```bash
   kubectl logs -n kyverno -l app.kubernetes.io/name=kyverno -c admission-controller --tail=50
   ```
3. Дождитесь фонового сканирования (обычно 15–30 минут для полного цикла).

**Этап 3. Анализ**
1. Просмотрите результаты:
   ```bash
   kubectl get polr -A                        # Namespace-scoped отчеты
   kubectl get cpolr                          # Cluster-scoped отчеты
   kubectl get admissionreport -A             # Отчеты по конкретным запросам
   ```
2. Проанализируйте количество срабатываний и их распределение по Namespace.
3. Идентифицируйте ложноположительные срабатывания (ресурсы, которые не должны блокироваться).

**Этап 4. Корректировка**
1. Если есть ложноположительные срабатывания, используйте:
   - `PolicyException` — для точечных разрешений (см. [practical_scenarios.md](../policies/practical_scenarios.md#12-исключения-через-policyexception-devops-сценарий)).
   - Блок `exclude` — для исключения целых Namespace или субъектов.
2. Повторите этапы 2–3 до тех пор, пока количество ложноположительных не будет приемлемым.

**Этап 5. Внедрение (Enforce)**
1. Переключите политику в `Enforce` / `Deny`.
2. Мониторьте первые 24–48 часов:
   ```bash
   # Проверка блокировок в реальном времени
   kubectl get events -A --field-selector reason=PolicyViolation

   # Проверка UpdateRequests (для generate/mutate)
   kubectl get updaterequests -n kyverno
   ```
3. При возникновении критических блокировок — откатите политику в `Audit` и проанализируйте причину.

---

## Рекомендации по версионированию (v1 vs v2)

В 2026 году в кластере сосуществуют два поколения API Kyverno. Выбор версии зависит от типа задачи и требуемой производительности.

### Когда использовать v1 (ClusterPolicy / Policy)

| Сценарий | Причина |
| :--- | :--- |
| `generate` — создание ресурсов | v2 `GeneratingPolicy` находится в стадии развития, `generate` в v1 более зрелый. |
| `mutate` — сложные мутации | JMESPath-шаблоны (`patchStrategicMerge`, `patchJSON6902`) в v1 проще для нетривиальных изменений. |
| `verifyImages` — статические ключи | v1 `verifyImages` с `attestors` и `attestations` — проверенный механизм. |
| `mutateExisting` — мутация существующих ресурсов | v1 нативно поддерживает `generate.mutateExisting`. |
| Нужна совместимость со старым GitOps | Если политики уже хранятся как `ClusterPolicy` и не требуют переписывания. |

**Важно**: `ClusterPolicy` deprecated (удаление запланировано в v1.20). Планируйте миграцию на v2.

### Когда использовать v2 (ValidatingPolicy / MutatingPolicy / GeneratingPolicy)

| Сценарий | Причина |
| :--- | :--- |
| Валидация без мутации | `ValidatingPolicy` транслируется в нативный `ValidatingAdmissionPolicy` Kubernetes — задержка <1 мс вместо 5–15 мс (вебхук). |
| Мутация через CEL | `MutatingPolicy` с `ApplyConfiguration` или `JSONPatch` через CEL. |
| Генерация ресурсов через CEL | `GeneratingPolicy` с CEL-условиями для триггеров. |
| Высоконагруженные кластеры | Отсутствие сетевого вызова вебхука снижает нагрузку на API-сервер. |
| Цель — долгосрочная стратегия | v2 — будущее Kyverno; v1 будет удален в v1.20. |

### Порядок миграции с v1 на v2

1. **Валидация**: Начните с `ValidatingPolicy` — это самый простой переход (JMESPath → CEL).
2. **Мутация**: Оцените `MutatingPolicy`, если мутации не требуют `patchStrategicMerge` (CEL не поддерживает его нативно).
3. **Генерация**: Перейдите на `GeneratingPolicy`, когда он достигнет GA.
4. **verifyImages**: Используйте `ImageValidatingPolicy` (v2) для keyless-верификации; статические ключи пока работают лучше в v1.

---

## Предварительные требования

Перед внедрением любого сценария убедитесь в следующем:

| Компонент | Минимальная версия | Проверка |
| :--- | :--- | :--- |
| Kubernetes | 1.25+ (для VAP) | `kubectl version --short` |
| Kyverno | 1.19+ | `kubectl get deployment -n kyverno kyverno -o jsonpath='{.spec.template.spec.containers[0].image}'` |
| Kyverno CLI | 1.19+ | `kyverno --version` (для Shift-Left тестирования) |
| Sigstore cosign | 2.0+ | `cosign version` (для сценариев верификации образов) |

### RBAC-подготовка

Для корректной работы фоновых операций (generate, cleanup) контроллеры Kyverno должны иметь соответствующие права:

```bash
# Проверка прав background-controller на создание ResourceQuota
kubectl auth can-i create resourcequotas \
  --as=system:serviceaccount:kyverno:kyverno-background-controller

# Проверка прав cleanup-controller на удаление PersistentVolume
kubectl auth can-i delete persistentvolumes \
  --as=system:serviceaccount:kyverno:kyverno-cleanup-controller
```

Если какие-то команды возвращают `no`, обратитесь к [руководству по агрегированным ролям](../additional.md) для настройки RBAC.

---

## Навигация по специализированным руководствам

### 1. Политики безопасности (Security & Hardening)
Сценарии, направленные на минимизацию поверхности атаки и предотвращение запуска небезопасных нагрузок.
- **PSS Enforcement**: Реализация профилей Baseline и Restricted через CEL.
- **Network Hardening**: Запрет использования небезопасных портов и протоколов.
- **Runtime Protection**: Контроль привилегий и доступа к файловой системе хоста.
- [Подробные сценарии безопасности](./security_policies.md)

### 2. Автоматизация и комплаенс (Platform Engineering)
Решение задач по автоматизации рутинных операций и подтверждению соответствия регуляторным требованиям.
- **Namespace Provisioning**: Автоматическое создание квот, лимитов и сетевых политик для новых команд.
- **Secret Management**: Синхронизация Docker Registry Credentials и CA-сертификатов.
- **Compliance Reporting**: Генерация отчетов для аудита PCI DSS и NIS2.
- [Подробные сценарии автоматизации](./automation_compliance.md)

### 3. Очистка ресурсов и верификация (Operations & Supply Chain)
Поддержание гигиены кластера и обеспечение доверия к используемым образам ПО.
- **Resource Cleanup**: Удаление завершенных Job и временных Namespace по TTL-меткам.
- **Image Verification**: Проверка подписей Sigstore/Cosign и аттестаций сборки.
- **SBOM Validation**: Проверка состава ПО на наличие запрещенных компонентов.
- [Подробные сценарии очистки и верификации](./cleanup_verification.md)

---

## Мониторинг после внедрения

После перевода политики в `Enforce` необходимо обеспечить наблюдаемость за её работой.

### Просмотр результатов

```bash
# Общая статистика нарушений по Namespace
kubectl get polr -A -o custom-columns=\
  NAMESPACE:.metadata.namespace,\
  PASS:.summary.pass,\
  FAIL:.summary.fail,\
  WARN:.summary.warn

# Кластерные нарушения
kubectl get cpolr -o custom-columns=\
  NAME:.metadata.name,\
  PASS:.summary.pass,\
  FAIL:.summary.fail

# Последние Admission-отчеты (для отладки конкретных запросов)
kubectl get admissionreport -A --sort-by=.metadata.creationTimestamp | tail -20
```

### Автоматизация отчетности

Для регулярной генерации отчетов для аудиторов используйте [Policy Reporter](../reporter.md). Он предоставляет веб-интерфейс, метрики Prometheus и интеграцию с каналами уведомлений (Slack, Teams).

---

## Типичные ошибки при внедрении сценариев

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Политика блокирует создание подов в `kube-system` | Системные Namespace не исключены в `exclude`. | Добавьте `kube-system`, `kube-public`, `kyverno` в `exclude.resources.namespaces`. |
| `generate` не создает ресурсы в новом Namespace | `synchronize: false` или нет триггера. | Установите `synchronize: true` и проверьте `kubectl get updaterequests -n kyverno`. |
| Фоновое сканирование не находит нарушения | `background: false` или политика создана после ресурсов. | Установите `background: true` (v1) и дождитесь следующего цикла сканирования (до 6 часов). |
| Мутация не применяется к существующим подам | Kyverno не мутирует уже созданные ресурсы без `mutateExisting`. | Используйте `mutateExisting` + `background: true` (v1) или `evaluation.mutateExisting.enabled: true` (v2). |
| CEL-политика падает с ошибкой компиляции | Неверный синтаксис CEL в `expression`. | Используйте `kubectl create ... --dry-run=Server` для валидации перед применением. |
| `PolicyException` не действует | Имя политики или правила не совпадает с манифестом. | Проверьте `policyName` и `ruleNames` в `PolicyException`. |
| Зависшие UpdateRequests | Ошибка при мутации/генерации из-за RBAC или конфликта. | `kubectl describe updaterequest <ur-name> -n kyverno` для диагностики. |
| Высокая задержка API после внедрения CEL-политики | Используется v1 `ClusterPolicy` вместо v2 `ValidatingPolicy`. | Мигрируйте на `ValidatingPolicy` (v2) для снижения задержки. |

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Стратегия Audit-First**: Любой новый сценарий должен внедряться в режиме `validationFailureAction: Audit`. Это позволяет оценить влияние на существующую нагрузку без риска остановки сервисов.
2.  **Использование PolicyException**: Вместо прямого редактирования блоков `exclude` в глобальных политиках, используйте ресурс `PolicyException` для предоставления точечных разрешений.
3.  **CEL-First**: При адаптации сценариев используйте нативные `ValidatingPolicy` (v2) для снижения задержек API-сервера. JMESPath-шаблоны (v1) используйте только для сложных мутаций.
4.  **Интеграция с GitOps**: Храните манифесты сценариев в репозитории и используйте Argo CD для синхронизации, включив Server-Side Apply (подробнее в [argo-cd.md](../argo-cd.md)).
5.  **Версионирование**: Учитывайте, что `ClusterPolicy` deprecated (удаление в v1.20). Планируйте миграцию на v2 API заранее.

### См. также

- **[Типы правил (подробно)](../rules.md)** — синтаксис validate, mutate, generate, cleanup.
- **[Библиотека практических примеров](../policies/practical_scenarios.md)** — компактные YAML-примеры для копирования.
- **[Основные концепции Kyverno](../concepts.md)** — архитектура и сравнение с OPA/Gatekeeper.
- **[Отчеты (Policy Reports)](../reports.md)** — анализ результатов выполнения политик.
